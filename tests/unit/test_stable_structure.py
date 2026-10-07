"""PA-432 · La misma HU de Jira se estructura igual cada vez.

Cubre los tres cambios de la ronda 15:

1. Temperatura 0 y semilla fija solo en la llamada `structure_story` (`deterministic()`,
   `FallbackLLMProvider(call_options=)`, `OpenAICompatibleProvider.with_options`).
2. CA y RN literales de la HU de Jira (`literal_criteria`) en lugar de los del modelo.
3. Estructura compartida entre conversaciones por clave y huella del contenido.

Sin red: el cliente de OpenAI va sobre `httpx.MockTransport` y el resto usa los fakes de
`tests/fakes/`. Todos los textos de HU son ficticios (Biblioteca Municipal de Villaficticia).
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

import core.graph.nodes as nodes
from adapters.base import IssueDetail, LLMResult, Message, StructuredResult, TaskType
from adapters.jira.adf import adf_to_text
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.openai_compatible import OpenAICompatibleProvider
from core.artifact_state import InMemoryArtifactStateStore, structure_cache_id
from core.config import AppConfig, Settings, load_models_config
from core.container import Container
from core.factories import build_llm_provider
from core.functional.context import StoryContext
from core.functional.determinism import DETERMINISTIC, current_call_options, deterministic
from core.functional.literal_criteria import literal_criteria
from core.functional.writer import StoryWriter
from core.graph import Origin, build_graph, initial_state
from core.qa.writer import TestWriter
from core.rag.prompts import Prompt, load_prompt
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_llm_openai_compatible import (
    TEST_PROMPTS,
    VALID_ANSWER,
    Answer,
    FakeServer,
    make_client,
)
from tests.unit.test_llm_openai_compatible import completion as oa_completion

STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}
NEED_ORIGIN: Origin = {
    "kind": "need",
    "project": "DEMO",
    "text": "Avisar a la persona socia tres días antes del vencimiento (necesidad ficticia).",
}
MESSAGES = [Message(role="user", content="Resume una HU ficticia de Villaficticia.")]
TEST_MODELS = Path(__file__).resolve().parents[1] / "fixtures" / "models.yaml"

# --- Textos de HU ficticios con el formato que llega desde ADF -------------------------------

AFQP16_TEXT = """## Historia de usuario

Como responsable de sala, quiero que el sistema suspenda de forma automática a la persona \
socia que devuelve un libro con retraso, para aplicar el reglamento de forma homogénea.

## Objetivo de negocio

Aplicar las sanciones sin cálculos manuales y reducir las reclamaciones.

## Criterios de aceptación

### CA-01 · Suspensión aplicada

```
Escenario: Suspensión aplicada
  Dado un préstamo devuelto con N días naturales de retraso
  Cuando la persona responsable de sala registra la devolución
  Entonces la persona socia queda suspendida N días
  Y AvisosVF le notifica la fecha de fin de la suspensión
```

### CA-02 · Bloqueo durante la suspensión

```
Escenario: Bloqueo durante la suspensión
  Dado una persona socia suspendida
  Cuando intenta reservar un libro o renovar un préstamo
  Entonces la operación se rechaza
  Y se muestra el aviso «Tu cuenta está suspendida» con la fecha de fin
```

### CA-03 · Devolución en plazo

```
Escenario: Devolución en plazo
  Dado un préstamo devuelto antes de su vencimiento o el mismo día
  Cuando se registra la devolución
  Entonces no se aplica ninguna suspensión
```

## Reglas de negocio

- RN-01: Un día de suspensión por cada día natural de retraso.
- RN-02: Durante la suspensión no se puede reservar ni renovar; sí devolver.
- RN-03: Los préstamos en curso mantienen su fecha de vencimiento.

## Dependencias

- HU-01 y HU-02: la suspensión bloquea la reserva y la renovación.
- AvisosVF: notificación de la suspensión."""

AFQP5_TEXT = """## Historia de usuario

Como persona socia quiero recibir un aviso cuando mi reserva esté lista para recogerla.

## Criterios de aceptación

