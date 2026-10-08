"""Ronda 17 de la auditoría: PA-457/PA-440 (reintento por formato), PA-456 (estructura compartida
en la revisión de calidad) y dos ajustes (`QualityReport` citado y `QualityReviewer.limits`).

1. PA-457 · `adapters/llm/openai_compatible.py`: el reintento por formato no válido (RNF-28) ya
   no lleva la respuesta fallida, solo un mensaje `user` con los errores recortados
   (`_MAX_RETRY_ERRORS_CHARS`); antes de llamar, `_fits` estima si cabe en `context_window` y,
   si no, lanza `StructuredOutputError` («no cabe») sin llamar, con los tokens ya gastados.
   `core/factories` pasa la ventana de cada proveedor (`limits_for`).
2. PA-456 · `core/functional/shared_structure.py`: el grafo y la revisión de calidad comparten la
   HU estructurada; la revisión solo estructura (y suma esos tokens) si no estaba guardada.
3. `QualityReport` en `CITED_SCHEMAS`, `without_forced_citations` en la revisión y
   `QualityReviewer.limits` con la cadena efectiva (`providers_of`).

Sin red: el HTTP va por `httpx.MockTransport` y el resto usa los fakes de `tests/fakes/`. Datos
100 % ficticios (Biblioteca de Villaficticia, clave «test-key»).
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError, create_model
from structlog.testing import capture_logs

import core.quality as quality
from adapters.base import TaskType
from adapters.errors import ExternalServiceError
from adapters.llm.openai_compatible import (
    _GUARD_CHARS_PER_TOKEN,
    _GUARD_MESSAGE_TOKENS,
    _GUARD_SAFETY_TOKENS,
    _MAX_RETRY_ERRORS_CHARS,
    OpenAICompatibleProvider,
    StructuredOutputError,
    _validation_errors,
    spent_tokens,
)
from adapters.llm.router import ModelChoice
from adapters.llm.schema_hints import llm_json_schema
from core.artifact_state import InMemoryArtifactStateStore
from core.config import ROOT_DIR, AppConfig, Settings, load_models_config
from core.container import Container
from core.factories import _openai_factory
from core.functional.citations import without_forced_citations
from core.functional.context import StoryContext
from core.functional.shared_structure import (
    STRUCTURE_CACHE_VERSION,
    load_shared_structure,
    save_shared_structure,
    shared_structure_id,
)
from core.graph import nodes
from core.quality import QualityReviewer
from core.rag.prompts import load_prompt
from schemas.common import SourceRef
from schemas.quality import QualityReport
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report
from tests.unit.test_cross_b_quality import ScriptedLLM
from tests.unit.test_llm_openai_compatible import (
    MESSAGES,
    TEST_PROMPTS,
    VALID_ANSWER,
    Answer,
    completion,
    make_provider,
    schema_rejected_response,
)
from tests.unit.test_mixed_models import GPT_120B, QWEN, _config
from tests.unit.test_stable_structure import _run, _spy_shared_ids, _structure_calls

AF = dataset.DEMO_USERS["af-demo"][1]
KEY = "DEMO-3"
INVALID_ANSWER = '{"title": "RESPUESTA-FALLIDA-NO-REENVIAR", "score": "no-es-un-numero"}'
TASK = TaskType.GENERATE_STORY
OUTPUT_CAP = 2000  # tope de salida ficticio de la tarea
TEST_MODELS = ROOT_DIR / "tests" / "fixtures" / "models.yaml"


# --- utilidades del adaptador -------------------------------------------------------------------


def _answer_errors(content: str = INVALID_ANSWER) -> str:
    """Los errores que el adaptador calcula para `Answer` (sin valores de entrada)."""
    try:
        Answer.model_validate_json(content)
    except ValidationError as exc:
        return _validation_errors(exc)
    raise AssertionError("la respuesta ficticia debería ser inválida")


def _needed(errors: str, *, json_mode: bool = False, schema: type[BaseModel] = Answer) -> int:
    """Estimación de la guarda (PA-457) para el reintento sobre `MESSAGES`."""
    feedback = TEST_PROMPTS.retry.replace("{errors}", errors[:_MAX_RETRY_ERRORS_CHARS])
    contents = [m.content for m in MESSAGES] + [feedback]
    chars = sum(len(c) for c in contents)
    if json_mode:
        chars += len(TEST_PROMPTS.json_mode) + len(json.dumps(llm_json_schema(schema)))
    tokens = -(-chars // _GUARD_CHARS_PER_TOKEN) + _GUARD_MESSAGE_TOKENS * len(contents)
    return tokens + OUTPUT_CAP + _GUARD_SAFETY_TOKENS


def _guarded(window: int | None, *replies: Any) -> Any:
    return make_provider(
        *replies or (completion(INVALID_ANSWER), completion(VALID_ANSWER)),
        context_window=window,
        max_output_tokens={TASK: OUTPUT_CAP},
    )


def _long_field_schema() -> type[BaseModel]:
    """Esquema ficticio con cinco campos de nombre largo: errores de más de 1500 caracteres."""
    fields: dict[str, Any] = {f"campo_ficticio_{i}_{'x' * 400}": (str, ...) for i in range(5)}
    return create_model("EsquemaLargoFicticio", **fields)


# --- 1 · PA-457 · reintento que no cabe -----------------------------------------------------------


def test_retry_raises_does_not_fit_without_calling_model_when_window_too_small() -> None:
    """PA-457 (error): si el reintento no cabe, `StructuredOutputError` («no cabe») sin llamar
    otra vez al modelo, con los tokens ya gastados y el log `llm_retry_does_not_fit`."""
    window = _needed(_answer_errors()) - 1
    setup = _guarded(window, completion(INVALID_ANSWER, prompt_tokens=40, completion_tokens=9))

    with capture_logs() as logs, pytest.raises(StructuredOutputError) as info:
        setup.provider.generate_structured(MESSAGES, Answer, TASK)

    assert len(setup.server.requests) == 1
    assert isinstance(info.value, ExternalServiceError)
    message = str(info.value)
    assert "no cabe" in message and str(window) in message and "Answer" in message
    assert "RESPUESTA-FALLIDA" not in message and "test-key" not in message
    assert spent_tokens(info.value) == (40, 9)
    (entry,) = [e for e in logs if e["event"] == "llm_retry_does_not_fit"]
    assert entry["context_window"] == window
    assert entry["estimated_tokens"] == window + 1
    assert entry["action"] == "llm_call"
    assert "RESPUESTA-FALLIDA" not in json.dumps(logs, default=str)


def test_retry_runs_when_estimate_equals_window() -> None:
    """PA-457 (límite): con la estimación justo igual a la ventana, el reintento cabe."""
    setup = _guarded(_needed(_answer_errors()))

    with capture_logs() as logs:
        result = setup.provider.generate_structured(MESSAGES, Answer, TASK)

    assert result.content == Answer(title="Renovación ficticia", score=7)
    assert len(setup.server.requests) == 2
    assert "llm_retry_does_not_fit" not in [e["event"] for e in logs]


def test_retry_that_fits_sums_tokens_and_sends_cap() -> None:
    """PA-457 · RNF-28: un reintento que cabe sigue funcionando: suma tokens y lleva el tope."""
    setup = _guarded(
        100_000,
        completion(INVALID_ANSWER, prompt_tokens=10, completion_tokens=5),
        completion(VALID_ANSWER, prompt_tokens=20, completion_tokens=6),
    )

    result = setup.provider.generate_structured(MESSAGES, Answer, TASK)

    assert (result.input_tokens, result.output_tokens) == (30, 11)
    assert [body["max_tokens"] for body in setup.server.bodies()] == [OUTPUT_CAP, OUTPUT_CAP]


def test_retry_has_no_guard_without_context_window() -> None:
    """PA-457 (límite): sin `context_window` no hay guarda, aunque el tope sea enorme."""
    setup = make_provider(
        completion(INVALID_ANSWER),
        completion(VALID_ANSWER),
        max_output_tokens={TASK: 10_000_000},
    )

    with capture_logs() as logs:
        result = setup.provider.generate_structured(MESSAGES, Answer, TASK)

    assert result.content.score == 7
    assert len(setup.server.requests) == 2
    assert "llm_retry_does_not_fit" not in [e["event"] for e in logs]


def test_guard_counts_schema_in_json_mode() -> None:
    """PA-457: en modo JSON el esquema va como texto y la guarda lo cuenta; la misma ventana
    basta con JSON Schema (el esquema va en `response_format`)."""
    window = _needed(_answer_errors())  # cabe justo sin el esquema
    assert _needed(_answer_errors(), json_mode=True) > window

    with_schema = _guarded(window)
    with_schema.provider.generate_structured(MESSAGES, Answer, TASK)
    assert len(with_schema.server.requests) == 2

    json_mode = _guarded(
        window,
        schema_rejected_response(),
        completion(INVALID_ANSWER, prompt_tokens=12, completion_tokens=4),
        completion(VALID_ANSWER),
    )
    with pytest.raises(StructuredOutputError, match="no cabe") as info:
        json_mode.provider.generate_structured(MESSAGES, Answer, TASK)
    assert len(json_mode.server.requests) == 2  # el 400 y la primera en modo JSON
    assert json_mode.server.bodies()[1]["response_format"] == {"type": "json_object"}
    assert spent_tokens(info.value) == (12, 4)


def test_guard_in_json_mode_fits_when_window_includes_schema() -> None:
    """PA-457 (límite): en modo JSON, con la ventana que cubre también el esquema, reintenta."""
    setup = _guarded(
        _needed(_answer_errors(), json_mode=True),
        schema_rejected_response(),
        completion(INVALID_ANSWER),
        completion(VALID_ANSWER),
    )

    result = setup.provider.generate_structured(MESSAGES, Answer, TASK)

    assert result.content.score == 7
    assert len(setup.server.requests) == 3


# --- 1 · PA-457 · contenido del reintento ---------------------------------------------------------


def test_retry_sends_errors_but_not_failed_response() -> None:
    """PA-457 (PA-440): el reintento es la petición original más un `user` con los errores; ni
    un mensaje `assistant` ni el texto de la respuesta fallida."""
    setup = _guarded(None)

    setup.provider.generate_structured(MESSAGES, Answer, TASK)

    first, second = setup.server.bodies()
    assert second["messages"][:-1] == first["messages"]
    assert [m["role"] for m in second["messages"]] == ["system", "user", "user"]
    feedback = second["messages"][-1]["content"]
    assert feedback == TEST_PROMPTS.retry.replace("{errors}", _answer_errors())
    sent = json.dumps(second["messages"], ensure_ascii=False)
    assert "RESPUESTA-FALLIDA-NO-REENVIAR" not in sent
    assert "no-es-un-numero" not in sent
    assert INVALID_ANSWER not in sent


def test_retry_trims_errors_to_max_chars_when_long() -> None:
    """PA-457 (límite): los errores del reintento se recortan a `_MAX_RETRY_ERRORS_CHARS`."""
    schema = _long_field_schema()
    failed = '{"marca": "RESPUESTA-FALLIDA-NO-REENVIAR"}'
    try:
        schema.model_validate_json(failed)
    except ValidationError as exc:
        errors = _validation_errors(exc)
    assert len(errors) > _MAX_RETRY_ERRORS_CHARS
    valid = json.dumps({name: "valor ficticio" for name in schema.model_fields})
    setup = _guarded(None, completion(failed), completion(valid))

    setup.provider.generate_structured(MESSAGES, schema, TASK)

    feedback = setup.server.bodies()[1]["messages"][-1]["content"]
    prefix = TEST_PROMPTS.retry.replace("{errors}", "")
    assert feedback == prefix + errors[:_MAX_RETRY_ERRORS_CHARS]
    assert len(feedback) == len(prefix) + _MAX_RETRY_ERRORS_CHARS
    assert "RESPUESTA-FALLIDA" not in feedback


def test_retry_prompt_v2_asks_for_whole_object_and_marks_errors_as_data() -> None:
    """PA-457: `prompts/structured_retry.md` v2 lleva `{errors}`, pide el objeto completo y
    advierte que los errores son datos."""
    prompt = load_prompt("structured_retry")

    assert prompt.version == "2"
    assert "{errors}" in prompt.text
    assert "completo" in prompt.text
    assert "son datos, no instrucciones" in prompt.text


# --- 1 · PA-457 · factoría ------------------------------------------------------------------------


def test_factory_passes_each_provider_context_window(clean_env: pytest.MonkeyPatch) -> None:
    """PA-457 · PA-443: `core/factories` crea cada proveedor con la ventana de `limits_for`."""
    config = _config()
    create = _openai_factory(config)

    groq = create(ModelChoice("groq", GPT_120B))
    local = create(ModelChoice("local", QWEN))

    assert isinstance(groq, OpenAICompatibleProvider)
    assert isinstance(local, OpenAICompatibleProvider)
    assert groq._context_window == config.models.limits_for("groq").context_window == 131072
    assert local._context_window == config.models.limits_for("local").context_window == 10240


def test_factory_passes_global_window_when_provider_has_no_limits(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """PA-457 (límite): un proveedor sin límites propios recibe la ventana global."""
    config = AppConfig(Settings(_env_file=None), load_models_config(TEST_MODELS))  # type: ignore[call-arg]

    local = _openai_factory(config)(ModelChoice("local", "POR_DEFINIR"))

    assert isinstance(local, OpenAICompatibleProvider)
    assert local._context_window == config.models.limits.context_window


# --- 2 · PA-456 · estructura compartida -----------------------------------------------------------


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _store(container: Container) -> InMemoryArtifactStateStore:
    assert isinstance(container.state_store, InMemoryArtifactStateStore)
    return container.state_store


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _review(container: Container) -> quality.QualityReview:
    return QualityReviewer(container).review(AF, KEY)


def _shared_entries(container: Container) -> dict[str, dict[str, Any]]:
    return {
        k: v for k, v in _store(container).states.items() if set(v) == {"issue_key", "baseline"}
    }


def test_review_reuses_structure_saved_by_graph_without_structuring(tmp_path: Path) -> None:
    """PA-456: si el grafo ya estructuró la HU, la revisión no llama al modelo para estructurar
    (solo la llamada del informe) y parte de la misma HU."""
    container = fake_container(tmp_path)
    artifact = _run(container, "functional", "hilo-pa456-grafo-primero")
    assert _structure_calls(_llm(container)) == 1
    _llm(container).calls.clear()

    review = _review(container)

    assert [c["schema"] for c in _llm(container).calls] == [QualityReport]
    baseline = _store(container).states[str(artifact.id)]["baseline"]
    assert review.story.model_dump(mode="json") == baseline


def test_graph_reuses_structure_saved_by_review(tmp_path: Path) -> None:
    """PA-456: si la revisión estructuró la HU, el grafo la reutiliza sin estructurar."""
    container = fake_container(tmp_path)
    review = _review(container)
    assert _structure_calls(_llm(container)) == 1

    artifact = _run(container, "functional", "hilo-pa456-revision-primero")

    assert _structure_calls(_llm(container)) == 1
    baseline = _store(container).states[str(artifact.id)]["baseline"]
    assert baseline == review.story.model_dump(mode="json")


def test_graph_and_review_compute_same_shared_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-456: para la misma HU, el grafo y la revisión calculan el mismo identificador."""
    container = fake_container(tmp_path)
    _review(container)
    (review_id,) = _shared_entries(container)

    ids = _spy_shared_ids(monkeypatch)
    _run(container, "functional", "hilo-pa456-mismo-id")

    assert ids == [review_id]


