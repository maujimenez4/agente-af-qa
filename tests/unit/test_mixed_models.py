"""Ronda 16 · PA-442 (la HU de origen, siempre entera) y PA-443 (modelos mixtos).

Cubre:

1. PA-442 · `apply_budget` y todos los caminos que reúnen el contexto (estructurar, generar y
   evolucionar una HU, QA, revisión de calidad y panel de fuentes): la HU de origen larga llega
   entera al prompt; si no cabe en la ventana, `ContextOverflowError` («no cabe») sin llamar al
   LLM. Las fuentes opcionales sí se recortan o descartan.
2. PA-442 · la huella compartida de PA-432 sale del origen sin recortar
   (`STRUCTURE_CACHE_VERSION = 2`) y una entrada de la versión 1 no se reutiliza.
3. PA-443 · `ProviderLimits`, `ModelsConfig.limits_for`/`context_budget_for`/`task_providers`,
   `PromptLimits.from_config(config, providers_for)`, `providers_of`, el presupuesto por tarea
   de `build_context_service` y la tarea de cada nodo (`_generation_task`), con las tres
   configuraciones versionadas (`config/models.yaml`, `models.todo-local.yaml` y
   `models.groq.yaml`).
4. PA-443 · selector de modelo (RF-42): con `ModelRouter.set_override`, los límites, el
   presupuesto y los topes/esperas salen del proveedor del modelo elegido.
5. PA-443 · el 429 con `Retry-After` espera hasta `max_wait_s`; el 413 lanza
   `PromptTooLargeError` sin reintentar y pasa al respaldo con el motivo `no_cabe`; el código
   HTTP llega a `llm_provider_failed` y nunca el cuerpo.

Sin red: el cliente de OpenAI va sobre `httpx.MockTransport` (servidor falso de
`test_llm_openai_compatible.py`) y el resto usa los fakes de `tests/fakes/`. Nunca se lee `.env`
(`Settings(_env_file=None)`); la clave de Groq es un valor claramente ficticio. Datos 100 %
ficticios (Villaficticia, claves DEMO-N).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

import core.graph.nodes as nodes
from adapters.base import Chunk, IssueDetail, LLMProvider, Message, RetrievedChunk, TaskType
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError
from adapters.llm.fallback import FallbackEvent, FallbackLLMProvider, capture_fallbacks
from adapters.llm.openai_compatible import (
    OpenAICompatibleProvider,
    PromptTooLargeError,
    ProviderTimeoutError,
    http_status,
    with_http_status,
)
from adapters.llm.router import ModelChoice, ModelRouter
from api.cancel import CancellableLLM
from core.artifact_state import InMemoryArtifactStateStore
from core.config import (
    DEFAULT_MODELS_PATH,
    AppConfig,
    ConfigError,
    LimitsConfig,
    ModelsConfig,
    ProviderLimits,
    Settings,
    load_models_config,
)
from core.container import Container
from core.context.budget import (
    SAFETY_TOKENS,
    TRUNCATION_MARK,
    ContextOverflowError,
    PromptLimits,
    apply_budget,
    fit_messages,
    issue_tokens,
    providers_of,
    truncate_issue,
)
from core.context.service import DEFAULT_TOKEN_BUDGET, build_context_service
from core.factories import _openai_factory, build_llm_provider, model_router
from core.functional.context import StoryContext
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import GraphNodes
from core.guided_start import GuidedStart
from core.quality import QualityReviewer
from schemas.common import SourceRef
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_llm_openai_compatible import (
    BODY_MARKER,
    MESSAGES,
    TEST_PROMPTS,
    FakeServer,
    Reply,
    completion,
    error_response,
    make_client,
)

CONFIG_DIR = DEFAULT_MODELS_PATH.parent
MIXED = DEFAULT_MODELS_PATH  # config/models.yaml
TODO_LOCAL = CONFIG_DIR / "models.todo-local.yaml"
GROQ_FILE = CONFIG_DIR / "models.groq.yaml"
ALL_FILES = [MIXED, TODO_LOCAL, GROQ_FILE]
ALL_IDS = ["mixta", "todo-local", "groq"]

FAKE_GROQ = "gsk-ficticia-0000-no-es-una-clave-real"  # claramente ficticia
GPT_120B = "openai/gpt-oss-120b"
GPT_20B = "openai/gpt-oss-20b"
QWEN = "qwen3:1.7b"
PHI = "phi4-mini"
STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md

GROQ_TASKS_120B = (TaskType.GENERATE_STORY, TaskType.EVOLVE_STORY, TaskType.REVIEW_STORY)
GROQ_TASKS_20B = (
    TaskType.ANALYZE_IMPACT,
    TaskType.SYNTHESIZE_MEMORY,
    TaskType.CLASSIFY_SOURCE,
    TaskType.NL_TO_JQL,
)
GROQ_TASKS = GROQ_TASKS_120B + GROQ_TASKS_20B

# Ventana local (10 240) − tope de salida de las HU y la suite (2500) − margen.
LOCAL_ROOM_2500 = 10_240 - 2500 - SAFETY_TOKENS

FILLER = "Descripción ficticia de la renovación de préstamos de la Biblioteca de Villaficticia. "
END_MARK = "FIN-DEL-ORIGEN-PA442"
STORY: Origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
EPIC: Origin = {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}
AF = dataset.DEMO_USERS["af-demo"][1]


# --- utilidades ----------------------------------------------------------------------------


def _settings(*, groq: bool) -> Settings:
    if groq:
        return Settings(_env_file=None, groq_api_key=SecretStr(FAKE_GROQ))  # type: ignore[call-arg]
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _config(
    path: Path = MIXED, *, groq: bool = True, models: ModelsConfig | None = None
) -> AppConfig:
    return AppConfig(_settings(groq=groq), models or load_models_config(path))


def _description(tokens: int) -> str:
    """Descripción de unos `tokens` tokens estimados que termina en una marca reconocible."""
    text = FILLER * (tokens * 3 // len(FILLER) + 1)
    return text + END_MARK


def _lengthen(container: Container, key: str, tokens: int) -> IssueDetail:
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    issue = tracker.issues.get(key)
    if issue is None:  # la épica del dataset
        assert key == dataset.EPIC.key
        issue = dataset.EPIC
    longer = issue.model_copy(update={"description_text": _description(tokens)})
    tracker.issues[key] = longer
    return longer


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _texts(call: dict[str, Any]) -> str:
    return "\n".join(m.content for m in call["messages"])


def _run(container: Container, mode: str, origin: Origin, thread: str) -> Any:
    graph = build_graph(container)
    config = {"configurable": {"thread_id": thread}}
    user = "qa-demo" if mode == "qa" else "af-demo"
    graph.invoke(initial_state(user, mode, origin), config)  # type: ignore[arg-type]
    return graph.get_state(config).values["artifact"]


def _is_structure(call: dict[str, Any]) -> bool:
    return (
        call["schema"] is UserStory
        and bool(call["messages"])
        and STRUCTURE_MARK in call["messages"][0].content
    )


def _provider(
    *replies: Reply, name: str = "groq", model: str = GPT_120B, **kwargs: Any
) -> tuple[OpenAICompatibleProvider, FakeServer, list[float]]:
    """Proveedor real sobre un servidor falso (sin red) con un `sleep` que solo anota."""
    server = FakeServer(list(replies))
    sleeps: list[float] = []
    kwargs.setdefault("prompts", TEST_PROMPTS)
    provider = OpenAICompatibleProvider(
        name, model, make_client(server), sleep=sleeps.append, **kwargs
    )
    return provider, server, sleeps


def _chain(*providers: LLMProvider) -> Callable[[TaskType], Sequence[LLMProvider]]:
    return lambda _task: list(providers)


def _failed_events(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in logs if e.get("event") == "llm_provider_failed"]


def _local_fallback() -> FakeLLMProvider:
    return FakeLLMProvider(provider="local", model=QWEN)


# --- 1 · PA-442: la HU de origen, siempre entera ------------------------------------------


def test_apply_budget_origin_larger_than_budget_enters_whole_and_optional_sources_do_not() -> None:
    """PA-442: el origen supera el presupuesto → entra entero; las incidencias opcionales y los
    fragmentos del RAG no entran (su coste cuenta)."""
    origin = IssueDetail(
        key="DEMO-3",
        summary="HU ficticia larga",
        issue_type="Story",
        status="Por hacer",
        description_text=_description(3000),
        comments=["comentario ficticio"],
    )
    other = dataset.STORIES["DEMO-2"]
    chunk = RetrievedChunk(
        chunk=Chunk(id="c1", document_id="doc-ficticio", ordinal=0, content="Norma ficticia."),
        score=0.9,
        source=SourceRef(kind="rag", ref="doc-ficticio"),
    )

    issues, chunks, report = apply_budget([origin, other], [chunk], 2000)

    assert issues == [origin]
    assert issues[0].description_text.endswith(END_MARK)
    assert chunks == []
    assert report.used == issue_tokens(origin) > 2000
    assert report.truncated_issues == 0
    assert (report.dropped_issues, report.dropped_chunks) == (1, 1)


@pytest.mark.parametrize(
    ("mode", "origin", "tokens", "budget_task"),
    [
        pytest.param("functional", STORY, 2600, TaskType.EVOLVE_STORY, id="evolucionar"),
        pytest.param("functional", EPIC, 2600, TaskType.GENERATE_STORY, id="generar"),
        pytest.param("qa", STORY, 3600, TaskType.GENERATE_TESTS, id="qa"),
    ],
)
def test_long_origin_reaches_every_prompt_whole_when_it_exceeds_the_budget(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
    mode: str,
    origin: Origin,
    tokens: int,
    budget_task: TaskType,
) -> None:
    """PA-442 · PA-443: con `config/models.yaml` (contexto 2000 para las HU en Groq y 3300 para
    QA en local), una HU de origen más larga que el presupuesto llega entera a cada llamada que
    la usa (estructurar, generar/evolucionar y la suite): con su final y sin marca de recorte."""
    config = _config(groq=False)
    container = fake_container(tmp_path, config=config)
    longer = _lengthen(container, str(origin["key"]), tokens)
    budget = config.models.context_budget_for(config.models.task_providers(budget_task))
    assert issue_tokens(longer) > budget

    artifact = _run(container, mode, origin, f"hilo-pa442-{mode}-{origin['kind']}")

    assert artifact is not None
    calls = _llm(container).calls
    users = [c for c in calls if c["task"] in (budget_task, TaskType.EVOLVE_STORY)]
    assert users, "la prueba necesita llamadas que usen el origen"
    for call in users:
        text = _texts(call)
        assert longer.description_text in text, call["task"]
        assert TRUNCATION_MARK not in text
    if origin["kind"] == "story":
        assert any(_is_structure(c) for c in calls)


@pytest.mark.parametrize(
    ("mode", "origin"),
    [
        pytest.param("functional", STORY, id="estructurar"),
        pytest.param("functional", EPIC, id="generar"),
        pytest.param("qa", STORY, id="qa"),
    ],
)
def test_origin_that_does_not_fit_the_window_raises_without_calling_llm(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, mode: str, origin: Origin
) -> None:
    """PA-442 (error): si la HU de origen ni sola cabe en la ventana (la más restrictiva de la
    cadena: la local, 10 240), `ContextOverflowError` («no cabe») sin llamar al LLM, en lugar de
    recortarla en silencio."""
    container = fake_container(tmp_path, config=_config(groq=False))
    _lengthen(container, str(origin["key"]), LOCAL_ROOM_2500 + 500)

    with pytest.raises(ContextOverflowError, match="no cabe"):
        _run(container, mode, origin, f"hilo-pa442-overflow-{mode}-{origin['kind']}")

    assert _llm(container).calls == []


def test_quality_review_sends_long_origin_whole(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-442: la revisión de calidad (`QualityReviewer`) estructura y revisa con la HU de
    origen entera aunque supere el presupuesto global (2000)."""
    config = _config(groq=False)
    container = fake_container(tmp_path, config=config)
    longer = _lengthen(container, "DEMO-3", 2600)
    assert issue_tokens(longer) > config.models.limits.context_token_budget

    QualityReviewer(container).review(AF, "DEMO-3")

    calls = _llm(container).calls
    assert {c["task"] for c in calls} >= {TaskType.EVOLVE_STORY, TaskType.REVIEW_STORY}
    for call in calls:
        assert longer.description_text in _texts(call), call["task"]
        assert TRUNCATION_MARK not in _texts(call)