- Se envía un aviso cuando el ejemplar está preparado en el mostrador.
- El aviso indica el plazo de recogida."""

EXPECTED_CRITERIA = [
    AcceptanceCriterion(
        id="CA-01",
        title="Suspensión aplicada",
        given=["un préstamo devuelto con N días naturales de retraso"],
        when=["la persona responsable de sala registra la devolución"],
        then=[
            "la persona socia queda suspendida N días",
            "AvisosVF le notifica la fecha de fin de la suspensión",
        ],
    ),
    AcceptanceCriterion(
        id="CA-02",
        title="Bloqueo durante la suspensión",
        given=["una persona socia suspendida"],
        when=["intenta reservar un libro o renovar un préstamo"],
        then=[
            "la operación se rechaza",
            "se muestra el aviso «Tu cuenta está suspendida» con la fecha de fin",
        ],
    ),
    AcceptanceCriterion(
        id="CA-03",
        title="Devolución en plazo",
        given=["un préstamo devuelto antes de su vencimiento o el mismo día"],
        when=["se registra la devolución"],
        then=["no se aplica ninguna suspensión"],
    ),
]
EXPECTED_RULES = [
    BusinessRule(id="RN-01", description="Un día de suspensión por cada día natural de retraso."),
    BusinessRule(
        id="RN-02",
        description="Durante la suspensión no se puede reservar ni renovar; sí devolver.",
    ),
    BusinessRule(
        id="RN-03", description="Los préstamos en curso mantienen su fecha de vencimiento."
    ),
]


def formatted(criteria: str, rules: str = "- RN-01: Regla ficticia.") -> str:
    """HU mínima con las dos secciones; `criteria` y `rules` son su contenido literal."""
    return (
        "## Historia de usuario\n\nComo persona socia quiero algo ficticio.\n\n"
        f"## Criterios de aceptación\n\n{criteria}\n\n## Reglas de negocio\n\n{rules}\n"
    )


def block(*steps: str, title: str = "Escenario ficticio") -> str:
    body = "\n".join(f"  {s}" for s in steps)
    return f"```\nEscenario: {title}\n{body}\n```"


VALID_CA = "### CA-01 · Escenario ficticio\n\n" + block(
    "Dado un dato ficticio", "Cuando ocurre algo ficticio", "Entonces pasa lo esperado"
)


# --- 1. deterministic() y current_call_options() --------------------------------------------


def test_call_options_are_empty_outside_deterministic() -> None:
    """PA-432 (1): fuera de `deterministic()` no hay ajustes de muestreo."""
    assert current_call_options() == {}


def test_deterministic_sets_temperature_zero_and_seed_inside_block() -> None:
    """PA-432 (1): dentro del bloque, temperatura 0 y semilla 0; al salir, vacío otra vez."""
    with deterministic():
        assert current_call_options() == {"temperature": 0, "seed": 0}
    assert current_call_options() == {}


def test_deterministic_resets_options_when_block_raises() -> None:
    """PA-432 (1, error): una excepción dentro del bloque no deja los ajustes puestos."""
    with pytest.raises(RuntimeError), deterministic():
        raise RuntimeError("fallo ficticio")
    assert current_call_options() == {}


def test_current_call_options_returns_a_copy_when_mutated() -> None:
    """PA-432 (1, límite): modificar lo devuelto no cambia los ajustes compartidos."""
    with deterministic():
        options = current_call_options()
        options["temperature"] = 1
        assert current_call_options()["temperature"] == 0
    assert dict(DETERMINISTIC) == {"temperature": 0, "seed": 0}


# --- 1. OpenAICompatibleProvider.with_options ------------------------------------------------


def _openai(*replies: httpx.Response) -> tuple[OpenAICompatibleProvider, FakeServer]:
    server = FakeServer(list(replies))
    provider = OpenAICompatibleProvider(
        "proveedor-ficticio",
        "modelo-ficticio",
        make_client(server),
        prompts=TEST_PROMPTS,
        sleep=lambda _s: None,
    )
    return provider, server


def test_with_options_sends_temperature_and_seed_when_set() -> None:
    """PA-432 (1): la copia de `with_options` añade `temperature` y `seed` a la petición."""
    provider, server = _openai(oa_completion("hola"), oa_completion(VALID_ANSWER))

    clone = provider.with_options(temperature=0, seed=0)
    clone.generate(MESSAGES, TaskType.EVOLVE_STORY)
    clone.generate_structured(MESSAGES, Answer, TaskType.EVOLVE_STORY)

    for body in server.bodies():
        assert body["temperature"] == 0
        assert body["seed"] == 0


def test_with_options_does_not_modify_original_provider() -> None:
    """PA-432 (1): el proveedor original (cacheado por el router) sigue sin temperatura."""
    provider, server = _openai(oa_completion(VALID_ANSWER))

    clone = provider.with_options(temperature=0, seed=0)
    provider.generate_structured(MESSAGES, Answer, TaskType.EVOLVE_STORY)

    assert clone is not provider
    assert (clone.provider, clone.model) == (provider.provider, provider.model)
    (body,) = server.bodies()
    assert "temperature" not in body and "seed" not in body


def test_with_options_omits_values_when_none() -> None:
    """PA-432 (1, límite): sin valores, la copia no envía `temperature` ni `seed`."""
    provider, server = _openai(oa_completion("hola"))

    provider.with_options().generate(MESSAGES, TaskType.EVOLVE_STORY)

    (body,) = server.bodies()
    assert "temperature" not in body and "seed" not in body


def test_provider_without_options_sends_no_sampling_when_called() -> None:
    """PA-432 (1): sin `with_options`, la petición no lleva `temperature` ni `seed`."""
    provider, server = _openai(oa_completion("hola"))

    provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    (body,) = server.bodies()
    assert "temperature" not in body and "seed" not in body


# --- 1. FallbackLLMProvider(call_options=) ---------------------------------------------------


@dataclass
class OptionsSpy:
    """Proveedor falso con `with_options`: registra con qué ajustes se llamó cada copia."""

    inner: FakeLLMProvider = field(default_factory=FakeLLMProvider)
    options: dict[str, Any] = field(default_factory=dict)
    clones: list[dict[str, Any]] = field(default_factory=list)
    used: list[dict[str, Any]] = field(default_factory=list)
    provider: str = "espia"
    model: str = "modelo-espia"

    def with_options(self, **options: Any) -> "OptionsSpy":
        self.clones.append(options)
        return OptionsSpy(inner=self.inner, options=options, clones=self.clones, used=self.used)

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        self.used.append(dict(self.options))
        return self.inner.generate(messages, task)

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        self.used.append(dict(self.options))
        return self.inner.generate_structured(messages, schema, task)


def _fallback(provider: Any, call_options: Callable[[], Mapping[str, Any]] | None = None):
    return FallbackLLMProvider(lambda _task: [provider], call_options=call_options)


def test_fallback_applies_options_inside_deterministic() -> None:
    """PA-432 (1): dentro de `deterministic()` la cadena llama a la copia con temperatura 0."""
    spy = OptionsSpy()
    llm = _fallback(spy, current_call_options)

    with deterministic():
        llm.generate_structured(MESSAGES, UserStory, TaskType.EVOLVE_STORY)

    assert spy.clones == [{"temperature": 0, "seed": 0}]
    assert spy.used == [{"temperature": 0, "seed": 0}]
    assert spy.options == {}  # el original no cambia


def test_fallback_sends_no_options_outside_deterministic() -> None:
    """PA-432 (1): fuera del bloque no se crea ninguna copia ni se envían ajustes."""
    spy = OptionsSpy()
    llm = _fallback(spy, current_call_options)

    llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert spy.clones == []
    assert spy.used == [{}]


def test_fallback_without_call_options_sends_nothing() -> None:
    """PA-432 (1, límite): sin `call_options` el comportamiento es el de siempre."""
    spy = OptionsSpy()

    with deterministic():
        _fallback(spy).generate(MESSAGES, TaskType.EVOLVE_STORY)

    assert spy.clones == [] and spy.used == [{}]


def test_fallback_works_with_provider_without_with_options() -> None:
    """PA-432 (1): un proveedor sin `with_options` sigue funcionando con ajustes en curso."""
    fake = FakeLLMProvider()

    with deterministic():
        result = _fallback(fake, current_call_options).generate_structured(
            MESSAGES, UserStory, TaskType.EVOLVE_STORY
        )

    assert isinstance(result.content, UserStory)
    assert len(fake.calls) == 1


def test_fallback_keeps_calling_when_call_options_raises() -> None:
    """PA-432 (1, error): un `call_options` que lanza no rompe la llamada (sin ajustes)."""
    spy = OptionsSpy()

    def broken() -> Mapping[str, Any]:
        raise RuntimeError("ajustes ficticios rotos")

    result = _fallback(spy, broken).generate(MESSAGES, TaskType.EVOLVE_STORY)

    assert result.content
    assert spy.clones == [] and spy.used == [{}]


def test_fallback_end_to_end_reuses_cached_provider_without_leaking_options() -> None:
    """PA-432 (1): con el mismo proveedor real cacheado, solo la llamada determinista lleva
    `temperature`/`seed`; las siguientes no heredan los ajustes."""
    provider, server = _openai(oa_completion(VALID_ANSWER))
    llm = _fallback(provider, current_call_options)

    with deterministic():
        llm.generate_structured(MESSAGES, Answer, TaskType.EVOLVE_STORY)
    llm.generate_structured(MESSAGES, Answer, TaskType.EVOLVE_STORY)

    first, second = server.bodies()
    assert (first["temperature"], first["seed"]) == (0, 0)
    assert "temperature" not in second and "seed" not in second


def test_build_llm_provider_passes_current_call_options(clean_env: pytest.MonkeyPatch) -> None:
    """PA-432 (1): la composición (`core/factories`) conecta `current_call_options`."""
    config = AppConfig(Settings(_env_file=None), load_models_config(TEST_MODELS))
    spies: list[OptionsSpy] = []

    def factory(choice: Any) -> OptionsSpy:
        spies.append(OptionsSpy(provider=choice.provider, model=choice.model))
        return spies[-1]

    llm = build_llm_provider(config, provider_factory=factory)
    with deterministic():
        llm.generate(MESSAGES, TaskType.CLASSIFY_SOURCE)
    llm.generate(MESSAGES, TaskType.CLASSIFY_SOURCE)

    used = [u for spy in spies for u in spy.used]
    assert used == [{"temperature": 0, "seed": 0}, {}]


# --- 1. StoryWriter: solo la estructuración es determinista ----------------------------------


class RecordingLLM(FakeLLMProvider):
    """FakeLLMProvider que anota los ajustes de muestreo en curso de cada llamada."""

    def __init__(self) -> None:
        super().__init__()
        self.options_seen: list[dict[str, Any]] = []

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        self.options_seen.append(current_call_options())
        return super().generate_structured(messages, schema, task)


def _story_ctx(issue: IssueDetail | None = None, **kwargs: Any) -> StoryContext:
    issue = issue or dataset.STORIES["DEMO-3"]
    return StoryContext(origin_kind="story", origin_key=issue.key, jira=[issue], **kwargs)


def test_structure_runs_deterministic_and_other_tasks_do_not() -> None:
    """PA-432 (1): `structure` va con temperatura 0; generar, evolucionar y QA, no."""
    llm = RecordingLLM()
    writer = StoryWriter(llm)

    story = writer.structure(_story_ctx()).story
    writer.evolve(_story_ctx(previous=story))
    writer.generate(StoryContext(origin_kind="need", need="Necesidad ficticia."))
    TestWriter(llm).generate(story, _story_ctx())

    assert llm.options_seen[0] == {"temperature": 0, "seed": 0}
    assert all(seen == {} for seen in llm.options_seen[1:])
    assert len(llm.options_seen) == 4
    assert current_call_options() == {}


@dataclass
class SchemaServer:
    """Servidor OpenAI falso que responde según el esquema pedido con los builders del fake."""

    bodies: list[dict[str, Any]] = field(default_factory=list)
    builders: dict[type[BaseModel], Any] = field(default_factory=lambda: FakeLLMProvider().builders)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        name = (body.get("response_format") or {}).get("json_schema", {}).get("name")
        if name is None:
            return oa_completion("Respuesta ficticia.")
        schema = next(s for s in self.builders if s.__name__ == name)
        messages = [Message(role=m["role"], content=m["content"]) for m in body["messages"]]
        return oa_completion(self.builders[schema](messages).model_dump_json())

    def structure_bodies(self) -> list[dict[str, Any]]:
        return [b for b in self.bodies if STRUCTURE_MARK in b["messages"][0]["content"]]

    def other_bodies(self) -> list[dict[str, Any]]:
        return [b for b in self.bodies if STRUCTURE_MARK not in b["messages"][0]["content"]]


def _real_chain_container(tmp_path: Path) -> tuple[Container, SchemaServer]:
    server = SchemaServer()
    provider = OpenAICompatibleProvider(
        "proveedor-ficticio",
        "modelo-ficticio",
        make_client(server),
        prompts=TEST_PROMPTS,
        sleep=lambda _s: None,
    )
    llm = FallbackLLMProvider(lambda _task: [provider], call_options=current_call_options)
    return fake_container(tmp_path, llm=llm), server


@pytest.mark.parametrize(
    ("mode", "origin", "structured"),
    [("functional", STORY_ORIGIN, 1), ("qa", STORY_ORIGIN, 1), ("functional", NEED_ORIGIN, 0)],
    ids=["evolucion", "qa", "hu_nueva"],
)
def test_graph_sends_temperature_only_on_structure_call(
    tmp_path: Path, mode: str, origin: Origin, structured: int
) -> None:
    """PA-432 (1) de punta a punta: grafo + FallbackLLMProvider + OpenAICompatibleProvider;
    solo `chat.completions.create` de `structure_story` lleva `temperature=0` y `seed=0`."""
    container, server = _real_chain_container(tmp_path)
    graph = build_graph(container)

    graph.invoke(
        initial_state("qa-demo" if mode == "qa" else "af-demo", mode, origin),  # type: ignore[arg-type]
        {"configurable": {"thread_id": f"hilo-pa432-{mode}-{structured}"}},
    )

    assert len(server.structure_bodies()) == structured
    for body in server.structure_bodies():
        assert (body["temperature"], body["seed"]) == (0, 0)
    assert server.other_bodies(), "debería haber al menos otra llamada (evolución, QA o HU)"
    for body in server.other_bodies():
        assert "temperature" not in body and "seed" not in body


# --- 2. literal_criteria ---------------------------------------------------------------------


def test_literal_criteria_reads_afqp16_exactly() -> None:
    """PA-432 (2): AFQP-16 da 3 CA y 3 RN exactos; las «Y» se añaden al paso anterior."""
    result = literal_criteria(AFQP16_TEXT)

    assert result is not None
    criteria, rules = result
    assert criteria == EXPECTED_CRITERIA
    assert rules == EXPECTED_RULES


def _adf_text(value: str, *, strong: bool = False) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": value}
    if strong:
        node["marks"] = [{"type": "strong"}]
    return node


def _afqp16_adf() -> dict[str, Any]:
    """AFQP-16 como documento ADF ficticio (lo que devuelve Jira Cloud)."""

    def heading(level: int, text: str) -> dict[str, Any]:
        return {"type": "heading", "attrs": {"level": level}, "content": [_adf_text(text)]}

    def code(text: str) -> dict[str, Any]:
        return {"type": "codeBlock", "content": [_adf_text(text)]}

    def bullets(*items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": item}]}
                for item in items
            ],
        }

    content: list[dict[str, Any]] = [
        heading(2, "Historia de usuario"),
        {"type": "paragraph", "content": [_adf_text("Como responsable de sala, quiero algo.")]},
        heading(2, "Criterios de aceptación"),
    ]
    for criterion in EXPECTED_CRITERIA:
        steps = [f"  Dado {criterion.given[0]}", f"  Cuando {criterion.when[0]}"]
        steps.append(f"  Entonces {criterion.then[0]}")
        steps.extend(f"  Y {extra}" for extra in criterion.then[1:])
        content.append(heading(3, f"{criterion.id} · {criterion.title}"))
        content.append(code("\n".join([f"Escenario: {criterion.title}", *steps])))
    content.append(heading(2, "Reglas de negocio"))
    content.append(
        bullets(
            *[
                [_adf_text(rule.id, strong=True), _adf_text(f": {rule.description}")]
                for rule in EXPECTED_RULES
            ]
        )
    )
    content.append(heading(2, "Dependencias"))
    content.append(bullets([_adf_text("HU-01: la suspensión bloquea la reserva.")]))
    return {"type": "doc", "version": 1, "content": content}


def test_literal_criteria_reads_text_converted_from_adf() -> None:
    """PA-432 (2): el texto que produce `adf_to_text` desde ADF se lee igual."""
    result = literal_criteria(adf_to_text(_afqp16_adf()))

    assert result == (EXPECTED_CRITERIA, EXPECTED_RULES)


def test_literal_criteria_returns_none_for_afqp5_bullets() -> None:
    """PA-432 (2): AFQP-5 (criterios en viñetas sin numerar y sin RN) da `None`."""
    assert literal_criteria(AFQP5_TEXT) is None


def test_literal_criteria_accepts_crlf_line_endings() -> None:
    """PA-432 (2, límite): los saltos de línea de Windows no impiden la lectura."""
    assert literal_criteria(AFQP16_TEXT.replace("\n", "\r\n")) == (
        EXPECTED_CRITERIA,
        EXPECTED_RULES,
    )


def test_literal_criteria_accepts_several_steps_of_same_kind() -> None:
    """PA-432 (2, límite): varios «Dado» seguidos o «Y» tras «Dado» son válidos."""
    text = formatted(
        "### CA-01: Escenario ficticio\n\n"
        + block("Dado un dato", "Y otro dato", "Dado un tercero", "Cuando pasa", "Entonces sale")
    )

    result = literal_criteria(text)

    assert result is not None
    (criterion,), (rule,) = result
    assert criterion.given == ["un dato", "otro dato", "un tercero"]
    assert criterion.title == "Escenario ficticio"
    assert rule.id == "RN-01"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "## Historia de usuario\n\nAlgo ficticio.\n\n## Reglas de negocio\n\n- RN-01: X.",
            id="sin_seccion_de_criterios",
        ),
        pytest.param(
            "## Historia de usuario\n\nAlgo ficticio.\n\n## Criterios de aceptación\n\n" + VALID_CA,
            id="sin_seccion_de_reglas",
        ),
        pytest.param(formatted(""), id="seccion_de_criterios_vacia"),
        pytest.param(formatted("Texto suelto ficticio.\n\n" + VALID_CA), id="texto_suelto"),
        pytest.param(formatted(VALID_CA + "\n\nNota ficticia tras el bloque."), id="nota_al_final"),
        pytest.param(
            formatted("### CA-01 · Sin Dado\n\n" + block("Cuando pasa algo", "Entonces sale algo")),
            id="ca_sin_dado",
        ),
        pytest.param(
            formatted("### CA-01 · Sin Cuando\n\n" + block("Dado un dato", "Entonces sale algo")),
            id="ca_sin_cuando",
        ),
        pytest.param(
            formatted("### CA-01 · Sin Entonces\n\n" + block("Dado un dato", "Cuando pasa algo")),
            id="ca_sin_entonces",
        ),
        pytest.param(
            formatted("### CA-01 · Sin bloque\n\n" + VALID_CA.replace("CA-01", "CA-02")),
            id="ca_sin_bloque",
        ),
        pytest.param(
            formatted(
                "### CA-01 · Orden\n\n" + block("Dado un dato", "Entonces sale", "Cuando pasa")
            ),
            id="orden_incorrecto",
        ),
        pytest.param(
            formatted(
                "### CA-01 · Vuelta\n\n"
                + block("Dado un dato", "Cuando pasa", "Entonces sale", "Dado otro")
            ),
            id="dado_tras_entonces",
        ),
        pytest.param(
            formatted(
                "### CA-01 · Y primero\n\n"
                + block("Y algo previo", "Dado un dato", "Cuando pasa", "Entonces sale")
            ),
            id="y_sin_paso_previo",
        ),
        pytest.param(
            formatted(
                "### CA-01 · Pero\n\n"
                + block("Dado un dato", "Cuando pasa", "Entonces sale", "Pero no siempre")
            ),
            id="paso_desconocido",
        ),
        pytest.param(
            formatted(VALID_CA.removesuffix("```")),
            id="bloque_sin_cerrar",
        ),
        pytest.param(
            formatted(block("Dado un dato", "Cuando pasa", "Entonces sale") + "\n\n" + VALID_CA),
            id="bloque_sin_titulo",
        ),
        pytest.param(formatted(VALID_CA + "\n\n" + VALID_CA), id="ca_repetido"),
        pytest.param(
            formatted(VALID_CA, "- RN-01: Una regla.\n- RN-01: Otra regla."),
            id="rn_repetida",
        ),
        pytest.param(formatted(VALID_CA, "- Regla sin identificador."), id="rn_sin_id"),
        pytest.param(formatted(VALID_CA, "Texto suelto de reglas."), id="rn_texto_suelto"),
        pytest.param(
            formatted(VALID_CA) + "\n## Criterios de aceptación\n\n" + VALID_CA,
            id="seccion_repetida",
        ),
        pytest.param(
            formatted("### CA-1 Sin separador\n\n" + block("Dado a", "Cuando b", "Entonces c")),
            id="titulo_sin_separador",
        ),
    ],
)
def test_literal_criteria_returns_none_when_not_safe(text: str) -> None:
    """PA-432 (2, negativas): si algo no se lee completo y sin ambigüedad, `None`."""
    assert literal_criteria(text) is None


def test_literal_criteria_returns_none_when_criterion_has_two_blocks() -> None:
    """PA-432 (2, negativa): dos escenarios bajo un mismo `### CA-NN` son ambiguos → `None`."""
    text = formatted(
        VALID_CA + "\n\n" + block("Y otra consecuencia ficticia", title="Segundo escenario")
    )

    assert literal_criteria(text) is None


def test_literal_criteria_returns_none_for_empty_text() -> None:
    """PA-432 (2, límite): texto vacío o sin secciones da `None`."""
    assert literal_criteria("") is None
    assert literal_criteria("Como persona socia quiero algo ficticio.") is None


# --- 2. StoryWriter.structure con CA y RN literales ------------------------------------------


def _afqp_issue(key: str, text: str) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary="[HU-12] Suspensión por retraso (ficticia)",
        issue_type="Story",
        status="Por hacer",
        description_text=text,
    )


def test_structure_uses_literal_criteria_when_issue_has_format() -> None:
    """PA-432 (2): con formato, los CA y RN son los literales aunque el modelo devuelva otros."""
    llm = FakeLLMProvider()
    issue = _afqp_issue("AFQP-16", AFQP16_TEXT)

    story = StoryWriter(llm).structure(_story_ctx(issue)).story

    model = dataset.renewal_story()
    assert [c.id for c in model.acceptance_criteria] != [c.id for c in EXPECTED_CRITERIA]
    assert story.acceptance_criteria == EXPECTED_CRITERIA
    assert story.business_rules == EXPECTED_RULES
    assert story.jira_key == "AFQP-16"
    assert story.changes_from_previous == []
    assert story.title == model.title  # el resto de campos sigue siendo del modelo


@pytest.mark.parametrize(
    "text",
    [AFQP5_TEXT, AFQP16_TEXT.split("## Reglas de negocio")[0]],
    ids=["sin_formato", "ca_con_formato_sin_rn"],
)
def test_structure_keeps_all_model_criteria_when_issue_has_no_format(text: str) -> None:
    """PA-432 (2): sin formato completo, todos los CA y RN son del modelo (sin mezclar)."""
    llm = FakeLLMProvider()

    story = StoryWriter(llm).structure(_story_ctx(_afqp_issue("AFQP-5", text))).story

    model = dataset.renewal_story()
    assert story.acceptance_criteria == model.acceptance_criteria
    assert story.business_rules == model.business_rules


# --- 3. Estructura compartida entre conversaciones -------------------------------------------


def _structure_calls(llm: FakeLLMProvider) -> int:
    return sum(
        1
        for c in llm.calls
        if c["schema"] is UserStory and c["messages"] and STRUCTURE_MARK in c["messages"][0].content
    )


def _run(container: Container, mode: str, thread: str, origin: Origin = STORY_ORIGIN) -> Any:
    graph = build_graph(container)
    config = {"configurable": {"thread_id": thread}}
    user = "qa-demo" if mode == "qa" else "af-demo"
    graph.invoke(initial_state(user, mode, origin), config)  # type: ignore[arg-type]
    return graph.get_state(config).values["artifact"]


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _store(container: Container) -> InMemoryArtifactStateStore:
    assert isinstance(container.state_store, InMemoryArtifactStateStore)
    return container.state_store


def _spy_shared_ids(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Anota cada id compartido que calcula `_baseline` (sin cambiar el resultado)."""
    ids: list[str | None] = []
    original = nodes._shared_baseline_id

    def spy(issue_key: str | None, origin_only: StoryContext) -> str | None:
        ids.append(original(issue_key, origin_only))
        return ids[-1]

    monkeypatch.setattr(nodes, "_shared_baseline_id", spy)
    return ids


