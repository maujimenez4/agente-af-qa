"""Preparación de las conversaciones de la demo (T-36, parte 1): `eval/demo_prepare.py`.

Todo sobre `fake_runtime`: sin `.env`, sin red, sin Jira ni LLM reales. Datos 100 % ficticios
(proyecto DEMO del dataset sintético y claves DEMO-5xx; AFQP solo como texto de las opciones). Se
llama a `prepare` directamente; la línea de órdenes solo se prueba con `--fake` o con la
composición real sustituida.
"""

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

import api.runtime
from adapters.base import IssueSummary, User
from adapters.errors import AuthenticationError, ExternalServiceError
from api import service
from api.errors import ApiError
from api.runtime import Runtime
from eval import demo_prepare
from eval.demo_prepare import (
    EVOLVE_FEEDBACK,
    ITERATE_FEEDBACK,
    MANIFEST,
    SANDBOX_STEPS,
    SIMULATION_STEPS,
    SUMMARY,
    DemoPrepareError,
    Options,
    Prepared,
    Step,
    _check_sandbox_plan,
    _Context,
    build,
    main,
    options_from,
    parse_args,
    prepare,
    render_summary,
)
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.test_management import FakeTestManagement

STORY = "DEMO-3"
AF = User(username="af-demo", role="functional")
QA = User(username="qa-demo", role="qa")
CASES = [
    IssueSummary(
        key="DEMO-501", summary="[CP-01] Caso ficticio uno", issue_type="Subtarea", status="Hecho"
    ),
    IssueSummary(
        key="DEMO-502", summary="[CP-02] Caso ficticio dos", issue_type="Subtarea", status="Hecho"
    ),
]
SIMULATION_NAMES = [s.name for s in SIMULATION_STEPS]
SANDBOX_NAMES = [s.name for s in SANDBOX_STEPS]


def _fake_options(**overrides: Any) -> Options:
    """Las opciones de la demo real apuntan a AFQP; con los fakes, a DEMO-3."""
    values: dict[str, Any] = {
        "project": "DEMO",
        "story": STORY,
        "qa_story": STORY,
        "quality_story": STORY,
    }
    return Options(**(values | overrides))


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


def _unset_publish_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quita JIRA_PUBLISH_MODE de forma que monkeypatch lo restaure al terminar."""
    monkeypatch.setenv("JIRA_PUBLISH_MODE", "simulation")
    monkeypatch.delenv("JIRA_PUBLISH_MODE")


def _edit_manifest(out: Path, name: str, **fields: object) -> None:
    path = out / MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    data["items"][name].update(fields)
    path.write_text(json.dumps(data), encoding="utf-8")


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
    """Los 3 pasos de SIMULATION_STEPS, en orden, cada uno en su estado esperado."""
    items = prepare(rt, _fake_options(), out)

    assert [i.name for i in items] == SIMULATION_NAMES
    assert SIMULATION_NAMES == ["qa-suite-en-revision", "evolucion-iterada", "calidad"]
    for item in items:
        assert item.state == item.expected, (item.name, item.state, item.note)
        assert item.id
        assert item.model == "fake/fake-model"
        assert item.seconds is not None and item.seconds >= 0


def test_prepare_leaves_qa_suite_in_review_for_qa_user(rt: Runtime, out: Path) -> None:
    """La suite de QA queda en revisión, de `qa-demo`, con la cobertura en la nota (solo IDs)."""
    item = _by_name(prepare(rt, _fake_options(), out))["qa-suite-en-revision"]

    assert item.user == "qa-demo"
    conv = service.conversation_out(rt, rt.workspace_factory(), QA, item.id or "")
    assert conv.state == "in_review"
    assert conv.mode == "qa"
    assert conv.review is not None and conv.review.uncovered is not None
    assert item.note == "Cobertura completa"


def test_prepare_refuses_qa_suite_of_story_with_published_cases(rt: Runtime, out: Path) -> None:
    """PA-450: una HU con casos en Jira (como AFQP-27) no recibe otra suite; el resto sigue."""
    _tm(rt).cases[STORY] = list(CASES)

    items = _by_name(prepare(rt, _fake_options(), out))

    qa = items["qa-suite-en-revision"]
    assert qa.state == "failed"
    assert qa.id is None
    assert "2 casos publicados" in qa.note and STORY in qa.note
    assert not any(c["task"] == "generate_tests" for c in _llm(rt).calls)
    assert items["evolucion-iterada"].state == "in_review"
    assert items["calidad"].state == "done"


def test_prepare_refuses_qa_suite_when_cases_cannot_be_checked(
    rt: Runtime, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-450, falla cerrado: si no se puede consultar Jira, no se prepara la suite."""

    def broken(_key: str) -> list[IssueSummary]:
        raise ExternalServiceError("Jira ficticio caído.", service="jira")

    monkeypatch.setattr(_tm(rt), "list_cases", broken)

    (item,) = prepare(rt, _fake_options(only=frozenset({"qa-suite-en-revision"})), out)

    assert item.state == "failed"
    assert item.id is None
    assert "No se pudo comprobar" in item.note
    assert _llm(rt).calls == []