def test_shared_id_matches_graph_helper_for_same_context() -> None:
    """PA-456: `shared_structure_id` y `nodes._shared_baseline_id` coinciden; depende de la
    clave, el contenido, la versión del prompt y la de la caché; sin clave, `None`."""
    issue = FakeIssueTracker().get_issue(KEY)
    origin_only = StoryContext(origin_kind="story", origin_key=KEY, jira=[issue])
    version = load_prompt("structure_story").version

    shared = shared_structure_id(KEY, origin_only, version)

    assert shared == nodes._shared_baseline_id(KEY, origin_only)
    assert shared == shared_structure_id(KEY, origin_only, version, STRUCTURE_CACHE_VERSION)
    assert shared != shared_structure_id(KEY, origin_only, version, STRUCTURE_CACHE_VERSION + 1)
    assert shared != shared_structure_id(KEY, origin_only, f"{version}-ficticia")
    changed = issue.model_copy(update={"description_text": "Otro contenido ficticio."})
    assert shared != shared_structure_id(
        KEY, StoryContext(origin_kind="story", origin_key=KEY, jira=[changed]), version
    )
    assert shared_structure_id(None, origin_only, version) is None
    assert shared_structure_id("", origin_only, version) is None


def test_review_structures_again_when_story_changes(tmp_path: Path) -> None:
    """PA-456 · PA-432: si la HU cambia en Jira, la revisión vuelve a estructurar (otra entrada)."""
    container = fake_container(tmp_path)
    _review(container)

    issue = _tracker(container).issues[KEY]
    issue.description_text += " Además, se avisa por correo (cambio ficticio)."
    _review(container)

    assert _structure_calls(_llm(container)) == 2
    assert len(_shared_entries(container)) == 2


