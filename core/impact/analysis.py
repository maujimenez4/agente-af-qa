"""Análisis de impacto de una HU nueva o evolucionada (T-21, RF-19, RF-27).

- `diffs`: siempre el diff determinista frente a la versión de Jira (T-19); nunca el del LLM.
- `affected` y `regression_notes`: los propone el LLM con un prompt pequeño que solo recibe la
  HU, los cambios y un resumen de las HU candidatas (épica, vínculos, hermanas y relacionadas
  que reunió T-18), para respetar el presupuesto de tokens (PA-07).
- Solo se aceptan HU afectadas que estaban entre las candidatas (RNF-14): se reintenta una vez y
  las referencias que sigan sin ser válidas se descartan y se anotan.
"""

import json
import unicodedata
from collections.abc import Callable

from adapters.base import IssueDetail, LLMProvider, Message, TaskType
from core.functional.context import escape_data
from core.impact.diff import diff_stories
from core.rag.prompts import Prompt, load_prompt
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.user_story import UserStory

PromptLoader = Callable[[str], Prompt]
MAX_CANDIDATES = 12
SUMMARY_CHARS = 300


def _relation(issue: IssueDetail, parent_key: str | None) -> str:
    if parent_key and issue.key == parent_key:
        return "épica"
    if issue.parent_key and issue.parent_key == parent_key:
        return "hermana"
    return "relacionada"


def candidates(
    jira: list[IssueDetail],
    origin_key: str | None,
    limit: int = MAX_CANDIDATES,
    parent_key: str | None = None,
) -> list[IssueDetail]:
    """HU que pueden verse afectadas: el contexto de Jira salvo la propia HU y su épica."""
    excluded = {origin_key, parent_key}
    seen: set[str] = set()
    found = []
    for issue in jira:
        if issue.key not in excluded and issue.key not in seen:
            seen.add(issue.key)
            found.append(issue)
    return found[:limit]


def render_request(
    story: UserStory,
    diffs: list[StoryDiff],
    pool: list[IssueDetail],
    origin: IssueDetail | None,
    parent_key: str | None = None,
) -> str:
    """Mensaje de usuario con la HU, los cambios y las candidatas como datos delimitados."""
    parent_key = parent_key or (origin.parent_key if origin else None)
    rules = "\n".join(f"- {r.id}: {escape_data(r.description)}" for r in story.business_rules)
    criteria = "\n".join(f"- {c.id}: {escape_data(c.title)}" for c in story.acceptance_criteria)
    parts = [
        f'<hu titulo="{escape_data(story.title)}">\nReglas:\n{rules or "- (ninguna)"}\n'
        f"Criterios:\n{criteria or '- (ninguno)'}\n</hu>"
    ]
    if diffs:
        changes = json.dumps([d.model_dump() for d in diffs], ensure_ascii=False)
        parts.append(f"<cambios>\n{escape_data(changes)}\n</cambios>")
    blocks = []
    for issue in pool:
        summary = " ".join(issue.description_text.split())[:SUMMARY_CHARS]
        relation = _relation(issue, parent_key)
        blocks.append(
            f'<candidata clave="{escape_data(issue.key)}" relacion="{relation}">\n'
            f"{escape_data(issue.summary)}\n{escape_data(summary)}\n</candidata>"
        )
    parts.append("<candidatas>\n" + "\n".join(blocks) + "\n</candidatas>")
    return "\n\n".join(parts)


class ImpactAnalyzer:
    def __init__(self, llm: LLMProvider, *, prompt_loader: PromptLoader = load_prompt) -> None:
        self._llm = llm
        self._load = prompt_loader

    def analyze(
        self,
        story: UserStory,
        jira: list[IssueDetail],
        *,
        baseline: UserStory | None = None,
        origin_key: str | None = None,
        parent_key: str | None = None,
    ) -> ImpactAnalysis:
        """`parent_key`: épica de la HU (la de origen si es una HU nueva desde una épica)."""
        diffs = diff_stories(baseline, story) if baseline is not None else []
        origin = next((i for i in jira if i.key == origin_key), None)
        parent_key = parent_key or (origin.parent_key if origin else None)
        pool = candidates(jira, origin_key, parent_key=parent_key)
        # Sin cambios en una evolución, o sin candidatas, no hay nada que analizar: sin llamada.
        if (baseline is not None and not diffs) or not pool:
            return ImpactAnalysis(diffs=diffs, affected=[], regression_notes=[])

        allowed = {issue.key for issue in pool}
        prompt = self._load("analyze_impact")
        messages = [
            Message(role="system", content=prompt.text),
            Message(role="user", content=render_request(story, diffs, pool, origin, parent_key)),
        ]
        proposal = self._llm.generate_structured(
            messages, ImpactAnalysis, TaskType.ANALYZE_IMPACT
        ).content
        invalid = _invalid(proposal.affected, allowed)
        if invalid:
            retry = Message(
                role="user",
                content=(
                    "Estas claves no están entre las candidatas: "
                    + ", ".join(escape_data(k[:40]) for k in invalid)
                    + ". Usa solo: "
                    + ", ".join(escape_data(k) for k in sorted(allowed))
                    + ". Devuelve el análisis corregido."
                ),
            )
            valid_only = proposal.model_copy(
                update={"affected": [i for i in proposal.affected if i.jira_key in allowed]}
            )
            answer = Message(role="assistant", content=valid_only.model_dump_json())
            proposal = self._llm.generate_structured(
                [*messages, answer, retry], ImpactAnalysis, TaskType.ANALYZE_IMPACT
            ).content

        valid, dropped, blank = _keep_valid(proposal.affected, allowed)
        notes = [note.strip() for note in proposal.regression_notes if note.strip()]
        if dropped:
            notes.append(
                f"Se descartaron {dropped} referencias a HU que no estaban en el contexto."
            )
        if blank:  # PA-182: una HU afectada sin motivo no llega al comentario del vínculo
            notes.append(f"Se descartaron {blank} HU afectadas sin motivo.")
        return ImpactAnalysis(diffs=diffs, affected=valid, regression_notes=notes)


def _invalid(items: list[ImpactItem], allowed: set[str]) -> list[str]:
    return sorted({item.jira_key for item in items if item.jira_key not in allowed})


def _keep_valid(items: list[ImpactItem], allowed: set[str]) -> tuple[list[ImpactItem], int, int]:
    """HU afectadas válidas, sin repetir (clave, tipo) y con el motivo limpio; cuántas se
    descartaron por no ser candidatas y cuántas por no tener motivo (PA-182)."""
    valid: list[ImpactItem] = []
    seen: set[tuple[str, str]] = set()
    dropped = blank = 0
    for item in items:
        if item.jira_key not in allowed:
            dropped += 1
            continue
        reason = item.reason.strip()
        # Un motivo hecho solo de caracteres invisibles (U+200B, U+FEFF…) también está vacío.
        if not "".join(ch for ch in reason if unicodedata.category(ch) != "Cf").strip():
            blank += 1
            continue
        key = (item.jira_key, item.kind)
        if key not in seen:
            seen.add(key)
            valid.append(item.model_copy(update={"reason": reason}))
    return valid, dropped, blank