def test_quality_review_origin_that_does_not_fit_raises_without_calling_llm(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-442 (error): en la revisión de calidad, un origen que no cabe da «no cabe» sin LLM."""
    container = fake_container(tmp_path, config=_config(groq=False))
    _lengthen(container, "DEMO-3", LOCAL_ROOM_2500 + 500)

    with pytest.raises(ContextOverflowError, match="no cabe"):
        QualityReviewer(container).review(AF, "DEMO-3")
    assert _llm(container).calls == []


def test_sources_panel_shows_long_origin_whole_and_trims_optional_sources(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-442: el panel de fuentes (`GuidedStart.preview_sources_with_budget`) cuenta la HU de
    origen entera; con ella por encima del presupuesto no entra ninguna fuente opcional."""
    container = fake_container(tmp_path, config=_config(groq=False))
    longer = _lengthen(container, "DEMO-3", 2600)

    rows, report = GuidedStart(container).preview_sources_with_budget(STORY)

    origin = next(r for r in rows if r.ref == "DEMO-3")
    assert origin.tokens == issue_tokens(longer) > report.budget
    assert [r.ref for r in rows] == ["DEMO-3"]
    assert report.truncated_issues == 0
    assert report.dropped_issues + report.dropped_chunks >= 1
    assert _llm(container).calls == []


def test_sources_panel_trims_long_related_issue_but_not_the_origin(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-442: una HU vinculada (opcional) larga sí se recorta; el origen queda intacto."""
    container = fake_container(tmp_path, config=_config(groq=False))
    related = _lengthen(container, "DEMO-2", 3000)
    origin_tokens = issue_tokens(dataset.STORIES["DEMO-3"])

    rows, report = GuidedStart(container).preview_sources_with_budget(STORY)

    by_ref = {r.ref: r for r in rows}
    assert by_ref["DEMO-3"].tokens == origin_tokens
    assert "DEMO-2" in by_ref
    assert 0 < (by_ref["DEMO-2"].tokens or 0) < issue_tokens(related)
    assert report.truncated_issues >= 1
    assert report.used <= report.budget


# --- 2 · PA-442: huella compartida sobre el origen sin recortar ---------------------------


def _spy_shared_ids(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str | None, StoryContext]]:
    seen: list[tuple[str | None, StoryContext]] = []
    original = nodes._shared_baseline_id

    def spy(issue_key: str | None, origin_only: StoryContext) -> str | None:
        shared = original(issue_key, origin_only)
        seen.append((shared, origin_only))
        return shared

    monkeypatch.setattr(nodes, "_shared_baseline_id", spy)
    return seen


@pytest.mark.parametrize("mode", ["functional", "qa"])
def test_shared_baseline_id_uses_the_untruncated_origin(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """PA-442 · PA-432: con un origen más largo que el presupuesto, la huella compartida es la
    de la incidencia sin recortar (no la de la versión recortada de antes)."""
    seen = _spy_shared_ids(monkeypatch)
    container = fake_container(tmp_path, config=_config(groq=False))
    longer = _lengthen(container, "DEMO-3", 3600)
    whole = StoryContext(origin_kind="story", origin_key="DEMO-3", jira=[longer])
    trimmed = StoryContext(
        origin_kind="story", origin_key="DEMO-3", jira=[truncate_issue(longer, 2000)]
    )

    _run(container, mode, STORY, f"hilo-pa442-huella-{mode}")

    assert seen, "no se calculó la huella compartida"
    shared, origin_only = seen[0]
    assert origin_only.jira == [longer]
    assert shared == nodes._shared_baseline_id("DEMO-3", whole)
    assert shared != nodes._shared_baseline_id("DEMO-3", trimmed)


def test_structure_cache_version_is_two() -> None:
    """PA-442: la versión de la estructura compartida sube a 2."""
    assert nodes.STRUCTURE_CACHE_VERSION == 2


def test_shared_entry_saved_with_version_one_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-442 (límite): una estructura compartida guardada con la versión 1 (pudo hacerse con el
    origen recortado) no se reutiliza: la HU se estructura de nuevo."""
    store = InMemoryArtifactStateStore()
    container = fake_container(tmp_path, state_store=store)
    issue = dataset.STORIES["DEMO-3"]
    origin_only = StoryContext(origin_kind="story", origin_key="DEMO-3", jira=[issue])
    with monkeypatch.context() as patch:
        patch.setattr(nodes, "STRUCTURE_CACHE_VERSION", 1)
        old_id = nodes._shared_baseline_id("DEMO-3", origin_only)
    assert old_id is not None
    assert old_id != nodes._shared_baseline_id("DEMO-3", origin_only)
    stale = dataset.renewal_story().model_copy(update={"title": "ESTRUCTURA-V1-FICTICIA"})
    store.save(old_id, {"issue_key": "DEMO-3", "baseline": stale.model_dump(mode="json")})

    artifact = _run(container, "functional", {"kind": "story", "key": "DEMO-3"}, "hilo-pa442-v1")

    assert sum(1 for c in _llm(container).calls if _is_structure(c)) == 1
    baseline = store.states[str(artifact.id)]["baseline"]
    assert baseline["title"] != "ESTRUCTURA-V1-FICTICIA"


# --- 3 · PA-443: configuración y límites por proveedor ------------------------------------


@pytest.mark.parametrize("path", ALL_FILES, ids=ALL_IDS)
def test_versioned_models_files_validate_with_every_task(path: Path) -> None:
    """PA-443: las tres configuraciones versionadas validan y asignan todas las tareas."""
    models = load_models_config(path)
    assert set(models.tasks) == set(TaskType)
    assert models.embeddings.model == "bge-m3"
    for task in TaskType:
        assert models.task_providers(task), task.value


@pytest.mark.parametrize("task", GROQ_TASKS, ids=[t.value for t in GROQ_TASKS])
def test_mixed_config_sends_groq_tasks_to_groq_with_local_fallback(task: TaskType) -> None:
    """PA-443: HU, evolución y calidad → gpt-oss-120b; impacto, memoria, clasificar y JQL →
    gpt-oss-20b; todas con respaldo local qwen3:1.7b."""
    chain = load_models_config(MIXED).tasks[task]
    expected = GPT_120B if task in GROQ_TASKS_120B else GPT_20B
    assert [(r.provider, r.model) for r in chain] == [("groq", expected), ("local", QWEN)]


def test_mixed_config_sends_qa_to_local_models() -> None:
    """PA-443: la suite de QA va en local (qwen3:1.7b y respaldo phi4-mini), sin Groq."""
    chain = load_models_config(MIXED).tasks[TaskType.GENERATE_TESTS]
    assert [(r.provider, r.model) for r in chain] == [("local", QWEN), ("local", PHI)]


def test_todo_local_config_never_uses_groq() -> None:
    """PA-443 (plan B): todo local; ninguna tarea sale del equipo."""
    models = load_models_config(TODO_LOCAL)
    assert set(models.providers) == {"local"}
    for task in TaskType:
        assert set(models.task_providers(task)) == {"local"}, task.value


def test_groq_config_sends_every_task_to_groq_with_local_fallback() -> None:
    """PA-443 (plan B): todo Groq, también la suite, con respaldo local."""
    models = load_models_config(GROQ_FILE)
    for task in TaskType:
        assert models.task_providers(task) == ["groq", "local"], task.value


def test_limits_for_inherits_what_the_provider_does_not_set() -> None:
    """PA-443: `limits_for` = los globales con lo que cambia el proveedor; lo no puesto se
    hereda (p. ej. `max_wait_s` y `max_retries_on_429` del local)."""
    models = load_models_config(MIXED)
    groq, local = models.limits_for("groq"), models.limits_for("local")
    assert (groq.context_window, groq.context_token_budget) == (131_072, 2000)
    assert (groq.max_wait_s, groq.max_retries_on_429, groq.request_timeout_s) == (60, 2, 120)
    assert groq.max_output_tokens == {}
    assert (local.context_window, local.context_token_budget) == (10_240, 3300)
    assert local.request_timeout_s == 900
    assert local.max_wait_s == models.limits.max_wait_s == 20  # heredado
    assert local.max_retries_on_429 == models.limits.max_retries_on_429
    assert groq.daily_token_warning == local.daily_token_warning == 180_000


def test_limits_for_unknown_or_unconfigured_provider_returns_the_global_limits() -> None:
    """PA-443 (límite): un proveedor sin `limits` (o desconocido) usa los globales."""
    models = load_models_config(TODO_LOCAL)
    assert models.providers["local"].limits is None
    assert models.limits_for("local") == models.limits
    assert models.limits_for("proveedor-ficticio") == models.limits


def test_limits_for_empty_output_caps_remove_every_global_cap() -> None:
    """PA-443 (límite): `max_output_tokens: {}` en el proveedor quita los topes globales;
    sin ponerlo (None), se heredan."""
    base = load_models_config(TODO_LOCAL)
    assert base.limits.max_output_tokens  # la configuración global sí tiene topes
    providers = {
        "local": base.providers["local"].model_copy(
            update={"limits": ProviderLimits(max_output_tokens={})}
        ),
        "otro": base.providers["local"].model_copy(
            update={"limits": ProviderLimits(context_window=4096)}
        ),
    }
    models = base.model_copy(update={"providers": providers})
    assert models.limits_for("local").max_output_tokens == {}
    other = models.limits_for("otro")
    assert other.context_window == 4096
    assert other.max_output_tokens == base.limits.max_output_tokens


def test_max_wait_defaults_to_twenty_seconds() -> None:
    """PA-443: `limits.max_wait_s` vale 20 s si la configuración no lo pone."""
    limits = LimitsConfig(max_retries_on_429=2, context_token_budget=100, daily_token_warning=1)
    assert limits.max_wait_s == 20.0


@pytest.mark.parametrize(
    "bad",
    [
        {"context_window": 0},
        {"max_wait_s": -1},
        {"max_retries_on_429": -1},
        {"max_output_tokens": {"tarea_inexistente": 10}},
        {"campo_inventado": 1},
    ],
    ids=["ventana_cero", "espera_negativa", "reintentos_negativos", "tarea_rara", "campo_extra"],
)
def test_provider_limits_reject_invalid_values(tmp_path: Path, bad: dict[str, Any]) -> None:
    """PA-443 (error): unos `limits` de proveedor no válidos dan `ConfigError` al cargar."""
    import yaml

    data = yaml.safe_load(MIXED.read_text(encoding="utf-8"))
    data["providers"]["groq"]["limits"] = bad
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_models_config(path)


def test_context_budget_is_2000_for_groq_tasks_and_3300_for_qa() -> None:
    """PA-443: presupuesto de contexto del primer proveedor de la cadena; sin cadena, global."""
    models = load_models_config(MIXED)
    for task in GROQ_TASKS:
        assert models.context_budget_for(models.task_providers(task)) == 2000, task.value
    assert models.context_budget_for(models.task_providers(TaskType.GENERATE_TESTS)) == 3300
    assert models.context_budget_for([]) == models.limits.context_token_budget == 2000
    assert models.context_budget_for(["local", "groq"]) == 3300


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        (TaskType.GENERATE_STORY, LOCAL_ROOM_2500),
        (TaskType.GENERATE_TESTS, LOCAL_ROOM_2500),
        (TaskType.REVIEW_STORY, 10_240 - 2000 - SAFETY_TOKENS),
        (TaskType.CLASSIFY_SOURCE, 10_240 - 200 - SAFETY_TOKENS),
    ],
    ids=lambda v: v.value if isinstance(v, TaskType) else str(v),
)
def test_available_is_the_minimum_of_the_chain(task: TaskType, expected: int) -> None:
    """PA-443: lo que cabe en el prompt es lo más restrictivo de la cadena (Groq: 131 072 sin
    topes; local: 10 240 − tope de la tarea), para que quepa también en el respaldo."""
    limits = PromptLimits.from_config(_config())
    assert limits.available(task) == expected


