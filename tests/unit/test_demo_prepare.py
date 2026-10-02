"""Preparación de las conversaciones de la demo (T-36, parte 1): `eval/demo_prepare.py`.

Todo sobre `fake_runtime`: sin `.env`, sin red, sin Jira ni LLM reales. Datos 100 % ficticios
(proyecto DEMO del dataset sintético y claves DEMO-5xx). Se llama a `prepare` directamente; la
línea de órdenes solo se prueba con `--fake` o con la composición real sustituida.
"""

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import api.runtime
from adapters.base import IssueSummary, Message, User
from adapters.errors import ExternalServiceError
from api import executions, service
from api.runtime import Runtime
from eval import demo_prepare
from eval.demo_prepare import (
    EVOLVE_FEEDBACK,
    MANIFEST,
    NEED_FEEDBACK,
    NEED_TEXT,
    SANDBOX_STEPS,
    SIMULATION_STEPS,
    SUMMARY,
    DemoPrepareError,
    Options,
    Prepared,
    build,
    main,
    options_from,
    parse_args,
    prepare,
    render_summary,
)
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider, _story_citing_context
from tests.fakes.test_management import FakeTestManagement

STORY = "DEMO-3"
AF = User(username="af-demo", role="functional")
QA = User(username="qa-demo", role="qa")
CASES = [
    IssueSummary(
        key="DEMO-501",
        summary="[CP-01] Caso ficticio uno",
        issue_type="Subtarea",
        status="Por hacer",
    ),
    IssueSummary(
        key="DEMO-502",
        summary="[CP-02] Caso ficticio dos",
        issue_type="Subtarea",
        status="Por hacer",
    ),
]
SIMULATION_NAMES = [s.name for s in SIMULATION_STEPS]
SANDBOX_NAMES = [s.name for s in SANDBOX_STEPS]


# --- utilidades --------------------------------------------------------------------------


def _container(rt: Runtime) -> Any:
    return rt.workspace_factory().container


def _tracker(rt: Runtime) -> FakeIssueTracker:
    tracker = _container(rt).issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    return tracker


def _tm(rt: Runtime) -> FakeTestManagement:
    tm = _container(rt).test_management
    assert isinstance(tm, FakeTestManagement)
    return tm


def _llm(rt: Runtime) -> FakeLLMProvider:
    llm = _container(rt).llm
    assert isinstance(llm, FakeLLMProvider)
    return llm


def _by_name(items: list[Prepared]) -> dict[str, Prepared]:
    return {i.name: i for i in items}


def _with_cases(rt: Runtime) -> Runtime:
    _tm(rt).cases[STORY] = list(CASES)
    return rt