def test_second_review_of_unchanged_story_does_not_structure(tmp_path: Path) -> None:
    """PA-456: dos revisiones de la misma HU sin cambios estructuran una sola vez."""
    container = fake_container(tmp_path)

    first = _review(container)
    second = _review(container)

    assert _structure_calls(_llm(container)) == 1
    assert first.story == second.story
    assert len(_shared_entries(container)) == 1


def test_review_tokens_exclude_structure_when_reused(tmp_path: Path) -> None:
    """PA-456: los tokens de `QualityReview` suman la estructuración solo si se llamó al modelo."""
    llm = ScriptedLLM()
    container = fake_container(tmp_path, llm=llm)

    first = _review(container)
    structure, report = llm.results
    assert (first.input_tokens, first.output_tokens) == (
        structure.input_tokens + report.input_tokens,
        structure.output_tokens + report.output_tokens,
    )

    second = _review(container)
    assert len(llm.results) == 3
    last = llm.results[-1]
    assert last.content.__class__ is QualityReport
    assert (second.input_tokens, second.output_tokens) == (last.input_tokens, last.output_tokens)


def test_review_still_works_when_shared_store_fails(tmp_path: Path) -> None:
    """PA-456 (error): si el almacén falla al leer o guardar la entrada compartida, la revisión
    estructura con el modelo y termina igual (es solo un ahorro)."""

    class BrokenStore(InMemoryArtifactStateStore):
        def load(self, artifact_id: str) -> dict[str, Any] | None:
            raise RuntimeError("almacén ficticio caído")

        def save(self, artifact_id: str, state: dict[str, Any]) -> None:
            raise RuntimeError("almacén ficticio caído")

    container = fake_container(tmp_path, state_store=BrokenStore())

    review = _review(container)

    assert review.report.summary
    assert _structure_calls(_llm(container)) == 1