def test_available_without_local_fallback_uses_the_groq_window() -> None:
    """PA-443 (límite): una cadena solo de Groq dispone de su ventana entera (sin topes)."""
    base = load_models_config(MIXED)
    tasks = {**base.tasks, TaskType.GENERATE_STORY: base.tasks[TaskType.GENERATE_STORY][:1]}
    config = _config(models=base.model_copy(update={"tasks": tasks}))
    limits = PromptLimits.from_config(config)
    assert limits.available(TaskType.GENERATE_STORY) == 131_072 - SAFETY_TOKENS


def test_available_without_models_keeps_the_global_window() -> None:
    """PA-443 (límite): sin configuración de modelos, ventana − tope de la tarea − margen."""
    limits = PromptLimits(6000, {TaskType.EVOLVE_STORY: 1000})
    assert limits.available(TaskType.EVOLVE_STORY) == 6000 - 1000 - SAFETY_TOKENS


def test_available_falls_back_to_configured_chain_when_resolver_fails() -> None:
    """PA-443 (error): si la cadena efectiva no se puede leer, se usa la configurada y se
    avisa sin el mensaje de la excepción."""

    def broken(_task: TaskType) -> list[str]:
        raise RuntimeError("cadena ficticia rota CON-DETALLE-INTERNO")

    limits = PromptLimits.from_config(_config(), broken)
    with capture_logs() as logs:
        assert limits.available(TaskType.GENERATE_STORY) == LOCAL_ROOM_2500
    [warning] = [e for e in logs if e.get("action") == "context_limits"]
    assert warning["error"] == "RuntimeError"
    assert "CON-DETALLE-INTERNO" not in repr(logs)