def _unset_publish_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quita JIRA_PUBLISH_MODE de forma que monkeypatch lo restaure al terminar."""
    monkeypatch.setenv("JIRA_PUBLISH_MODE", "simulation")
    monkeypatch.delenv("JIRA_PUBLISH_MODE")


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path / "rt", publish_mode="simulation")


@pytest.fixture
def out(tmp_path: Path) -> Path:
    return tmp_path / "demo"


@pytest.fixture
def no_tempdir_leak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """`build` con `--fake` crea su carpeta de trabajo dentro de `tmp_path`."""
    workdir = tmp_path / "work"

    def mkdtemp(prefix: str = "") -> str:
        workdir.mkdir(parents=True, exist_ok=True)
        return str(workdir)

    monkeypatch.setattr(demo_prepare.tempfile, "mkdtemp", mkdtemp)
    return workdir


# --- 1. Simulación con fakes ------------------------------------------------------------


def test_prepare_creates_all_simulation_steps_in_order_with_fakes(rt: Runtime, out: Path) -> None:
    """Criterio 1: los 8 pasos de SIMULATION_STEPS, en orden, cada uno en su estado esperado."""
    items = prepare(_with_cases(rt), Options(), out)

    assert [i.name for i in items] == SIMULATION_NAMES
    for item in items:
        assert item.state == item.expected, (item.name, item.state, item.note)
        assert item.id
        assert item.seconds is not None and item.seconds >= 0


def test_prepare_iterates_need_conversation_to_two_versions(rt: Runtime, out: Path) -> None:
    """Criterio 1: necesidad-iterada queda in_review con 2 versiones y el feedback aplicado."""
    item = _by_name(prepare(rt, Options(), out))["necesidad-iterada"]

    assert item.state == "in_review"
    conv = service.conversation_out(rt, rt.workspace_factory(), AF, item.id or "")
    assert conv.state == "in_review"
    assert len(conv.versions) == 2
    assert NEED_FEEDBACK in conv.feedback
    assert item.model == "fake/fake-model"
    assert item.user == "af-demo"


def test_prepare_leaves_evolutions_in_review_and_simulated(rt: Runtime, out: Path) -> None:
    """Criterio 1: evolucion-en-revision in_review; evolucion-simulada simulated en el servidor."""
    items = _by_name(prepare(rt, Options(), out))
    ws = rt.workspace_factory()

    review = service.conversation_out(rt, ws, AF, items["evolucion-en-revision"].id or "")
    simulated = service.conversation_out(rt, ws, AF, items["evolucion-simulada"].id or "")
    assert review.state == "in_review"
    assert simulated.state == "simulated"
    assert simulated.result is not None and simulated.result.simulated is True


def test_prepare_chains_qa_from_simulated_story_with_handoff(rt: Runtime, out: Path) -> None:
    """Criterio 1: qa-encadenada-en-revision in_review, de qa-demo y con su handoff_id."""
    item = _by_name(prepare(rt, Options(), out))["qa-encadenada-en-revision"]

    assert item.state == "in_review"
    assert item.user == "qa-demo"
    assert item.handoff_id
    assert rt.handoffs is not None and rt.handoffs.get(item.handoff_id) is not None
    conv = service.conversation_out(rt, rt.workspace_factory(), QA, item.id or "")
    assert conv.state == "in_review"
    assert conv.mode == "qa"


def test_prepare_leaves_direct_qa_in_review_and_simulated(rt: Runtime, out: Path) -> None:
    """Criterio 1: qa-directa-en-revision in_review y qa-directa-simulada simulated."""
    items = _by_name(prepare(rt, Options(), out))
    ws = rt.workspace_factory()

    assert service.conversation_out(rt, ws, QA, items["qa-directa-en-revision"].id or "").state == (
        "in_review"
    )
    assert service.conversation_out(rt, ws, QA, items["qa-directa-simulada"].id or "").state == (
        "simulated"
    )


def test_prepare_skips_execution_when_story_has_no_cases(rt: Runtime, out: Path) -> None:
    """Criterio 1: sin casos publicados, ejecucion-en-revision queda «skipped» con su nota."""
    item = _by_name(prepare(rt, Options(), out))["ejecucion-en-revision"]

    assert item.state == "skipped"
    assert item.id is None
    assert STORY in item.note and "casos publicados" in item.note


def test_prepare_opens_execution_in_review_when_story_has_cases(rt: Runtime, out: Path) -> None:
    """Criterio 1: con casos en Jira, ejecucion-en-revision queda in_review con esos casos."""
    item = _by_name(prepare(_with_cases(rt), Options(), out))["ejecucion-en-revision"]

    assert item.state == "in_review"
    described = executions.describe(rt, rt.workspace_factory(), QA, item.id or "")
    assert described.state == "in_review"
    assert [c.key for c in described.cases] == ["DEMO-501", "DEMO-502"]
    assert _tm(rt).executions == []


def test_prepare_uses_execution_story_option_for_cases(rt: Runtime, out: Path) -> None:
    """Criterio 1: `execution_story` decide qué HU se consulta para el registro (T-47)."""
    _tm(rt).cases["DEMO-4"] = list(CASES)
    item = _by_name(prepare(rt, Options(execution_story="DEMO-4"), out))["ejecucion-en-revision"]

    assert item.state == "in_review"
    assert executions.describe(rt, rt.workspace_factory(), QA, item.id or "").story_key == "DEMO-4"


def test_prepare_writes_quality_report_file(rt: Runtime, out: Path) -> None:
    """Criterio 1: calidad queda done y escribe calidad-DEMO-3.md en la carpeta de salida."""
    item = _by_name(prepare(rt, Options(), out))["calidad"]

    assert item.state == "done"
    assert item.id == "calidad-DEMO-3.md"
    assert item.model == "fake/fake-model"
    report = out / "calidad-DEMO-3.md"
    assert report.exists()
    assert report.read_text(encoding="utf-8").strip()


# --- 2. Nada se escribe en Jira en simulación ------------------------------------------


def test_prepare_never_writes_jira_in_simulation(rt: Runtime, out: Path) -> None:
    """Criterio 2: ni el fake de Jira ni el de casos reciben escrituras en simulación."""
    prepare(_with_cases(rt), Options(), out)

    assert _tracker(rt).writes == []
    assert _tm(rt).publish_calls == 0
    assert _tm(rt).executions == []
    assert _tm(rt).cases[STORY] == CASES


# --- 3. Idempotencia ---------------------------------------------------------------------


def test_prepare_twice_reuses_ids_without_new_llm_calls(rt: Runtime, out: Path) -> None:
    """Criterio 3: la segunda vez mismos ids, sin llamadas nuevas al LLM y nota «ya preparada»."""
    first = prepare(_with_cases(rt), Options(), out)
    calls = len(_llm(rt).calls)
    assert calls > 0

    second = prepare(rt, Options(), out)

    assert [(i.name, i.id) for i in second] == [(i.name, i.id) for i in first]
    assert len(_llm(rt).calls) == calls
    for item in second:
        assert item.state == item.expected
        if item.kind != "quality":  # la de calidad conserva su nota del plan B
            assert item.note == "ya preparada", item.name


def test_prepare_redo_recreates_only_named_step(rt: Runtime, out: Path) -> None:
    """Criterio 3: `redo` rehace solo evolucion-en-revision; el resto conserva su id."""
    first = _by_name(prepare(rt, Options(), out))
    calls = len(_llm(rt).calls)

    second = _by_name(prepare(rt, Options(redo=frozenset({"evolucion-en-revision"})), out))

    assert second["evolucion-en-revision"].id != first["evolucion-en-revision"].id
    assert second["evolucion-en-revision"].state == "in_review"
    assert second["evolucion-en-revision"].note == ""
    for name in SIMULATION_NAMES:
        if name != "evolucion-en-revision":
            assert second[name].id == first[name].id, name
    assert len(_llm(rt).calls) > calls


def test_prepare_redoes_step_whose_id_no_longer_exists(rt: Runtime, out: Path) -> None:
    """Criterio 3: un id del manifiesto que ya no existe en el servidor se vuelve a preparar."""
    first = _by_name(prepare(rt, Options(), out))
    path = out / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    ghost = str(uuid4())
    data["items"]["evolucion-en-revision"]["id"] = ghost
    path.write_text(json.dumps(data), encoding="utf-8")

    second = _by_name(prepare(rt, Options(), out))

    redone = second["evolucion-en-revision"]
    assert redone.id not in (ghost, first["evolucion-en-revision"].id)
    assert redone.state == "in_review"
    assert redone.note != "ya preparada"
    assert second["necesidad-iterada"].id == first["necesidad-iterada"].id


def test_prepare_redoes_everything_with_new_runtime(tmp_path: Path, out: Path) -> None:
    """Criterio 3: con otra composición (servidor vacío) las conversaciones se rehacen."""
    first = _by_name(prepare(fake_runtime(tmp_path / "a"), Options(), out))
    second = _by_name(prepare(fake_runtime(tmp_path / "b"), Options(), out))

    for name in ("necesidad-iterada", "evolucion-simulada", "qa-directa-simulada"):
        assert second[name].id != first[name].id
        assert second[name].state == second[name].expected


@pytest.mark.parametrize("state", ["pending", "error", "failed", "skipped"])
def test_prepare_redoes_saved_step_in_unfinished_state(rt: Runtime, out: Path, state: str) -> None:
    """Criterio 3: una entrada guardada sin terminar (pending/error/failed/skipped) se rehace."""
    first = _by_name(prepare(rt, Options(), out))
    path = out / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"]["qa-directa-en-revision"]["state"] = state
    path.write_text(json.dumps(data), encoding="utf-8")

    second = _by_name(prepare(rt, Options(), out))

    assert second["qa-directa-en-revision"].id != first["qa-directa-en-revision"].id
    assert second["qa-directa-en-revision"].state == "in_review"


def test_prepare_redoes_quality_when_report_file_is_missing(rt: Runtime, out: Path) -> None:
    """Criterio 3: si falta calidad-DEMO-3.md, la calidad se vuelve a generar."""
    prepare(rt, Options(), out)
    (out / "calidad-DEMO-3.md").unlink()
    calls = len(_llm(rt).calls)

    item = _by_name(prepare(rt, Options(), out))["calidad"]

    assert item.state == "done"
    assert (out / "calidad-DEMO-3.md").exists()
    assert len(_llm(rt).calls) > calls


# --- 4. --only ---------------------------------------------------------------------------


def test_prepare_only_runs_selected_step_on_empty_manifest(rt: Runtime, out: Path) -> None:
    """Criterio 4: `only={"calidad"}` sin manifiesto solo prepara la calidad."""
    items = prepare(rt, Options(only=frozenset({"calidad"})), out)

    assert [i.name for i in items] == ["calidad"]
    assert items[0].state == "done"
    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert list(saved["items"]) == ["calidad"]


def test_prepare_only_keeps_other_manifest_entries(tmp_path: Path, rt: Runtime, out: Path) -> None:
    """Criterio 4: `only` + `redo` de calidad conserva intactas las demás entradas guardadas."""
    reference = fake_runtime(tmp_path / "ref")
    prepare(reference, Options(only=frozenset({"calidad"})), tmp_path / "ref-out")
    quality_calls = len(_llm(reference).calls)

    first = _by_name(prepare(rt, Options(), out))
    calls = len(_llm(rt).calls)
    options = Options(only=frozenset({"calidad"}), redo=frozenset({"calidad"}))
    second = _by_name(prepare(rt, options, out))

    assert list(second) == SIMULATION_NAMES
    assert len(_llm(rt).calls) - calls == quality_calls
    for name in SIMULATION_NAMES:
        assert second[name].id == first[name].id
    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert list(saved["items"]) == SIMULATION_NAMES
    assert saved["items"]["evolucion-simulada"]["id"] == first["evolucion-simulada"].id


# --- 5. Dependencias ---------------------------------------------------------------------


def test_prepare_skips_chained_qa_when_source_failed(rt: Runtime, out: Path) -> None:
    """Criterio 5: si evolucion-simulada falla, qa-encadenada-en-revision queda «skipped»."""
    llm = _llm(rt)

    def story(messages: list[Message]) -> UserStory:
        if any(EVOLVE_FEEDBACK in m.content for m in messages):
            raise ExternalServiceError("Fallo ficticio del modelo.", service="llm")
        return _story_citing_context(messages)

    llm.builders[UserStory] = story

    items = _by_name(prepare(rt, Options(), out))

    assert items["evolucion-simulada"].state != "simulated"
    chained = items["qa-encadenada-en-revision"]
    assert chained.state == "skipped"
    assert chained.note.startswith("Falta preparar antes")
    assert "evolucion-simulada" in chained.note
    assert chained.id is None and chained.handoff_id is None
    assert items["evolucion-en-revision"].state == "in_review"  # el resto sigue
    assert items["qa-directa-en-revision"].state == "in_review"


def test_prepare_skips_chained_qa_when_source_not_in_only(rt: Runtime, out: Path) -> None:
    """Criterio 5: con `only` del paso encadenado y sin su origen preparado, queda «skipped»."""
    items = prepare(rt, Options(only=frozenset({"qa-encadenada-en-revision"})), out)

    assert [i.name for i in items] == ["qa-encadenada-en-revision"]
    assert items[0].state == "skipped"
    assert items[0].note == "Falta preparar antes: evolucion-simulada."
    assert _llm(rt).calls == []


def test_prepare_skips_chained_qa_when_saved_source_has_other_state(rt: Runtime, out: Path) -> None:
    """Criterio 5: si el manifiesto guarda el origen en otro estado, el encadenado se salta."""
    out.mkdir(parents=True)
    source = Prepared(
        name="evolucion-simulada",
        kind="conversation",
        user="af-demo",
        id=str(uuid4()),
        state="in_review",
        expected="simulated",
    )
    manifest = {"version": 1, "items": {source.name: source.__dict__}}
    (out / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    items = _by_name(prepare(rt, Options(only=frozenset({"qa-encadenada-en-revision"})), out))

    assert items["qa-encadenada-en-revision"].state == "skipped"
    assert items["evolucion-simulada"].state == "in_review"  # se conserva tal cual


# --- 6. Modo de publicación --------------------------------------------------------------


def test_prepare_rejects_live_runtime_in_simulation(tmp_path: Path, out: Path) -> None:
    """Criterio 6: composición en `live` y preparación en simulación → DemoPrepareError."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    with pytest.raises(DemoPrepareError, match="JIRA_PUBLISH_MODE"):
        prepare(live, Options(), out, "simulation")

    assert not out.exists()
    assert _tracker(live).writes == []
    assert _llm(live).calls == []