def test_load_ignores_entry_of_other_key() -> None:
    """PA-456 (límite): una entrada guardada para otra clave no se reutiliza."""
    store = InMemoryArtifactStateStore()
    story = dataset.renewal_story(jira_key=KEY)
    save_shared_structure(store, "entrada-ficticia", KEY, story)

    assert load_shared_structure(store, "entrada-ficticia", KEY) == story
    assert load_shared_structure(store, "entrada-ficticia", "DEMO-4") is None
    assert load_shared_structure(store, None, KEY) is None


# --- 3 · QualityReport citado y límites -----------------------------------------------------------


def test_quality_report_schema_sent_requires_sources() -> None:
    """PA-456: el esquema de `QualityReport` enviado al proveedor lleva `sources` obligatorio con
    `minItems: 1`."""
    report = renewal_quality_report().model_copy(
        update={"sources": [SourceRef(kind="jira", ref=KEY)]}
    )
    setup = make_provider(completion(report.model_dump_json()))

    setup.provider.generate_structured(MESSAGES, QualityReport, TaskType.REVIEW_STORY)

    sent = setup.server.bodies()[0]["response_format"]["json_schema"]["schema"]
    assert "sources" in sent["required"]
    assert sent["properties"]["sources"]["minItems"] == 1


def test_without_forced_citations_removes_sources_of_report_without_context() -> None:
    """PA-456: sin fuentes en el contexto, las citas del informe se quitan; con fuentes, no."""
    report = renewal_quality_report().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="DOC-INVENTADO-77")]}
    )

    assert without_forced_citations(report, []).sources == []
    sources = StoryContext(
        origin_kind="story", origin_key=KEY, jira=[FakeIssueTracker().get_issue(KEY)]
    ).sources()
    assert without_forced_citations(report, sources) is report