def _baseline_of(container: Container, artifact: Any) -> dict[str, Any]:
    return _store(container).states[str(artifact.id)]["baseline"]


@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_two_conversations_reuse_shared_structure_when_story_unchanged(
    tmp_path: Path, mode: str
) -> None:
    """PA-432 (3): dos conversaciones sobre la misma HU sin cambios estructuran una sola vez y
    parten de la misma versión."""
    container = fake_container(tmp_path)

    first = _run(container, mode, f"hilo-pa432-{mode}-a")
    second = _run(container, mode, f"hilo-pa432-{mode}-b")

    assert _structure_calls(_llm(container)) == 1
    assert first is not None and second is not None and first.id != second.id
    assert _baseline_of(container, first) == _baseline_of(container, second)


def test_qa_reuses_structure_shared_by_functional_conversation(tmp_path: Path) -> None:
    """PA-432 (3): la estructura es de la HU, no del modo: QA reutiliza la de una evolución."""
    container = fake_container(tmp_path)

    _run(container, "functional", "hilo-pa432-cruce-af")
    _run(container, "qa", "hilo-pa432-cruce-qa")

    assert _structure_calls(_llm(container)) == 1


@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_changed_story_in_jira_is_structured_again(tmp_path: Path, mode: str) -> None:
    """PA-432 (3) · PA-339: si la HU cambia en Jira, la otra conversación vuelve a estructurar."""
    container = fake_container(tmp_path)
    _run(container, mode, f"hilo-pa432-cambio-{mode}-a")

    issue = _tracker(container).issues["DEMO-3"]
    issue.description_text += " Además, se avisa por correo (cambio ficticio)."
    _run(container, mode, f"hilo-pa432-cambio-{mode}-b")

    assert _structure_calls(_llm(container)) == 2