def test_prepare_iterates_evolution_once(rt: Runtime, out: Path) -> None:
    """La evolución queda en revisión con 2 versiones y las dos peticiones aplicadas."""
    item = _by_name(prepare(rt, _fake_options(), out))["evolucion-iterada"]

    assert item.user == "af-demo"
    conv = service.conversation_out(rt, rt.workspace_factory(), AF, item.id or "")
    assert conv.state == "in_review"
    assert conv.mode == "functional"
    assert len(conv.versions) == 2
    assert EVOLVE_FEEDBACK in conv.feedback
    assert ITERATE_FEEDBACK in conv.feedback


def test_prepare_stores_quality_review_like_the_api(rt: Runtime, out: Path) -> None:
    """La revisión de calidad se guarda en el almacén de la API: sale en la lista de af-demo."""
    item = _by_name(prepare(rt, _fake_options(), out))["calidad"]

    review = rt.quality.get(item.id or "")
    assert review is not None
    assert review.state == "done"
    assert review.username == "af-demo"
    assert review.issue_key == STORY
    assert review.report is not None
    assert [r.id for r in rt.quality.list_for("af-demo")] == [item.id]
    assert not list(out.glob("calidad-*.md"))  # el informe ya no se escribe en docs/demo


def test_prepare_marks_quality_review_as_error_when_llm_fails(rt: Runtime, out: Path) -> None:
    """Como la API: si el modelo falla, la revisión queda en error con su mensaje."""
    _llm(rt).error = ExternalServiceError("Fallo ficticio del modelo.", service="llm")

    (item,) = prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    assert item.state == "failed"
    review = rt.quality.get(item.id or "")
    assert review is not None and review.state == "error"
    assert review.error_message and item.note == review.error_message[:200]


# --- 2. Nada se escribe en Jira en simulación ------------------------------------------


def test_prepare_never_writes_jira_in_simulation(rt: Runtime, out: Path) -> None:
    """Ni el fake de Jira ni el de casos reciben escrituras en simulación."""
    prepare(rt, _fake_options(), out)

    assert _tracker(rt).writes == []
    assert _tm(rt).publish_calls == 0
    assert _tm(rt).executions == []


# --- 3. Idempotencia ---------------------------------------------------------------------


def test_prepare_twice_reuses_ids_without_new_llm_calls(rt: Runtime, out: Path) -> None:
    """La segunda vez, mismos ids, sin llamadas nuevas al LLM y nota «ya preparada»."""
    first = prepare(rt, _fake_options(), out)
    calls = len(_llm(rt).calls)
    assert calls > 0

    second = prepare(rt, _fake_options(), out)

    assert [(i.name, i.id) for i in second] == [(i.name, i.id) for i in first]
    assert len(_llm(rt).calls) == calls
    for item in second:
        assert item.state == item.expected
        assert item.note.startswith("ya preparada"), item.name


def test_prepare_redo_recreates_only_named_step(rt: Runtime, out: Path) -> None:
    """`redo` rehace solo evolucion-iterada; el resto conserva su id."""
    first = _by_name(prepare(rt, _fake_options(), out))
    calls = len(_llm(rt).calls)

    second = _by_name(prepare(rt, _fake_options(redo=frozenset({"evolucion-iterada"})), out))

    assert second["evolucion-iterada"].id != first["evolucion-iterada"].id
    assert second["evolucion-iterada"].state == "in_review"
    assert second["evolucion-iterada"].note == ""
    for name in SIMULATION_NAMES:
        if name != "evolucion-iterada":
            assert second[name].id == first[name].id, name
    assert len(_llm(rt).calls) > calls


def test_prepare_redoes_step_whose_id_no_longer_exists(rt: Runtime, out: Path) -> None:
    """Un id del manifiesto que ya no existe en el servidor se vuelve a preparar."""
    first = _by_name(prepare(rt, _fake_options(), out))
    ghost = str(uuid4())
    _edit_manifest(out, "evolucion-iterada", id=ghost)

    second = _by_name(prepare(rt, _fake_options(), out))

    redone = second["evolucion-iterada"]
    assert redone.id not in (ghost, first["evolucion-iterada"].id)
    assert redone.state == "in_review"
    assert not redone.note.startswith("ya preparada")
    assert second["qa-suite-en-revision"].id == first["qa-suite-en-revision"].id


def test_prepare_redoes_everything_with_new_runtime(tmp_path: Path, out: Path) -> None:
    """Con otra composición (servidor vacío) las conversaciones y la revisión se rehacen."""
    first = _by_name(prepare(fake_runtime(tmp_path / "a"), _fake_options(), out))
    second = _by_name(prepare(fake_runtime(tmp_path / "b"), _fake_options(), out))

    for name in SIMULATION_NAMES:
        assert second[name].id != first[name].id, name
        assert second[name].state == second[name].expected