def test_review_drops_forced_citation_when_context_has_no_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-456: si el contexto de la revisión no trae fuentes, la cita forzada del informe se
    quita y no da `CitationError` (ni reintento)."""

    class EmptyContext:
        def gather(self, *_args: Any, **_kwargs: Any) -> Any:
            return SimpleNamespace(jira=[], rag=[])

    monkeypatch.setattr(quality, "build_context_service", lambda *_a, **_k: EmptyContext())
    container = fake_container(tmp_path)
    forced = renewal_quality_report().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="DOC-INVENTADO-77")]}
    )
    _llm(container).builders[QualityReport] = lambda _messages: forced

    review = _review(container)

    assert review.report.sources == []
    assert [c["schema"] for c in _llm(container).calls].count(QualityReport) == 1


class _ChainLLM(FakeLLMProvider):
    """Doble con la cadena efectiva (como `FallbackLLMProvider.chain_providers`)."""

    def chain_providers(self, task: TaskType) -> list[str]:
        return ["groq"]


def test_quality_limits_use_effective_chain(tmp_path: Path, clean_env: pytest.MonkeyPatch) -> None:
    """Ajuste PA-443: `QualityReviewer.limits` usa la cadena efectiva del LLM (`providers_of`):
    con solo Groq elegido, la ventana es la de Groq y no la del respaldo local configurado."""
    llm = _ChainLLM()
    reviewer = QualityReviewer(fake_container(tmp_path, config=_config(), llm=llm))

    limits = reviewer.limits

    assert limits.providers_for == llm.chain_providers
    assert limits.window(TaskType.REVIEW_STORY) == 131072


def test_quality_limits_use_configured_chain_without_effective_chain(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """Ajuste PA-443 (límite): sin cadena efectiva, la configurada (Groq y local: la local)."""
    reviewer = QualityReviewer(fake_container(tmp_path, config=_config()))

    limits = reviewer.limits

    assert limits.providers_for is None
    assert limits.window(TaskType.REVIEW_STORY) == 10240


def test_review_report_receives_reused_story(tmp_path: Path) -> None:
    """PA-456: la llamada del informe tras reutilizar la estructura lleva la HU guardada en el
    contexto (`<hu_actual>`), con sus CA."""
    container = fake_container(tmp_path)
    first = _review(container)
    _llm(container).calls.clear()

    _review(container)

    (call,) = _llm(container).calls
    user = "\n".join(m.content for m in call["messages"] if m.role == "user")
    assert "<hu_actual>" in user
    assert all(c.id in user for c in first.story.acceptance_criteria)