def test_changed_structure_prompt_version_is_structured_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-432 (3): otra versión del prompt `structure_story` da otra entrada compartida."""
    container = fake_container(tmp_path)
    _run(container, "functional", "hilo-pa432-prompt-a")

    real = load_prompt

    def bumped(name: str) -> Prompt:
        prompt = real(name)
        if name != "structure_story":
            return prompt
        return Prompt(name=prompt.name, version=f"{prompt.version}-ficticia", text=prompt.text)

    monkeypatch.setattr(nodes, "load_prompt", bumped)
    _run(container, "functional", "hilo-pa432-prompt-b")

    assert _structure_calls(_llm(container)) == 2


def test_other_key_with_same_content_does_not_reuse_structure(tmp_path: Path) -> None:
    """PA-432 (3): otra clave con el mismo contenido no usa la estructura de DEMO-3."""
    container = fake_container(tmp_path)
    tracker = _tracker(container)
    tracker.issues["DEMO-5"] = tracker.issues["DEMO-3"].model_copy(update={"key": "DEMO-5"})

    _run(container, "functional", "hilo-pa432-clave-a")
    other = _run(container, "functional", "hilo-pa432-clave-b", {"kind": "story", "key": "DEMO-5"})

    assert _structure_calls(_llm(container)) == 2
    assert _baseline_of(container, other)["jira_key"] == "DEMO-5"


def test_shared_id_depends_on_key_and_fingerprint() -> None:
    """PA-432 (3): el id compartido cambia con la clave (también de otro proyecto) y la huella."""
    base = structure_cache_id("DEMO-3", "huella-ficticia")

    assert base == structure_cache_id("DEMO-3", "huella-ficticia")
    assert base != structure_cache_id("DEMO-4", "huella-ficticia")
    assert base != structure_cache_id("OTRO-3", "huella-ficticia")
    assert base != structure_cache_id("DEMO-3", "otra-huella-ficticia")


def test_shared_id_is_none_without_issue_key() -> None:
    """PA-432 (3, límite): sin clave de origen no hay entrada compartida."""
    assert nodes._shared_baseline_id(None, StoryContext(origin_kind="story")) is None
    assert nodes._shared_baseline_id("", StoryContext(origin_kind="story")) is None


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda s: {**s, "issue_key": "OTRO-3"}, id="otro_issue_key"),
        pytest.param(
            lambda s: {**s, "baseline": {**s["baseline"], "jira_key": "OTRO-3"}},
            id="otro_jira_key",
        ),
        pytest.param(lambda s: {**s, "baseline": {"title": 1}}, id="baseline_no_valida"),
        pytest.param(lambda s: {**s, "baseline": "texto ficticio"}, id="baseline_no_es_objeto"),
        pytest.param(lambda s: {**s, "baseline": None}, id="baseline_vacia"),
        pytest.param(lambda s: {"issue_key": s["issue_key"]}, id="sin_baseline"),
    ],
)
def test_tampered_shared_entry_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: Callable[[dict], dict]
) -> None:
    """PA-432 (3): una entrada compartida que no cuadra (clave, `jira_key`) o dañada se ignora
    y se estructura de nuevo; la generación termina igualmente."""
    ids = _spy_shared_ids(monkeypatch)
    container = fake_container(tmp_path)
    _run(container, "functional", "hilo-pa432-dano-a")
    shared = ids[0]
    assert shared is not None
    store = _store(container)
    store.states[shared] = tamper(store.states[shared])

    artifact = _run(container, "functional", "hilo-pa432-dano-b")

    assert _structure_calls(_llm(container)) == 2
    assert artifact is not None
    assert _baseline_of(container, artifact)["jira_key"] == "DEMO-3"


class FailingSharedStore(InMemoryArtifactStateStore):
    """Almacén que falla al leer o guardar las entradas compartidas de estructura."""

    def __init__(self, *, fail_load: bool, fail_save: bool) -> None:
        super().__init__()
        self.shared: set[str] = set()
        self.fail_load = fail_load
        self.fail_save = fail_save

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        if self.fail_load and artifact_id in self.shared:
            raise RuntimeError("almacén ficticio caído al leer")
        return super().load(artifact_id)

    def save(self, artifact_id: str, state: dict[str, Any]) -> None:
        if self.fail_save and artifact_id in self.shared:
            raise RuntimeError("almacén ficticio caído al guardar")
        super().save(artifact_id, state)


@pytest.mark.parametrize(
    ("fail_load", "fail_save"),
    [(True, False), (False, True), (True, True)],
    ids=["falla_al_leer", "falla_al_guardar", "falla_siempre"],
)
def test_failing_store_for_shared_entry_does_not_break_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_load: bool, fail_save: bool
) -> None:
    """PA-432 (3, error): si el almacén falla con la entrada compartida, se estructura como
    antes y la conversación termina con su versión de partida."""
    store = FailingSharedStore(fail_load=fail_load, fail_save=fail_save)
    original = nodes._shared_baseline_id

    def register(issue_key: str | None, origin_only: StoryContext) -> str | None:
        shared = original(issue_key, origin_only)
        if shared is not None:
            store.shared.add(shared)
        return shared

    monkeypatch.setattr(nodes, "_shared_baseline_id", register)
    container = fake_container(tmp_path, state_store=store)

    first = _run(container, "functional", "hilo-pa432-falla-a")
    second = _run(container, "functional", "hilo-pa432-falla-b")

    assert first is not None and second is not None
    assert _structure_calls(_llm(container)) == 2
    assert _baseline_of(container, second)["jira_key"] == "DEMO-3"
    if fail_save:
        assert not store.shared & store.states.keys()


def test_literal_criteria_returns_none_when_rules_section_is_empty() -> None:
    """PA-432: `## Reglas de negocio` sin reglas no se lee con seguridad → se queda el modelo."""
    text = (
        "## Criterios de aceptación\n\n"
        "### CA-01 · Reserva ficticia\n\n"
        "```\nEscenario: Reserva ficticia\n  Dado una persona socia ficticia\n"
        "  Cuando pulsa «Reservar»\n  Entonces la reserva queda activa\n```\n\n"
        "## Reglas de negocio\n\n"
        "## Dependencias\n\n- Ninguna.\n"
    )
    assert literal_criteria(text) is None


@pytest.mark.parametrize(
    "line",
    [
        "## " + " " * 50_000 + "x",
        "### CA-01 · " + " " * 50_000 + "x",
        "- RN-01: " + " " * 50_000 + "x",
        "Dado " + " " * 50_000 + "x",
    ],
    ids=["seccion", "criterio", "regla", "paso"],
)
def test_literal_criteria_is_fast_with_long_runs_of_spaces(line: str) -> None:
    """PA-432 (security-reviewer): sin retroceso cuadrático con texto de Jira no confiable."""
    import time

    text = "## Criterios de aceptación\n\n" + line + "\n\n## Reglas de negocio\n\n- RN-01: x\n"
    started = time.perf_counter()
    literal_criteria(text)
    assert time.perf_counter() - started < 0.5