def test_overflow_message_cites_the_window_that_actually_limits() -> None:
    """PA-443 · PA-114 (error): con `models.groq.yaml`, lo que no cabe lo decide la ventana
    local del respaldo; el aviso «no cabe» debe citar esa ventana, no la global de Groq."""
    limits = PromptLimits.from_config(_config(GROQ_FILE))
    big = [Message(role="user", content="x" * 3 * (LOCAL_ROOM_2500 + 100))]

    with pytest.raises(ContextOverflowError, match="no cabe") as info:
        fit_messages(lambda _r, _j: big, 0, 0, limits, TaskType.EVOLVE_STORY, action="prueba")

    assert "131072" not in str(info.value)
    assert "10240" in str(info.value)


def test_providers_of_reads_chain_providers_also_through_cancellable_wrapper() -> None:
    """PA-443: `providers_of` lee `chain_providers` del LLM (también envuelto por la API);
    los dobles sin ella devuelven `None`."""
    llm = FallbackLLMProvider(_chain(_local_fallback(), FakeLLMProvider(provider="local")))
    resolver = providers_of(CancellableLLM(llm))
    assert resolver is not None
    assert list(resolver(TaskType.GENERATE_TESTS)) == ["local", "local"]
    assert providers_of(FakeLLMProvider()) is None