@pytest.mark.parametrize("state", ["pending", "error", "failed", "skipped"])
def test_prepare_redoes_saved_step_in_unfinished_state(rt: Runtime, out: Path, state: str) -> None:
    """Una entrada guardada sin terminar (pending/error/failed/skipped) se rehace."""
    first = _by_name(prepare(rt, _fake_options(), out))
    _edit_manifest(out, "qa-suite-en-revision", state=state)

    second = _by_name(prepare(rt, _fake_options(), out))

    assert second["qa-suite-en-revision"].id != first["qa-suite-en-revision"].id
    assert second["qa-suite-en-revision"].state == "in_review"


@pytest.mark.parametrize("tampered", ["../preparadas.json", "no-es-un-uuid", str(uuid4())])
def test_prepare_redoes_quality_with_tampered_or_missing_id(
    rt: Runtime, out: Path, tampered: str
) -> None:
    """Un id de revisión manipulado o que ya no existe no se toma por válido: se rehace."""
    prepare(rt, _fake_options(only=frozenset({"calidad"})), out)
    _edit_manifest(out, "calidad", id=tampered)

    (item,) = prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    assert item.id != tampered
    assert item.state == "done"
    assert not item.note.startswith("ya preparada")


def test_prepare_redoes_quality_review_of_another_user(rt: Runtime, out: Path) -> None:
    """Una revisión del manifiesto que es de otra persona no cuenta como preparada."""
    prepare(rt, _fake_options(only=frozenset({"calidad"})), out)
    other = prepare(
        rt,
        _fake_options(only=frozenset({"calidad"}), functional_user="otra-af"),
        out.parent / "otra",
    )[0]
    _edit_manifest(out, "calidad", id=other.id)

    (item,) = prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    assert item.id != other.id
    assert rt.quality.get(item.id or "").username == "af-demo"  # type: ignore[union-attr]


def test_prepare_marks_reused_quality_as_already_prepared(rt: Runtime, out: Path) -> None:
    """Al reutilizar la revisión de calidad, el resumen la distingue de una recién generada."""
    prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    (item,) = prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    assert item.note.startswith("ya preparada")


# --- 4. --only ---------------------------------------------------------------------------


def test_prepare_only_runs_selected_step_on_empty_manifest(rt: Runtime, out: Path) -> None:
    """`only={"calidad"}` sin manifiesto solo prepara la calidad."""
    items = prepare(rt, _fake_options(only=frozenset({"calidad"})), out)

    assert [i.name for i in items] == ["calidad"]
    assert items[0].state == "done"
    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert list(saved["items"]) == ["calidad"]


def test_prepare_only_keeps_other_manifest_entries(rt: Runtime, out: Path) -> None:
    """`only` + `redo` de calidad conserva intactas las demás entradas guardadas."""
    first = _by_name(prepare(rt, _fake_options(), out))
    calls = len(_llm(rt).calls)
    options = _fake_options(only=frozenset({"calidad"}), redo=frozenset({"calidad"}))

    second = _by_name(prepare(rt, options, out))

    assert list(second) == SIMULATION_NAMES
    assert [c["task"] for c in _llm(rt).calls[calls:]] and all(
        c["task"] != "generate_tests" for c in _llm(rt).calls[calls:]
    )
    assert second["calidad"].id != first["calidad"].id
    for name in ("qa-suite-en-revision", "evolucion-iterada"):
        assert second[name].id == first[name].id
    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert list(saved["items"]) == SIMULATION_NAMES


# --- 5. Modo de publicación --------------------------------------------------------------


def test_prepare_rejects_live_runtime_in_simulation(tmp_path: Path, out: Path) -> None:
    """Composición en `live` y preparación en simulación → DemoPrepareError, sin tocar nada."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    with pytest.raises(DemoPrepareError, match="JIRA_PUBLISH_MODE"):
        prepare(live, _fake_options(), out, "simulation")

    assert not out.exists()
    assert _tracker(live).writes == []
    assert _llm(live).calls == []


def test_prepare_rejects_simulation_runtime_in_live(rt: Runtime, out: Path) -> None:
    """Composición en simulación y preparación en `live` → DemoPrepareError."""
    with pytest.raises(DemoPrepareError, match="live"):
        prepare(rt, _fake_options(sandbox_live=True), out, "live")

    assert not out.exists()
    assert _llm(rt).calls == []


# --- 6. Sandbox en live con fakes ---------------------------------------------------------


def test_prepare_publishes_sandbox_steps_in_live_with_fakes(tmp_path: Path, out: Path) -> None:
    """En `live` con fakes, HU y casos quedan published y el fake de Jira escribe."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    items = prepare(live, _fake_options(sandbox_live=True), out, "live")

    assert [i.name for i in items] == SANDBOX_NAMES
    by_name = _by_name(items)
    assert by_name["sandbox-hu-publicada"].state == "published"
    assert by_name["sandbox-casos-publicados"].state == "published"
    assert ("update_story", {"key": STORY}) in _tracker(live).writes
    assert _tm(live).publish_calls == 1
    assert _tm(live).cases[STORY]


