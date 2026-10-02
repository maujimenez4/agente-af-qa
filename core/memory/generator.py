"""Memoria sintética de un artefacto publicado con salida estructurada (RF-36, RNF-25).

`LLMMemoryGenerator` depende solo del protocolo `LLMProvider` y no distingue el tipo de artefacto:
los IDs y las fuentes válidas salen del contenido (HU o suite de QA). En el MVP el nodo
`memorize` solo lo llama para HU publicadas (D-07).

La salida del LLM no se da por buena: la identidad (`artifact_type`, `jira_key`, `version`) sale
del artefacto, las referencias se filtran contra sus fuentes, cada entrada se reduce a una línea
(sin encabezados ni `---` que falseen el `.md`) y se exige que los IDs de CA y RN existan y estén
todos. Si algo falla se reintenta una vez con los errores; si persiste, `MemorySynthesisError`.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from adapters.base import LLMProvider, Message, TaskType
from adapters.errors import AgentError
from core.functional.context import escape_data
from core.functional.writer import fill_placeholders
from core.logging import get_logger
from core.projects import ISSUE_KEY
from core.qa.validation import _personal_data_kind  # PA-250: hacerlo público en core/qa
from core.rag.prompts import Prompt, load_prompt
from schemas.artifact import Artifact
from schemas.memory import Memory
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

PromptLoader = Callable[[str], Prompt]

log = get_logger("core.memory")

TRACE_ID = re.compile(r"\b(?:CA|RN)-\d+\b")
_HEADING = re.compile(r"^#+\s*")
_RULE_LINE = re.compile(r"[-=*_~\s]+")
# Formas habituales de secretos: no deben llegar a la memoria, que se reindexa en el RAG.
_SECRET = re.compile(
    r"(?i)\bbearer\s+[\w.~+/-]{12,}"
    r"|\beyJ[\w-]{8,}\.[\w-]{8,}\."
    r"|\b(?:sk|gsk|ghp|xox[bp])[-_][\w-]{16,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\b[a-z][\w+.-]*://[^\s:/@]+:[^\s@]+@"  # cadena de conexión con credenciales
    # PA-218: tras «contraseña:» solo cuenta un valor que lo parezca: con dígitos o símbolos,
    # con una mayúscula en medio (frase de paso, «CorrectoCaballo») o de 16 letras o más.
    # «La contraseña: mínimo ocho caracteres» es una regla de negocio, no un secreto.
    r"|\b(?:api[_ -]?key|clave(?:[_ ]api)?|password|contraseña|secret)\s*[:=]\s*"
    r"(?:(?=\S*[\d_\-+/=@#$%&*!~])\S{6,}|(?-i:(?=\S*[a-zà-ÿ][A-Z]))\S{6,}|\w{16,})"
)
MAX_SHOWN = 80
_LIST_FIELDS = (
    "business_rules",
    "decisions",
    "dependencies",
    "changes",
    "acceptance_criteria",
)


class MemorySynthesisError(AgentError):
    """La memoria no es válida tras el reintento; mensaje en español para la UI."""


@dataclass(frozen=True)
class ArtifactFacts:
    """Lo que la memoria puede afirmar del artefacto, sacado de él y no del LLM."""

    jira_key: str
    criteria: tuple[str, ...]  # CA del artefacto, en orden
    rules: tuple[str, ...]  # RN del artefacto, en orden
    references: tuple[str, ...]  # `ref` de las fuentes que cita

    @property
    def ids(self) -> tuple[str, ...]:
        return (*self.criteria, *self.rules)


def artifact_facts(artifact: Artifact) -> ArtifactFacts:
    content = artifact.content
    if isinstance(content, UserStory):
        key = content.jira_key
        ids = [c.id for c in content.acceptance_criteria] + [r.id for r in content.business_rules]
    elif isinstance(content, TestSuite):
        key = content.story_jira_key
        ids = list(content.coverage())
    else:  # pragma: no cover - Artifact solo admite estos dos tipos
        raise TypeError(type(content).__name__)
    jira_key = key or artifact.origin_key
    if not jira_key or not ISSUE_KEY.fullmatch(jira_key):
        raise MemorySynthesisError(
            "No se puede generar la memoria: el artefacto no tiene una clave de Jira válida."
        )
    return ArtifactFacts(
        jira_key=jira_key,
        criteria=tuple(i for i in ids if i.startswith("CA-")),
        rules=tuple(i for i in ids if i.startswith("RN-")),
        references=tuple(dict.fromkeys(s.ref for s in content.sources)),
    )


def render_artifact(artifact: Artifact) -> str:
    """El artefacto como dato no confiable, escapado y delimitado."""
    data = json.dumps(artifact.content.model_dump(mode="json"), ensure_ascii=False)
    return (
        f'<artefacto tipo="{artifact.type.value}" version="{artifact.version}">\n'
        f"{escape_data(data)}\n</artefacto>"
    )


def sanitize(memory: Memory, artifact: Artifact, facts: ArtifactFacts) -> Memory:
    """Identidad del artefacto, una línea por entrada y solo referencias que el artefacto cita."""
    allowed = set(facts.references)
    references: list[str] = []
    for raw in memory.references:
        ref = _one_line(raw)
        kind, sep, rest = ref.partition(":")
        if ref not in allowed and sep and kind in ("jira", "rag", "memory"):
            ref = rest.strip()  # «rag:doc-x» → «doc-x»
        if ref in allowed and ref not in references:
            references.append(ref)
    lists = {
        name: [line for item in getattr(memory, name) if (line := _one_line(item))]
        for name in _LIST_FIELDS
    }
    return Memory(
        artifact_type=artifact.type,
        jira_key=facts.jira_key,
        version=artifact.version,
        objective=_one_line(memory.objective),
        scope=_one_line(memory.scope),
        references=references,
        **lists,
    )


def memory_errors(memory: Memory, facts: ArtifactFacts) -> list[str]:
    """Problemas de la memoria saneada; vacía si es válida. Nunca repite datos sensibles."""
    errors: list[str] = []
    known = set(facts.ids)
    unknown = sorted({i for text in _texts(memory) for i in TRACE_ID.findall(text)} - known)
    if unknown:
        errors.append(f"IDs que no existen en el artefacto: {', '.join(unknown)}")
    missing = _missing(facts.criteria, memory.acceptance_criteria)
    if missing:
        errors.append(f"faltan criterios de aceptación: {', '.join(missing)}")
    missing = _missing(facts.rules, memory.business_rules)
    if missing:
        errors.append(f"faltan reglas de negocio: {', '.join(missing)}")
    for name, text in _named_texts(memory):
        if kind := _personal_data_kind(text):
            errors.append(f"«{name}» parece contener un dato personal ({kind})")
        if _SECRET.search(text):
            errors.append(f"«{name}» parece contener un secreto")
    return list(dict.fromkeys(errors))


def _has_sensitive_data(memory: Memory) -> bool:
    return any(_personal_data_kind(t) or _SECRET.search(t) for t in _texts(memory))


class LLMMemoryGenerator:
    """`MemoryGenerator` con el LLM de la tarea `synthesize_memory` (SPEC-00 §4)."""

    def __init__(self, llm: LLMProvider, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self._llm = llm
        self._load = prompt_loader

    def generate(self, artifact: Artifact) -> Memory:
        started = time.perf_counter()
        facts = artifact_facts(artifact)
        prompt = self._load("synthesize_memory")
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=render_artifact(artifact)),
        ]
        result = self._llm.generate_structured(messages, Memory, TaskType.SYNTHESIZE_MEMORY)
        memory = sanitize(result.content, artifact, facts)
        errors = memory_errors(memory, facts)
        if errors:
            # La respuesta anterior solo se reenvía si no lleva datos sensibles.
            previous = (
                []
                if _has_sensitive_data(memory)
                else [Message(role="assistant", content=memory.model_dump_json())]
            )
            retry_messages = [
                *messages,
                *previous,
                Message(role="user", content=self._retry_text(errors, facts)),
            ]
            result = self._llm.generate_structured(
                retry_messages, Memory, TaskType.SYNTHESIZE_MEMORY
            )
            memory = sanitize(result.content, artifact, facts)
            if memory_errors(memory, facts):
                raise MemorySynthesisError(
                    "No se pudo generar una memoria válida de "
                    f"{facts.jira_key}: no recoge fielmente sus criterios y reglas o incluye "
                    "datos no permitidos. Vuelve a intentarlo."
                )
        log.info(
            "memoria sintetizada",
            action="synthesize_memory",
            artifact_id=str(artifact.id),
            model=result.model,
            prompt_version=prompt.version,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return memory

    def _retry_text(self, errors: list[str], facts: ArtifactFacts) -> str:
        return fill_placeholders(
            self._load("memory_retry").text,
            {
                "errors": "\n".join(f"- {escape_data(e[: MAX_SHOWN * 4])}" for e in errors),
                "ids": ", ".join(facts.ids) or "(ninguno)",
                "allowed": "\n".join(f"- {escape_data(r[:MAX_SHOWN])}" for r in facts.references)
                or "- (ninguna)",
            },
        )


def _one_line(text: str) -> str:
    line = _HEADING.sub("", " ".join(text.split()))
    return "" if _RULE_LINE.fullmatch(line) else line


def _missing(expected: tuple[str, ...], items: list[str]) -> list[str]:
    present = {i for item in items for i in TRACE_ID.findall(item)}
    return [i for i in expected if i not in present]


def _named_texts(memory: Memory) -> list[tuple[str, str]]:
    texts = [("objective", memory.objective), ("scope", memory.scope)]
    for name in (*_LIST_FIELDS, "references"):
        texts += [(name, item) for item in getattr(memory, name)]
    return texts


def _texts(memory: Memory) -> list[str]:
    return [text for _, text in _named_texts(memory)]