def test_without_groq_key_groq_tasks_only_have_the_local_model(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443: sin `GROQ_API_KEY`, las tareas de Groq van directamente al local: cadena,
    proveedores, límites (de la ventana local) y presupuesto (3300) salen de él."""
    config = _config(groq=False)
    router = model_router(config, provider_factory=lambda c: FakeLLMProvider(c.provider, c.model))
    llm = build_llm_provider(config, router=router)
    container = fake_container(tmp_path, config=config, llm=llm)

    for task in GROQ_TASKS:
        assert router.models_for(task) == [ModelChoice("local", QWEN)], task.value
        assert llm.chain_providers(task) == ["local"]
    limits = PromptLimits.from_config(config, providers_of(llm))
    assert limits.available(TaskType.GENERATE_STORY) == LOCAL_ROOM_2500
    service = build_context_service(container, "DEMO", TaskType.GENERATE_STORY)
    assert service._token_budget == 3300
    with pytest.raises(ValueError, match="falta su clave"):
        router.set_override(TaskType.GENERATE_STORY, ModelChoice("groq", GPT_120B))


def test_build_context_service_budget_per_task_and_global_without_task(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443: con tarea, el presupuesto del primer proveedor; sin tarea, el global; sin
    configuración, el de la aplicación."""
    config = _config()
    container = fake_container(tmp_path, config=config)  # FakeLLM: la cadena configurada
    assert build_context_service(container, "DEMO", TaskType.EVOLVE_STORY)._token_budget == 2000
    assert build_context_service(container, "DEMO", TaskType.GENERATE_TESTS)._token_budget == 3300
    assert build_context_service(container, "DEMO")._token_budget == 2000
    bare = fake_container(tmp_path / "sin-config")
    assert build_context_service(bare, "DEMO", TaskType.GENERATE_TESTS)._token_budget == (
        DEFAULT_TOKEN_BUDGET
    )


def test_build_context_service_falls_back_to_configured_chain_when_resolver_fails(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443 (error): si el LLM no da su cadena, el presupuesto es el de la configurada."""

    class BrokenChain(FakeLLMProvider):
        def chain_providers(self, task: TaskType) -> list[str]:
            raise RuntimeError("cadena ficticia rota")

    container = fake_container(tmp_path, config=_config(), llm=BrokenChain())
    with capture_logs() as logs:
        service = build_context_service(container, "DEMO", TaskType.GENERATE_TESTS)
    assert service._token_budget == 3300
    assert any(e.get("action") == "context_budget" for e in logs)


@pytest.mark.parametrize(
    ("mode", "origin", "task"),
    [
        ("qa", STORY, TaskType.GENERATE_TESTS),
        ("functional", STORY, TaskType.EVOLVE_STORY),
        ("functional", EPIC, TaskType.GENERATE_STORY),
        (
            "functional",
            {"kind": "need", "text": "Necesidad ficticia.", "project": "DEMO"},
            TaskType.GENERATE_STORY,
        ),
    ],
    ids=["qa", "evolucionar", "epica", "necesidad"],
)
def test_generation_task_matches_mode_and_origin(mode: str, origin: Origin, task: TaskType) -> None:
    """PA-443: QA → generate_tests; HU con origen story → evolve_story; si no → generate_story."""
    state = initial_state("af-demo", mode, origin)  # type: ignore[arg-type]
    assert nodes._generation_task(state) == task


@pytest.mark.parametrize(
    ("mode", "budget"), [("qa", 3300), ("functional", 2000)], ids=["qa", "evolucionar"]
)
def test_graph_context_service_uses_the_task_budget(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, mode: str, budget: int
) -> None:
    """PA-443: el nodo de contexto reúne con el presupuesto del proveedor de su tarea."""
    graph_nodes = GraphNodes(fake_container(tmp_path, config=_config()))
    state = initial_state("qa-demo" if mode == "qa" else "af-demo", mode, STORY)  # type: ignore[arg-type]
    assert graph_nodes._context_service(state)._token_budget == budget


# --- 4 · PA-443: selector de modelo (RF-42) ------------------------------------------------


def _override_setup(
    tmp_path: Path, config: AppConfig
) -> tuple[ModelRouter, FallbackLLMProvider, GraphNodes]:
    router = model_router(config)  # proveedores reales; crearlos no llama a la red
    llm = build_llm_provider(config, router=router)
    graph_nodes = GraphNodes(fake_container(tmp_path, config=config, llm=llm))
    return router, llm, graph_nodes


def test_override_to_local_moves_groq_task_limits_budget_and_waits_to_local(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443 · RF-42: si en una conversación se elige un modelo local para una tarea de Groq,
    el presupuesto (3300), los topes, el tiempo límite y la espera son los del local."""
    router, llm, graph_nodes = _override_setup(tmp_path, _config())
    state = initial_state("af-demo", "functional", EPIC)  # type: ignore[arg-type]
    assert llm.chain_providers(TaskType.GENERATE_STORY) == ["groq", "local"]
    assert graph_nodes._context_service(state)._token_budget == 2000

    router.set_override(TaskType.GENERATE_STORY, ModelChoice("local", PHI))

    assert llm.chain_providers(TaskType.GENERATE_STORY) == ["local", "groq", "local"]
    assert graph_nodes._context_service(state)._token_budget == 3300
    assert graph_nodes._limits().available(TaskType.GENERATE_STORY) == LOCAL_ROOM_2500
    first = router.chain(TaskType.GENERATE_STORY)[0]
    assert isinstance(first, OpenAICompatibleProvider)
    assert (first.provider, first.model) == ("local", PHI)
    assert first._max_wait_s == 20
    assert first._client.timeout == 900
    assert first._max_output_tokens[TaskType.GENERATE_STORY] == 2500

    router.clear_override(TaskType.GENERATE_STORY)
    assert graph_nodes._context_service(state)._token_budget == 2000


def test_override_to_groq_moves_qa_budget_and_waits_to_groq(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443 · RF-42: si se elige Groq para la suite (local por defecto), el presupuesto (2000),
    la espera ante un 429 (60 s), el tiempo límite (120 s) y los topes (ninguno) son los de
    Groq; lo que cabe en el prompt sigue siendo lo más restrictivo de la cadena efectiva."""
    router, llm, graph_nodes = _override_setup(tmp_path, _config())
    state = initial_state("qa-demo", "qa", STORY)  # type: ignore[arg-type]
    assert graph_nodes._context_service(state)._token_budget == 3300

    router.set_override(TaskType.GENERATE_TESTS, ModelChoice("groq", GPT_120B))

    assert llm.chain_providers(TaskType.GENERATE_TESTS) == ["groq", "local", "local"]
    assert graph_nodes._context_service(state)._token_budget == 2000
    assert (
        build_context_service(graph_nodes.c, "DEMO", TaskType.GENERATE_TESTS)._token_budget == 2000
    )
    assert graph_nodes._limits().available(TaskType.GENERATE_TESTS) == LOCAL_ROOM_2500
    first = router.chain(TaskType.GENERATE_TESTS)[0]
    assert isinstance(first, OpenAICompatibleProvider)
    assert (first.provider, first.model) == ("groq", GPT_120B)
    assert (first._max_wait_s, first._max_retries_on_429) == (60, 2)
    assert first._client.timeout == 120
    assert first._max_output_tokens == {}


def test_override_changes_available_when_it_changes_the_most_restrictive_provider(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """PA-443 · RF-42: `available` sale de la cadena efectiva: con una tarea solo de Groq, elegir
    el local en la conversación baja lo que cabe a la ventana local."""
    base = load_models_config(MIXED)
    tasks = {**base.tasks, TaskType.GENERATE_STORY: base.tasks[TaskType.GENERATE_STORY][:1]}
    config = _config(models=base.model_copy(update={"tasks": tasks}))
    router, llm, graph_nodes = _override_setup(tmp_path, config)
    assert graph_nodes._limits().available(TaskType.GENERATE_STORY) == 131_072 - SAFETY_TOKENS

    router.set_override(TaskType.GENERATE_STORY, ModelChoice("local", QWEN))

    limits = PromptLimits.from_config(config, providers_of(llm))
    assert limits.available(TaskType.GENERATE_STORY) == LOCAL_ROOM_2500
    assert graph_nodes._limits().available(TaskType.GENERATE_STORY) == LOCAL_ROOM_2500


# --- 5 · PA-443: 429, 413 y el código HTTP en el log --------------------------------------


def test_groq_429_waits_retry_after_below_threshold_and_retries() -> None:
    """PA-443: con `Retry-After: 45` y `max_wait_s=60`, se espera 45 s (sleep falso) y se
    reintenta con éxito."""
    provider, server, sleeps = _provider(
        error_response(429, {"Retry-After": "45"}),
        completion("Respuesta ficticia"),
        max_wait_s=60,
        max_retries_on_429=2,
    )

    result = provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "Respuesta ficticia"
    assert sleeps == [45.0]
    assert len(server.requests) == 2


def test_groq_429_stops_after_max_retries() -> None:
    """PA-443 (límite): reintenta hasta `max_retries_on_429` y después `RateLimitError` (429)."""
    provider, server, sleeps = _provider(
        error_response(429, {"Retry-After": "45"}), max_wait_s=60, max_retries_on_429=2
    )

    with pytest.raises(RateLimitError) as info:
        provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert sleeps == [45.0, 45.0]
    assert len(server.requests) == 3
    assert http_status(info.value) == 429


def test_groq_429_above_threshold_passes_to_next_without_sleeping() -> None:
    """PA-443: con `Retry-After: 90` (> 60) no se espera: se pasa al siguiente de la cadena."""
    provider, server, sleeps = _provider(
        error_response(429, {"Retry-After": "90"}), max_wait_s=60, max_retries_on_429=2
    )
    local = _local_fallback()
    llm = FallbackLLMProvider(_chain(provider, local))

    with capture_fallbacks() as events:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert sleeps == []
    assert len(server.requests) == 1
    assert result.provider == "local"
    assert [(e.provider, e.reason) for e in events] == [("groq", "limite")]


def test_factory_builds_groq_with_its_wait_and_local_with_its_timeout_and_caps(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """PA-443: `core/factories` crea cada proveedor con `limits_for(su proveedor)`: Groq con
    espera de 60 s, 2 reintentos, 120 s y sin topes; el local con 900 s y sus topes."""
    config = _config()
    create = _openai_factory(config)

    groq = create(ModelChoice("groq", GPT_120B))
    local = create(ModelChoice("local", QWEN))

    assert isinstance(groq, OpenAICompatibleProvider)
    assert isinstance(local, OpenAICompatibleProvider)
    assert (groq._max_wait_s, groq._max_retries_on_429, groq._client.timeout) == (60, 2, 120)
    assert groq._max_output_tokens == {}
    local_limits = config.models.limits_for("local")
    assert local._client.timeout == 900
    assert local._max_wait_s == 20
    assert local._max_output_tokens == dict(local_limits.max_output_tokens)
    assert local._max_output_tokens[TaskType.GENERATE_TESTS] == 2500


def test_factory_groq_variant_caps_only_the_suite(clean_env: pytest.MonkeyPatch) -> None:
    """PA-443: en `models.groq.yaml`, Groq solo lleva tope de salida en la suite."""
    groq = _openai_factory(_config(GROQ_FILE))(ModelChoice("groq", GPT_120B))
    assert isinstance(groq, OpenAICompatibleProvider)
    assert groq._max_output_tokens == {TaskType.GENERATE_TESTS: 2500}
    assert groq._max_wait_s == 60


@pytest.mark.parametrize("structured", [False, True], ids=["generate", "generate_structured"])
def test_413_raises_prompt_too_large_without_retrying(structured: bool) -> None:
    """PA-443: un 413 lanza `PromptTooLargeError` (con el código, sin el cuerpo) tras una sola
    petición y sin esperar."""
    provider, server, sleeps = _provider(error_response(413))

    with pytest.raises(PromptTooLargeError) as info:
        if structured:
            provider.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_TESTS)
        else:
            provider.generate(MESSAGES, TaskType.GENERATE_TESTS)

    assert len(server.requests) == 1
    assert sleeps == []
    assert http_status(info.value) == 413
    assert BODY_MARKER not in str(info.value)
    assert "413" in str(info.value)


def test_413_passes_to_fallback_with_reason_no_cabe() -> None:
    """PA-443: `FallbackLLMProvider` pasa al respaldo con el motivo `no_cabe`, el evento de
    cambio de proveedor y su aviso en español."""
    provider, server, _ = _provider(error_response(413))
    llm = FallbackLLMProvider(_chain(provider, _local_fallback()))

    with capture_fallbacks() as events, capture_logs() as logs:
        result = llm.generate(MESSAGES, TaskType.GENERATE_TESTS)

    assert result.provider == "local"
    assert len(server.requests) == 1
    [event] = events
    assert isinstance(event, FallbackEvent)
    assert (event.task, event.provider, event.model, event.reason) == (
        TaskType.GENERATE_TESTS,
        "groq",
        GPT_120B,
        "no_cabe",
    )
    assert event.message == "groq no admite una petición tan grande."
    [failed] = _failed_events(logs)
    assert (failed["reason"], failed["http_status"]) == ("no_cabe", 413)


@pytest.mark.parametrize(
    ("reply", "error", "status"),
    [
        (error_response(413), PromptTooLargeError, 413),
        (error_response(429, {"Retry-After": "999"}), RateLimitError, 429),
        (error_response(500), ExternalServiceError, 500),
        (error_response(401), AuthenticationError, 401),
        (error_response(403), AuthenticationError, 403),
        (error_response(404), ExternalServiceError, 404),
        (error_response(400), ExternalServiceError, 400),
        (httpx.ReadTimeout("tiempo ficticio agotado"), ProviderTimeoutError, None),
        (httpx.ConnectError("conexión ficticia rechazada"), ExternalServiceError, None),
    ],
    ids=["413", "429", "500", "401", "403", "404", "400", "timeout", "conexion"],
)
def test_http_status_is_logged_and_body_never(
    reply: Reply, error: type[Exception], status: int | None
) -> None:
    """PA-443 · PA-441: `llm_provider_failed` lleva `http_status` (None sin respuesta HTTP) y
    nunca el cuerpo de la respuesta del proveedor."""
    provider, _, sleeps = _provider(reply, max_wait_s=60)
    llm = FallbackLLMProvider(_chain(provider, _local_fallback()))

    with capture_logs() as logs:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.provider == "local"
    assert sleeps == []
    [failed] = _failed_events(logs)
    assert failed["http_status"] == status
    assert failed["error"] == error.__name__
    assert failed["provider"] == "groq"
    assert BODY_MARKER not in repr(logs)
    assert "detalle interno" not in repr(logs)


def test_http_status_helpers_annotate_only_integers() -> None:
    """PA-441 (límite): `http_status` solo devuelve enteros; sin anotar, `None`."""
    plain = ExternalServiceError("Error ficticio.")
    assert http_status(plain) is None
    assert http_status(with_http_status(ExternalServiceError("Error ficticio."), 502)) == 502
    odd = ExternalServiceError("Error ficticio.")
    odd.http_status = "502"  # type: ignore[attr-defined]
    assert http_status(odd) is None


def test_chain_exhausted_by_413_and_429_reports_both_reasons() -> None:
    """PA-443 (error): si el 413 y el 429 agotan la cadena, falla con los dos eventos."""
    big, _, _ = _provider(error_response(413))
    limited, _, _ = _provider(
        error_response(429, {"Retry-After": "999"}), name="local", model=QWEN, max_wait_s=20
    )
    llm = FallbackLLMProvider(_chain(big, limited))

    with capture_fallbacks() as events, pytest.raises(ExternalServiceError):
        llm.generate([Message(role="user", content="Petición ficticia.")], TaskType.NL_TO_JQL)

    assert [(e.provider, e.reason) for e in events] == [("groq", "no_cabe"), ("local", "limite")]