def test_prepare_rejects_simulation_runtime_in_live(rt: Runtime, out: Path) -> None:
    """Criterio 6: composición en simulación y preparación en `live` → DemoPrepareError."""
    with pytest.raises(DemoPrepareError, match="live"):
        prepare(rt, Options(sandbox_live=True), out, "live")

    assert not out.exists()
    assert _llm(rt).calls == []


# --- 7. Sandbox en live con fakes ---------------------------------------------------------


def test_prepare_publishes_sandbox_steps_in_live_with_fakes(tmp_path: Path, out: Path) -> None:
    """Criterio 7: en `live` con fakes, HU y casos quedan published y el fake de Jira escribe."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    items = prepare(live, Options(sandbox_live=True), out, "live")

    assert [i.name for i in items] == SANDBOX_NAMES
    by_name = _by_name(items)
    assert by_name["sandbox-hu-publicada"].state == "published"
    assert by_name["sandbox-casos-publicados"].state == "published"
    assert by_name["sandbox-casos-publicados"].handoff_id
    assert ("update_story", {"key": STORY}) in _tracker(live).writes
    assert _tm(live).publish_calls == 1
    assert _tm(live).cases[STORY]  # los casos ya existen para el registro de la ejecución


def test_prepare_sandbox_twice_does_not_publish_again(tmp_path: Path, out: Path) -> None:
    """Criterio 3 y 7: repetir el sandbox no vuelve a escribir en Jira."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    first = prepare(live, Options(sandbox_live=True), out, "live")
    writes, publishes = list(_tracker(live).writes), _tm(live).publish_calls

    second = prepare(live, Options(sandbox_live=True), out, "live")

    assert [i.id for i in second] == [i.id for i in first]
    assert _tracker(live).writes == writes
    assert _tm(live).publish_calls == publishes