def test_prepare_sandbox_refuses_cases_for_story_with_cases(tmp_path: Path, out: Path) -> None:
    """PA-450 también en `live`: con casos ya publicados no se publica otra suite."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    _tm(live).cases[STORY] = list(CASES)

    items = _by_name(prepare(live, _fake_options(sandbox_live=True), out, "live"))

    assert items["sandbox-casos-publicados"].state == "failed"
    assert _tm(live).publish_calls == 0
    assert _tm(live).cases[STORY] == CASES


def test_prepare_sandbox_twice_does_not_publish_again(tmp_path: Path, out: Path) -> None:
    """Repetir el sandbox no vuelve a escribir en Jira."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    first = prepare(live, _fake_options(sandbox_live=True), out, "live")
    writes, publishes = list(_tracker(live).writes), _tm(live).publish_calls

    second = prepare(live, _fake_options(sandbox_live=True), out, "live")

    assert [i.id for i in second] == [i.id for i in first]
    assert _tracker(live).writes == writes
    assert _tm(live).publish_calls == publishes


def test_prepare_live_keeps_simulation_manifest_entries(tmp_path: Path, out: Path) -> None:
    """Preparar el sandbox en la misma carpeta no borra la simulación."""
    prepare(fake_runtime(tmp_path / "sim"), _fake_options(), out)
    live = fake_runtime(tmp_path / "live", publish_mode="live")

    prepare(live, _fake_options(sandbox_live=True), out, "live")

    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert set(SIMULATION_NAMES) <= set(saved["items"])


def test_sandbox_plan_rejects_operations_outside_project(tmp_path: Path) -> None:
    """En `live`, un vínculo de impacto hacia otro proyecto para la aprobación (no se escribe)."""
    ctx = _Context(rt=None, options=Options(project="AFQP", sandbox_live=True), out_dir=tmp_path)
    _check_sandbox_plan(
        ctx,
        [
            {"op": "update_story", "project": "AFQP", "key": "AFQP-1"},
            {"op": "link", "from": "AFQP-1", "to": "AFQP-2", "type": "relates to"},
            {"op": "publish_suite", "project": "AFQP", "story": "AFQP-1", "cases": "3"},
        ],
    )
    for plan in (
        [{"op": "link", "from": "AFQP-1", "to": "OTRO-2", "type": "relates to"}],
        [{"op": "update_story", "project": "OTRO", "key": "AFQP-1"}],
        [{"op": "publish_suite", "project": "AFQP", "story": "OTRO-1", "cases": "3"}],
    ):
        with pytest.raises(DemoPrepareError, match="fuera del proyecto"):
            _check_sandbox_plan(ctx, plan)


@pytest.mark.parametrize("value", ["afqp-3", "OTRO-2", "AFQP-x"])
def test_sandbox_plan_fails_closed_on_non_canonical_keys(tmp_path: Path, value: str) -> None:
    """Un valor que no es una clave canónica del proyecto también para la aprobación."""
    ctx = _Context(rt=None, options=Options(project="AFQP", sandbox_live=True), out_dir=tmp_path)

    with pytest.raises(DemoPrepareError):
        _check_sandbox_plan(ctx, [{"op": "link", "from": "AFQP-1", "to": value}])
    _check_sandbox_plan(ctx, [{"op": "create_story", "project": "AFQP", "epic": ""}])


@pytest.mark.parametrize(
    "options",
    [
        _fake_options(sandbox_live=False),
        _fake_options(sandbox_live=True, story="OTRO-1"),
        _fake_options(sandbox_live=True, qa_story="OTRO-1"),
        _fake_options(sandbox_live=True, quality_story="OTRO-1"),
    ],
    ids=["sin-sandbox", "story-ajena", "qa-story-ajena", "quality-story-ajena"],
)
def test_prepare_live_rechecks_options(tmp_path: Path, out: Path, options: Options) -> None:
    """Defensa en profundidad: `prepare` en `live` repite las comprobaciones de la CLI."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")

    with pytest.raises(DemoPrepareError, match="live"):
        prepare(live, options, out, "live")

    assert _tracker(live).writes == []


# --- 7. Línea de órdenes -----------------------------------------------------------------


def test_main_fake_returns_zero(
    tmp_path: Path, no_tempdir_leak: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--fake` prepara los tres pasos sobre los fakes y termina en 0."""
    target = tmp_path / "cli"

    assert main(["--fake", "--out", str(target)]) == 0

    captured = capsys.readouterr()
    for name in SIMULATION_NAMES:
        assert name in captured.out
    assert str(target) in captured.out
    assert (target / MANIFEST).exists() and (target / SUMMARY).exists()