def test_prepare_live_keeps_simulation_manifest_entries(tmp_path: Path, out: Path) -> None:
    """Criterio 3 y 7: preparar el sandbox en la misma carpeta no borra la simulación."""
    prepare(fake_runtime(tmp_path / "sim"), Options(), out)
    live = fake_runtime(tmp_path / "live", publish_mode="live")

    prepare(live, Options(sandbox_live=True), out, "live")

    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert set(SIMULATION_NAMES) <= set(saved["items"])


# --- 8. Línea de órdenes -----------------------------------------------------------------


def test_main_fake_returns_zero_with_skipped_execution(
    tmp_path: Path, no_tempdir_leak: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 8: `--fake` termina en 0 aunque la ejecución quede «skipped» (sin casos)."""
    target = tmp_path / "cli"

    assert main(["--fake", "--out", str(target)]) == 0

    captured = capsys.readouterr()
    assert "ejecucion-en-revision" in captured.out
    assert str(target) in captured.out
    assert (target / MANIFEST).exists() and (target / SUMMARY).exists()
    saved = json.loads((target / MANIFEST).read_text(encoding="utf-8"))
    assert saved["items"]["ejecucion-en-revision"]["state"] == "skipped"


def test_main_returns_one_when_a_step_misses_its_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 8: si un paso no llega a su estado (y no está «skipped»), devuelve 1."""
    failing = fake_runtime(tmp_path / "rt")
    _llm(failing).error = ExternalServiceError("Fallo ficticio del modelo.", service="llm")
    monkeypatch.setattr(demo_prepare, "build", lambda _a, _m: (failing, tmp_path / "cli"))

    assert main(["--fake"]) == 1
    assert "⚠️" in capsys.readouterr().out


def test_main_sandbox_live_without_confirmation_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 8: `--sandbox-live` sin `--confirmo-escritura-AFQP` → 2 y aviso en stderr."""

    def no_build(*_args: object) -> None:
        raise AssertionError("no debe construir la composición")

    monkeypatch.setattr(demo_prepare, "build", no_build)

    assert main(["--fake", "--sandbox-live"]) == 2
    assert "--confirmo-escritura-AFQP" in capsys.readouterr().err


def test_main_real_sandbox_outside_afqp_returns_two_without_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 8: `--real --sandbox-live` con `--project DEMO` → 2 sin la composición real."""

    def no_runtime() -> None:
        raise AssertionError("no debe construir la composición real")

    monkeypatch.setattr(api.runtime, "build_runtime", no_runtime)
    _unset_publish_mode(monkeypatch)

    argv = ["--real", "--sandbox-live", "--confirmo-escritura-AFQP", "--project", "DEMO"]
    assert main(argv) == 2

    assert "AFQP" in capsys.readouterr().err
    assert "JIRA_PUBLISH_MODE" not in os.environ


def test_options_reject_real_sandbox_story_outside_afqp() -> None:
    """Criterio 8: `--real --sandbox-live` solo publica HU del proyecto AFQP (no DEMO-3)."""
    args = parse_args(["--real", "--sandbox-live", "--confirmo-escritura-AFQP"])

    with pytest.raises(DemoPrepareError):
        options_from(args)


def test_options_accept_real_sandbox_on_afqp_story() -> None:
    """Criterio 8: `--real --sandbox-live` con confirmación, proyecto y HU de AFQP se acepta."""
    args = parse_args(
        ["--real", "--sandbox-live", "--confirmo-escritura-AFQP", "--story", "AFQP-1"]
    )

    options = options_from(args)

    assert options.project == "AFQP"
    assert options.sandbox_live is True
    assert options.story == "AFQP-1"


def test_options_map_cli_flags() -> None:
    """Criterio 3 y 4: `--rehacer` y `--only` llegan como conjuntos a `Options`."""
    args = parse_args(
        ["--fake", "--only", "calidad", "--only", "necesidad-iterada", "--rehacer", "calidad"]
    )

    options = options_from(args)

    assert options.only == frozenset({"calidad", "necesidad-iterada"})
    assert options.redo == frozenset({"calidad"})
    assert options.project == "DEMO"
    assert options.sandbox_live is False


@pytest.mark.parametrize("argv", [[], ["--fake", "--real"], ["--out", "x"]])
def test_parse_args_requires_exactly_one_target(argv: list[str]) -> None:
    """Criterio 8: sin `--fake` ni `--real` (o con los dos) argparse sale con SystemExit."""
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 2


# --- 9. Resumen y manifiesto -------------------------------------------------------------


def test_summary_has_one_row_per_step_without_story_content(rt: Runtime, out: Path) -> None:
    """Criterio 9: preparadas.md lleva todas las filas y nada del contenido de las HU."""
    items = prepare(_with_cases(rt), Options(), out)
    text = (out / SUMMARY).read_text(encoding="utf-8")

    rows = [line for line in text.splitlines() if line.startswith("| ") and "`" in line]
    assert len(rows) == len(items) == len(SIMULATION_STEPS)
    for item in items:
        assert f"| {item.name} | {item.user} | `{item.id}` |" in text
    assert "modo `simulation`" in text
    for secret_text in (
        dataset.renewal_story().title,
        dataset.renewal_story().description,
        NEED_TEXT,
        NEED_FEEDBACK,
        EVOLVE_FEEDBACK,
    ):
        assert secret_text not in text


def test_manifest_round_trips_prepared_items(rt: Runtime, out: Path) -> None:
    """Criterio 9: preparadas.json se relee y reproduce los mismos `Prepared`."""
    items = prepare(rt, Options(), out)

    raw = json.loads((out / MANIFEST).read_text(encoding="utf-8"))

    assert raw["version"] == 1
    assert [Prepared(**data) for data in raw["items"].values()] == items
    text = (out / MANIFEST).read_text(encoding="utf-8")
    assert NEED_TEXT not in text and dataset.renewal_story().title not in text


@pytest.mark.parametrize(
    "content",
    [
        "{esto no es json",
        json.dumps({"items": {"calidad": {"nombre": "desconocido"}}}),
        json.dumps({"items": {"calidad": ["no", "es", "un", "objeto"]}}),
    ],
)
def test_prepare_rejects_damaged_manifest(rt: Runtime, out: Path, content: str) -> None:
    """Criterio 9: un manifiesto dañado → DemoPrepareError y no se toca nada."""
    out.mkdir(parents=True)
    (out / MANIFEST).write_text(content, encoding="utf-8")

    with pytest.raises(DemoPrepareError, match="dañado"):
        prepare(rt, Options(), out)

    assert (out / MANIFEST).read_text(encoding="utf-8") == content
    assert _llm(rt).calls == []


@pytest.mark.parametrize("content", ["[]", json.dumps({"items": []}), "null"])
def test_prepare_rejects_manifest_with_wrong_shape(rt: Runtime, out: Path, content: str) -> None:
    """Criterio 9: un manifiesto con JSON válido pero forma incorrecta también está dañado."""
    out.mkdir(parents=True)
    (out / MANIFEST).write_text(content, encoding="utf-8")

    with pytest.raises(DemoPrepareError):
        prepare(rt, Options(), out)


def test_render_summary_escapes_pipes_and_newlines_in_note() -> None:
    """Criterio 9: la nota con `|` y saltos de línea no rompe la fila de la tabla."""
    item = Prepared(
        name="calidad",
        kind="quality",
        user="af-demo",
        id="calidad-DEMO-3.md",
        state="failed",
        expected="done",
        note="Fallo ficticio | columna\nsegunda línea\r\n  tercera",
    )

    text = render_summary([item], "simulation")

    rows = [line for line in text.splitlines() if line.startswith("| calidad ")]
    assert len(rows) == 1
    assert "Fallo ficticio \\| columna segunda línea tercera" in rows[0]
    assert rows[0].replace("\\|", "").count("|") == 9
    assert "⚠️ failed" in rows[0]


def test_render_summary_uses_dashes_for_missing_values() -> None:
    """Criterio 9: sin id, modelo, segundos ni nota se pinta «—»."""
    item = Prepared(name="ejecucion-en-revision", kind="execution", user="qa-demo")

    row = next(line for line in render_summary([item], "live").splitlines() if "ejecucion" in line)

    assert row == ("| ejecucion-en-revision | qa-demo | — | ⚠️ pending | in_review | — | — | — |")


# --- 10. build() --------------------------------------------------------------------------


def test_build_fake_returns_fake_runtime_and_temp_out(no_tempdir_leak: Path) -> None:
    """Criterio 10: con `--fake` y sin `--out`, fakes en el modo pedido y carpeta temporal."""
    rt, out_dir = build(parse_args(["--fake"]), "simulation")

    assert isinstance(rt, Runtime)
    container = rt.workspace_factory().container
    assert container.publish_mode == "simulation"
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    assert out_dir == no_tempdir_leak / "demo"


def test_build_fake_honours_out_and_live_mode(tmp_path: Path, no_tempdir_leak: Path) -> None:
    """Criterio 10: `--out` se respeta y el modo `live` llega a la composición de fakes."""
    rt, out_dir = build(parse_args(["--fake", "--out", str(tmp_path / "x")]), "live")

    assert rt.workspace_factory().container.publish_mode == "live"
    assert out_dir == tmp_path / "x"


@pytest.mark.parametrize("mode", ["simulation", "live"])
def test_build_real_forces_publish_mode_env(
    monkeypatch: pytest.MonkeyPatch, mode: demo_prepare.Mode
) -> None:
    """Criterio 10: con `--real` fija JIRA_PUBLISH_MODE al modo pedido antes de componer."""
    seen: dict[str, str | None] = {}
    sentinel = object()

    def fake_build_runtime() -> object:
        seen["mode"] = os.environ.get("JIRA_PUBLISH_MODE")
        return sentinel

    other = "live" if mode == "simulation" else "simulation"
    monkeypatch.setenv("JIRA_PUBLISH_MODE", other)
    monkeypatch.setattr(api.runtime, "build_runtime", fake_build_runtime)

    rt, out_dir = build(parse_args(["--real"]), mode)

    assert rt is sentinel
    assert seen["mode"] == mode
    assert out_dir == demo_prepare.DEFAULT_OUT


def test_build_real_without_env_sets_mode_and_custom_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Criterio 10: sin JIRA_PUBLISH_MODE previo también lo fija; `--out` manda sobre docs/demo."""
    _unset_publish_mode(monkeypatch)
    monkeypatch.setattr(api.runtime, "build_runtime", lambda: "composicion-ficticia")

    rt, out_dir = build(parse_args(["--real", "--out", str(tmp_path / "y")]), "simulation")

    assert rt == "composicion-ficticia"
    assert out_dir == tmp_path / "y"
    assert os.environ["JIRA_PUBLISH_MODE"] == "simulation"


# --- Correcciones tras test-writer ---------------------------------------------------------------


def test_prepare_rejects_unknown_step_names(rt: Runtime, out: Path) -> None:
    """Un `--only` o `--rehacer` con un nombre que no existe avisa en lugar de ignorarse."""
    with pytest.raises(DemoPrepareError, match="desconocidos"):
        prepare(rt, Options(only=frozenset({"no-existe"})), out)
    with pytest.raises(DemoPrepareError, match="desconocidos"):
        prepare(rt, Options(redo=frozenset({"sandbox-hu-publicada"})), out)


def test_prepare_redoes_quality_with_tampered_id(rt: Runtime, out: Path) -> None:
    """El id del informe sale del manifiesto: uno manipulado no se toma como ruta válida."""
    prepare(rt, Options(only=frozenset({"calidad"})), out)
    manifest = json.loads((out / "preparadas.json").read_text(encoding="utf-8"))
    manifest["items"]["calidad"]["id"] = "../preparadas.json"
    (out / "preparadas.json").write_text(json.dumps(manifest), encoding="utf-8")

    (item,) = [i for i in prepare(rt, Options(only=frozenset({"calidad"})), out)]

    assert item.id == "calidad-DEMO-3.md"
    assert "ya preparada" not in item.note


def test_prepare_marks_reused_quality_as_already_prepared(rt: Runtime, out: Path) -> None:
    """Al reutilizar el informe de calidad, el resumen lo distingue de uno recién generado."""
    prepare(rt, Options(only=frozenset({"calidad"})), out)

    (item,) = [i for i in prepare(rt, Options(only=frozenset({"calidad"})), out)]

    assert item.note.startswith("ya preparada")


# --- Endurecimiento tras security-reviewer ------------------------------------------------------


def test_sandbox_plan_rejects_operations_outside_project(tmp_path: Path) -> None:
    """En `live`, un vínculo de impacto hacia otro proyecto para la aprobación (no se escribe)."""
    from eval.demo_prepare import _check_sandbox_plan, _Context

    ctx = _Context(rt=None, options=Options(project="AFQP", sandbox_live=True), out_dir=tmp_path)
    _check_sandbox_plan(
        ctx,
        [
            {"op": "update_story", "project": "AFQP", "key": "AFQP-1"},
            {"op": "link", "from": "AFQP-1", "to": "AFQP-2", "type": "relates to"},
        ],
    )
    for plan in (
        [{"op": "link", "from": "AFQP-1", "to": "OTRO-2", "type": "relates to"}],
        [{"op": "update_story", "project": "OTRO", "key": "AFQP-1"}],
    ):
        with pytest.raises(DemoPrepareError, match="fuera del proyecto"):
            _check_sandbox_plan(ctx, plan)


@pytest.mark.parametrize(
    "options",
    [
        Options(sandbox_live=False),
        Options(sandbox_live=True, project="DEMO", story="OTRO-1"),
        Options(sandbox_live=True, project="DEMO", qa_story="OTRO-1"),
    ],
    ids=["sin-sandbox", "story-ajena", "qa-story-ajena"],
)
def test_prepare_live_rechecks_options(tmp_path: Path, out: Path, options: Options) -> None:
    """Defensa en profundidad: `prepare` en `live` repite las comprobaciones de la CLI."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    with pytest.raises(DemoPrepareError, match="live"):
        prepare(live, options, out, "live")

    assert _tracker(live).writes == []


def test_quality_rejects_key_that_is_not_an_issue_key(rt: Runtime, out: Path) -> None:
    """La clave es también el nombre del informe: una ruta no se escribe fuera de la carpeta."""
    (item,) = prepare(rt, Options(story="../fuera", only=frozenset({"calidad"})), out)

    assert item.state == "failed"
    assert "no válida" in item.note
    assert not (out.parent / "fuera.md").exists()
    assert [p.name for p in out.iterdir() if p.name.startswith("calidad")] == []


@pytest.mark.parametrize("value", ["afqp-3", "OTRO-2", "AFQP-x"])
def test_sandbox_plan_fails_closed_on_non_canonical_keys(tmp_path: Path, value: str) -> None:
    """Un valor que no es una clave canónica del proyecto también para la aprobación."""
    from eval.demo_prepare import _check_sandbox_plan, _Context

    ctx = _Context(rt=None, options=Options(project="AFQP", sandbox_live=True), out_dir=tmp_path)

    with pytest.raises(DemoPrepareError):
        _check_sandbox_plan(ctx, [{"op": "link", "from": "AFQP-1", "to": value}])
    _check_sandbox_plan(ctx, [{"op": "create_story", "project": "AFQP", "epic": ""}])


def test_prepare_rejects_manifest_with_unknown_kind(rt: Runtime, out: Path) -> None:
    """Un `kind` desconocido en el manifiesto se trata como manifiesto dañado."""
    out.mkdir(parents=True, exist_ok=True)
    entry = {"name": "calidad", "kind": "otra-cosa", "user": "af-demo"}
    (out / "preparadas.json").write_text(
        json.dumps({"version": 1, "items": {"calidad": entry}}), encoding="utf-8"
    )

    with pytest.raises(DemoPrepareError, match="dañado"):
        prepare(rt, Options(), out)


def test_render_summary_escapes_every_cell() -> None:
    """Ningún campo del manifiesto (id, modelo, estado…) puede romper la tabla."""
    from eval.demo_prepare import Prepared, render_summary

    item = Prepared(
        name="a|b", kind="conversation", user="u", id="x`|y", state="in|review", model="m|1"
    )

    row = render_summary([item], "simulation").splitlines()[-1]

    assert row.count(" | ") == 7  # 8 celdas
    assert "`x'\\|y`" in row and "a\\|b" in row and "m\\|1" in row