def test_main_returns_one_when_a_step_misses_its_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Si un paso no llega a su estado, devuelve 1 y lo marca con ⚠️."""
    failing = fake_runtime(tmp_path / "rt")
    _llm(failing).error = ExternalServiceError("Fallo ficticio del modelo.", service="llm")
    monkeypatch.setattr(demo_prepare, "build", lambda _a, _m: (failing, tmp_path / "cli"))

    assert main(["--fake"]) == 1
    assert "⚠️" in capsys.readouterr().out


def test_main_sandbox_live_without_confirmation_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--sandbox-live` sin `--confirmo-escritura-AFQP` → 2 y aviso en stderr."""

    def no_build(*_args: object) -> None:
        raise AssertionError("no debe construir la composición")

    monkeypatch.setattr(demo_prepare, "build", no_build)

    assert main(["--fake", "--sandbox-live"]) == 2
    assert "--confirmo-escritura-AFQP" in capsys.readouterr().err


def test_main_real_sandbox_outside_afqp_returns_two_without_runtime(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--real --sandbox-live` con `--project DEMO` → 2 sin la composición real."""

    def no_runtime() -> None:
        raise AssertionError("no debe construir la composición real")

    monkeypatch.setattr(api.runtime, "build_runtime", no_runtime)
    _unset_publish_mode(monkeypatch)

    argv = ["--real", "--sandbox-live", "--confirmo-escritura-AFQP", "--project", "DEMO"]
    assert main(argv) == 2

    assert "AFQP" in capsys.readouterr().err
    assert "JIRA_PUBLISH_MODE" not in os.environ


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--story", "AFQP-1"],
        ["--qa-story", "AFQP-2"],
        ["--story", "AFQP-1", "--qa-story", "OTRO-2"],
        ["--story", "AFQP-1", "--qa-story", "AFQP-2", "--quality-story", "OTRO-3"],
    ],
    ids=["sin-claves", "sin-qa-story", "sin-story", "qa-ajena", "calidad-ajena"],
)
def test_options_reject_real_sandbox_without_explicit_afqp_keys(extra: list[str]) -> None:
    """`--real --sandbox-live` exige --story y --qa-story de AFQP (nunca las de por defecto)."""
    args = parse_args(["--real", "--sandbox-live", "--confirmo-escritura-AFQP", *extra])

    with pytest.raises(DemoPrepareError, match="AFQP"):
        options_from(args)


def test_options_accept_real_sandbox_on_afqp_stories() -> None:
    """`--real --sandbox-live` con confirmación y HU de AFQP indicadas a mano se acepta."""
    args = parse_args(
        [
            "--real",
            "--sandbox-live",
            "--confirmo-escritura-AFQP",
            "--story",
            "AFQP-1",
            "--qa-story",
            "AFQP-2",
        ]
    )

    options = options_from(args)

    assert options.project == "AFQP"
    assert options.sandbox_live is True
    assert (options.story, options.qa_story, options.quality_story) == (
        "AFQP-1",
        "AFQP-2",
        "AFQP-1",
    )


def test_options_real_defaults_point_to_afqp_demo() -> None:
    """Con `--real`, la demo actual: AFQP, suite de AFQP-28 y evolución y calidad de AFQP-3."""
    options = options_from(parse_args(["--real"]))

    assert options.project == "AFQP"
    assert options.qa_story == "AFQP-28"
    assert options.story == "AFQP-3"
    assert options.quality_story == "AFQP-3"
    assert options.qa_story != "AFQP-27"  # PA-450: ya tiene AFQP-29…34
    assert options.sandbox_live is False
    assert (options.functional_user, options.qa_user) == ("af-demo", "qa-demo")
    assert Options().qa_story == "AFQP-28" and Options().project == "AFQP"


def test_options_map_cli_flags_with_fake_defaults() -> None:
    """`--rehacer` y `--only` llegan como conjuntos; con `--fake`, el proyecto DEMO de los fakes."""
    args = parse_args(
        ["--fake", "--only", "calidad", "--only", "evolucion-iterada", "--rehacer", "calidad"]
    )

    options = options_from(args)

    assert options.only == frozenset({"calidad", "evolucion-iterada"})
    assert options.redo == frozenset({"calidad"})
    assert (options.project, options.story, options.qa_story) == ("DEMO", STORY, STORY)
    assert options.sandbox_live is False


def test_options_quality_story_overrides_story() -> None:
    """`--quality-story` separa la HU de la revisión de la HU que se evoluciona."""
    options = options_from(parse_args(["--real", "--quality-story", "AFQP-5"]))

    assert (options.story, options.quality_story) == ("AFQP-3", "AFQP-5")


@pytest.mark.parametrize("argv", [[], ["--fake", "--real"], ["--out", "x"]])
def test_parse_args_requires_exactly_one_target(argv: list[str]) -> None:
    """Sin `--fake` ni `--real` (o con los dos) argparse sale con SystemExit."""
    with pytest.raises(SystemExit) as exc:
        main(argv)

    assert exc.value.code == 2


def test_prepare_rejects_unknown_step_names(rt: Runtime, out: Path) -> None:
    """Un `--only` o `--rehacer` con un nombre que no existe avisa en lugar de ignorarse."""
    with pytest.raises(DemoPrepareError, match="desconocidos"):
        prepare(rt, _fake_options(only=frozenset({"no-existe"})), out)
    with pytest.raises(DemoPrepareError, match="desconocidos"):
        prepare(rt, _fake_options(redo=frozenset({"sandbox-hu-publicada"})), out)
    with pytest.raises(DemoPrepareError, match="desconocidos"):  # pasos retirados
        prepare(rt, _fake_options(only=frozenset({"ejecucion-en-revision"})), out)


def test_quality_rejects_key_that_is_not_an_issue_key(rt: Runtime, out: Path) -> None:
    """Una clave de calidad que no es de Jira falla antes de guardar nada ni llamar al modelo."""
    (item,) = prepare(rt, _fake_options(quality_story="../fuera", only=frozenset({"calidad"})), out)

    assert item.state == "failed"
    assert "no válida" in item.note
    assert rt.quality.list_for("af-demo") == []
    assert _llm(rt).calls == []


# --- 8. Resumen y manifiesto -------------------------------------------------------------


def test_summary_has_one_row_per_step_without_story_content(rt: Runtime, out: Path) -> None:
    """preparadas.md lleva todas las filas y nada del contenido de las HU ni de las peticiones."""
    items = prepare(rt, _fake_options(), out)
    text = (out / SUMMARY).read_text(encoding="utf-8")

    rows = [line for line in text.splitlines() if line.startswith("| ") and "`" in line]
    assert len(rows) == len(items) == len(SIMULATION_STEPS)
    for item in items:
        assert f"| {item.name} | {item.user} | `{item.id}` |" in text
    assert "modo `simulation`" in text
    assert "web/DEMO.md" in text
    for secret_text in (
        dataset.renewal_story().title,
        dataset.renewal_story().description,
        EVOLVE_FEEDBACK,
        ITERATE_FEEDBACK,
    ):
        assert secret_text not in text


def test_manifest_round_trips_prepared_items(rt: Runtime, out: Path) -> None:
    """preparadas.json se relee y reproduce los mismos `Prepared`, sin contenido de las HU."""
    items = prepare(rt, _fake_options(), out)

    raw = json.loads((out / MANIFEST).read_text(encoding="utf-8"))

    assert raw["version"] == 2
    assert [Prepared(**data) for data in raw["items"].values()] == items
    text = (out / MANIFEST).read_text(encoding="utf-8")
    assert EVOLVE_FEEDBACK not in text and dataset.renewal_story().title not in text


def test_manifest_from_previous_version_drops_retired_steps(rt: Runtime, out: Path) -> None:
    """Las entradas de la versión del 2 de octubre (DEMO-3, ejecución…) se descartan sin error."""
    out.mkdir(parents=True)
    old = {
        "necesidad-iterada": {
            "name": "necesidad-iterada",
            "kind": "conversation",
            "user": "af-demo",
            "id": str(uuid4()),
            "state": "in_review",
            "expected": "in_review",
            "handoff_id": None,
        },
        "ejecucion-en-revision": {
            "name": "ejecucion-en-revision",
            "kind": "execution",
            "user": "qa-demo",
        },
        "calidad": {
            "name": "calidad",
            "kind": "quality",
            "user": "af-demo",
            "id": "calidad-DEMO-3.md",
            "state": "done",
            "expected": "done",
            "handoff_id": None,
        },
    }
    (out / MANIFEST).write_text(json.dumps({"version": 1, "items": old}), encoding="utf-8")

    items = prepare(rt, _fake_options(), out)

    assert [i.name for i in items] == SIMULATION_NAMES
    assert _by_name(items)["calidad"].id != "calidad-DEMO-3.md"
    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    assert sorted(saved["items"]) == sorted(SIMULATION_NAMES)


@pytest.mark.parametrize(
    "content",
    [
        "{esto no es json",
        json.dumps({"items": {"calidad": {"nombre": "desconocido"}}}),
        json.dumps({"items": {"calidad": ["no", "es", "un", "objeto"]}}),
    ],
)
def test_prepare_rejects_damaged_manifest(rt: Runtime, out: Path, content: str) -> None:
    """Un manifiesto dañado → DemoPrepareError y no se toca nada."""
    out.mkdir(parents=True)
    (out / MANIFEST).write_text(content, encoding="utf-8")

    with pytest.raises(DemoPrepareError, match="dañado"):
        prepare(rt, _fake_options(), out)

    assert (out / MANIFEST).read_text(encoding="utf-8") == content
    assert _llm(rt).calls == []


@pytest.mark.parametrize("content", ["[]", json.dumps({"items": []}), "null"])
def test_prepare_rejects_manifest_with_wrong_shape(rt: Runtime, out: Path, content: str) -> None:
    """Un manifiesto con JSON válido pero forma incorrecta también está dañado."""
    out.mkdir(parents=True)
    (out / MANIFEST).write_text(content, encoding="utf-8")

    with pytest.raises(DemoPrepareError):
        prepare(rt, _fake_options(), out)


def test_prepare_rejects_manifest_with_unknown_kind(rt: Runtime, out: Path) -> None:
    """Un `kind` desconocido en un paso vigente se trata como manifiesto dañado."""
    out.mkdir(parents=True, exist_ok=True)
    entry = {"name": "calidad", "kind": "execution", "user": "af-demo"}
    (out / MANIFEST).write_text(
        json.dumps({"version": 2, "items": {"calidad": entry}}), encoding="utf-8"
    )

    with pytest.raises(DemoPrepareError, match="dañado"):
        prepare(rt, _fake_options(), out)


def test_render_summary_escapes_pipes_and_newlines_in_note() -> None:
    """La nota con `|` y saltos de línea no rompe la fila de la tabla."""
    item = Prepared(
        name="calidad",
        kind="quality",
        user="af-demo",
        id=str(uuid4()),
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
    """Sin id, modelo, segundos ni nota se pinta «—»."""
    item = Prepared(name="qa-suite-en-revision", kind="conversation", user="qa-demo")

    row = next(line for line in render_summary([item], "live").splitlines() if "qa-suite" in line)

    assert row == "| qa-suite-en-revision | qa-demo | — | ⚠️ pending | in_review | — | — | — |"


def test_render_summary_escapes_every_cell() -> None:
    """Ningún campo del manifiesto (id, modelo, estado…) puede romper la tabla."""
    item = Prepared(
        name="a|b", kind="conversation", user="u", id="x`|y", state="in|review", model="m|1"
    )

    row = render_summary([item], "simulation").splitlines()[-1]

    assert row.count(" | ") == 7  # 8 celdas
    assert "`x'\\|y`" in row and "a\\|b" in row and "m\\|1" in row


# --- 9. build() --------------------------------------------------------------------------


def test_build_fake_returns_fake_runtime_and_temp_out(no_tempdir_leak: Path) -> None:
    """Con `--fake` y sin `--out`, fakes en el modo pedido y carpeta temporal."""
    rt, out_dir = build(parse_args(["--fake"]), "simulation")

    assert isinstance(rt, Runtime)
    container = rt.workspace_factory().container
    assert container.publish_mode == "simulation"
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    assert out_dir == no_tempdir_leak / "demo"


def test_build_fake_honours_out_and_live_mode(tmp_path: Path, no_tempdir_leak: Path) -> None:
    """`--out` se respeta y el modo `live` llega a la composición de fakes."""
    rt, out_dir = build(parse_args(["--fake", "--out", str(tmp_path / "x")]), "live")

    assert rt.workspace_factory().container.publish_mode == "live"
    assert out_dir == tmp_path / "x"


@pytest.mark.parametrize("mode", ["simulation", "live"])
def test_build_real_forces_publish_mode_env(
    monkeypatch: pytest.MonkeyPatch, mode: demo_prepare.Mode
) -> None:
    """Con `--real` fija JIRA_PUBLISH_MODE al modo pedido antes de componer."""
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
    """Sin JIRA_PUBLISH_MODE previo también lo fija; `--out` manda sobre docs/demo."""
    _unset_publish_mode(monkeypatch)
    monkeypatch.setattr(api.runtime, "build_runtime", lambda: "composicion-ficticia")

    rt, out_dir = build(parse_args(["--real", "--out", str(tmp_path / "y")]), "simulation")

    assert rt == "composicion-ficticia"
    assert out_dir == tmp_path / "y"
    assert os.environ["JIRA_PUBLISH_MODE"] == "simulation"


def test_main_real_in_simulation_refuses_live_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Si la composición real no quedara en simulación, `--real` se para con 2 sin escribir."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    monkeypatch.setattr(api.runtime, "build_runtime", lambda: live)
    monkeypatch.setenv("JIRA_PUBLISH_MODE", "simulation")

    assert main(["--real", "--out", str(tmp_path / "z")]) == 2

    assert "JIRA_PUBLISH_MODE" in capsys.readouterr().err
    assert _tracker(live).writes == [] and _tm(live).publish_calls == 0
    assert _llm(live).calls == []


# --- 10. Correcciones tras security-reviewer y spec-checker ---------------------------------


def test_prepare_records_api_error_and_keeps_published_story_in_manifest(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un `ApiError` de `api.service` marca el paso como fallido sin perder el manifiesto: la HU
    ya publicada en el sandbox no se vuelve a publicar al repetir."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    real_resume = service.resume

    def resume(rt: Runtime, ws: Any, user: User, *args: Any) -> Any:
        if user.role == "qa":
            raise ApiError(409, "not_in_review", "La conversación no está en revisión.")
        return real_resume(rt, ws, user, *args)

    monkeypatch.setattr(service, "resume", resume)

    items = _by_name(prepare(live, _fake_options(sandbox_live=True), out, "live"))

    assert items["sandbox-hu-publicada"].state == "published"
    assert items["sandbox-casos-publicados"].state == "failed"
    assert "no está en revisión" in items["sandbox-casos-publicados"].note
    updates = [w for w in _tracker(live).writes if w[0] == "update_story"]
    assert updates

    monkeypatch.setattr(service, "resume", real_resume)
    again = _by_name(prepare(live, _fake_options(sandbox_live=True), out, "live"))

    assert again["sandbox-hu-publicada"].id == items["sandbox-hu-publicada"].id
    assert [w for w in _tracker(live).writes if w[0] == "update_story"] == updates


def test_main_returns_two_on_api_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Un `ApiError` fuera de los pasos (p. ej. al componer) sale con 2 y su mensaje, sin traza."""

    def failing_build(*_args: object) -> None:
        raise ApiError(503, "unavailable", "Servicio ficticio no disponible.")

    monkeypatch.setattr(demo_prepare, "build", failing_build)

    assert main(["--fake"]) == 2
    assert "Servicio ficticio no disponible." in capsys.readouterr().err


def test_prepare_saves_manifest_before_propagating_unexpected_error(
    rt: Runtime, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un error no previsto se propaga, pero lo ya preparado queda guardado."""

    def boom(*_args: object) -> None:
        raise RuntimeError("fallo ficticio")

    steps = tuple(
        Step(s.name, s.role, s.kind, s.expected, boom if s.name == "calidad" else s.run)
        for s in SIMULATION_STEPS
    )
    monkeypatch.setattr(demo_prepare, "SIMULATION_STEPS", steps)

    with pytest.raises(RuntimeError):
        prepare(rt, _fake_options(), out)

    saved = json.loads((out / MANIFEST).read_text(encoding="utf-8"))["items"]
    assert saved["qa-suite-en-revision"]["state"] == "in_review"
    assert saved["calidad"]["state"] == "failed"


def test_sandbox_rechecks_published_cases_right_before_approving(
    tmp_path: Path, out: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-450: si aparecen casos en Jira mientras se genera la suite, no se aprueba."""
    live = fake_runtime(tmp_path / "rt", publish_mode="live")
    real_start = demo_prepare._start

    def start(ctx: Any, role: str, body: Any, item: Prepared) -> str:
        thread = real_start(ctx, role, body, item)
        if role == "qa":
            _tm(live).cases[STORY] = list(CASES)  # alguien publicó entretanto
        return thread

    monkeypatch.setattr(demo_prepare, "_start", start)

    items = _by_name(prepare(live, _fake_options(sandbox_live=True), out, "live"))

    assert items["sandbox-casos-publicados"].state == "failed"
    assert "casos publicados" in items["sandbox-casos-publicados"].note
    assert _tm(live).publish_calls == 0


def test_check_mode_checks_every_role_workspace(tmp_path: Path, out: Path) -> None:
    """Si el contenedor de QA no estuviera en simulación, tampoco se sigue."""
    rt = fake_runtime(tmp_path / "rt")
    live = fake_runtime(tmp_path / "live", publish_mode="live")
    workspaces = iter([rt.workspace_factory(), live.workspace_factory()])
    rt.workspace_factory = lambda: next(workspaces)

    with pytest.raises(DemoPrepareError, match="JIRA_PUBLISH_MODE"):
        prepare(rt, _fake_options(), out)

    assert not out.exists()
    assert _llm(live).calls == []


def test_quality_normalizes_key_like_the_api(rt: Runtime, out: Path) -> None:
    """Como la API: una clave escrita a mano (` demo-3 `) se normaliza a `DEMO-3`."""
    (item,) = prepare(rt, _fake_options(quality_story=" demo-3 ", only=frozenset({"calidad"})), out)

    assert item.state == "done"
    review = rt.quality.get(item.id or "")
    assert review is not None and review.issue_key == STORY


def test_quality_requires_review_permission(rt: Runtime, out: Path) -> None:
    """Como la API: sin el permiso de revisar (rol QA), no se guarda ninguna revisión."""
    ctx = _Context(rt=rt, options=_fake_options(), out_dir=out)
    ctx.users = {"functional": QA, "qa": QA}
    item = Prepared(name="calidad", kind="quality", user="qa-demo", expected="done")

    with pytest.raises(AuthenticationError, match="permiso"):
        demo_prepare._quality(ctx, item)

    assert rt.quality.list_for("qa-demo") == []
    assert _llm(rt).calls == []
