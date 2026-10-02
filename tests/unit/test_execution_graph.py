"""Grafo del registro de la ejecución (T-47 · RF-28, R-01 opción A; UI.md §6.6).

Solo fakes de `tests/fakes/` y datos 100 % ficticios (claves DEMO-5xx, textos «ficticio»).
Comprueba que `publish` es el único nodo que escribe, solo con la aprobación vigente guardada en
el servidor, una sola vez, y que la auditoría nunca guarda el texto de la evidencia.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters import base
from adapters.base import IssueSummary
from adapters.errors import NotFoundError, PublishError
from core.audit import InMemoryAuditTrail
from core.container import Container
from core.factories import PendingTestManagement
from core.graph import memory_checkpointer
from core.graph.execution import (
    MAX_ENVIRONMENT_CHARS,
    NO_CASES,
    ExecutionNodes,
    ExecutionRejectedError,
    ExecutionState,
    build_execution_graph,
    clean_environment,
    execution_fingerprint,
    execution_plan,
    initial_execution_state,
    validate_results,
)
from schemas.test_case import MAX_EVIDENCE_CHARS, ExecutionStatus
from tests.fakes.container import fake_container
from tests.fakes.test_management import FakeTestManagement

USER = "qa-demo"
STORY = "DEMO-3"
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
EVIDENCE = "Texto de evidencia ficticio-7f3a: el botón no responde."
RESULTS = [
    {"case_key": "DEMO-501", "status": "paso", "evidence_md": ""},
    {"case_key": "DEMO-502", "status": "fallo", "evidence_md": EVIDENCE},
]


# --- utilidades --------------------------------------------------------------------------


@pytest.fixture
def container(tmp_path: Path) -> Container:
    c = fake_container(tmp_path)
    _tm(c).cases[STORY] = list(CASES)
    return c


@pytest.fixture
def graph(container: Container) -> CompiledStateGraph:
    return build_execution_graph(container, checkpointer=memory_checkpointer())


def _tm(c: Container) -> FakeTestManagement:
    tm = c.test_management
    assert isinstance(tm, FakeTestManagement)
    return tm


def _config(user: str = USER) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(uuid4()), "user": user}}


def _start(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    graph.invoke(initial_execution_state(USER, STORY), config)
    return _payload(graph, config)


def _payload(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    snapshot = graph.get_state(config)
    values = [i.value for task in snapshot.tasks for i in task.interrupts]
    assert values, "el grafo no está en revisión"
    return values[-1]


def _in_review(graph: CompiledStateGraph, config: dict[str, Any]) -> bool:
    snapshot = graph.get_state(config)
    return any(task.interrupts for task in snapshot.tasks)


def _resume(graph: CompiledStateGraph, config: dict[str, Any], answer: Any) -> None:
    graph.invoke(Command(resume=answer), config)


def _save(
    graph: CompiledStateGraph,
    config: dict[str, Any],
    results: list[dict[str, Any]] | None = None,
    environment: str = "",
) -> dict[str, Any]:
    answer = {
        "decision": "save",
        "results": RESULTS if results is None else results,
        "environment": environment,
    }
    _resume(graph, config, answer)
    return _payload(graph, config)


def _cases_rows() -> list[dict[str, str]]:
    return [{"key": c.key, "summary": c.summary, "status": c.status} for c in CASES]


def _state(**overrides: Any) -> ExecutionState:
    state = initial_execution_state(USER, STORY)
    state["cases"] = _cases_rows()  # type: ignore[typeddict-item]
    state["results"] = [dict(r) for r in RESULTS]  # type: ignore[typeddict-item]
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# --- carga de casos ------------------------------------------------------------------------


def test_load_cases_raises_publish_error_when_story_has_no_cases(tmp_path: Path) -> None:
    """RF-28: una HU sin subtareas CP no se puede registrar; mensaje en español con la clave."""
    c = fake_container(tmp_path)
    g = build_execution_graph(c, checkpointer=memory_checkpointer())
    with pytest.raises(PublishError) as exc:
        g.invoke(initial_execution_state(USER, STORY), _config())
    assert str(exc.value) == NO_CASES.format(key=STORY)
    assert _tm(c).executions == []


def test_start_pauses_in_review_with_receipt_payload(graph: CompiledStateGraph) -> None:
    """UI.md §6.6: la revisión muestra los casos, sin resultados, con huella y sin error."""
    payload = _start(graph, _config())
    assert payload["kind"] == "execution"
    assert payload["story_key"] == STORY
    assert [c["key"] for c in payload["cases"]] == ["DEMO-501", "DEMO-502"]
    assert payload["results"] == [] and payload["plan"] == []
    assert payload["environment"] == ""
    assert len(payload["fingerprint"]) == 64
    assert payload["error"] is None


# --- flujo feliz -----------------------------------------------------------------------------


def test_save_then_approve_records_each_case_once_with_environment(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-28 · principio 1: aprobar escribe cada caso una vez, con «Entorno: …» delante."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config, environment="preproducción ficticia")
    assert _tm(container).executions == []  # guardar no escribe
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})

    executions = _tm(container).executions
    assert [(k, s) for k, s, _e in executions] == [("DEMO-501", "paso"), ("DEMO-502", "fallo")]
    assert executions[0][2] == "Entorno: preproducción ficticia"
    assert executions[1][2] == f"Entorno: preproducción ficticia\n\n{EVIDENCE}"
    values = graph.get_state(config).values
    assert values["recorded"] == ["DEMO-501", "DEMO-502"]
    assert values["failed"] == [] and values["errors"] == []
    assert values["approved_at"]
    assert not _in_review(graph, config)


def test_approve_without_environment_sends_evidence_unchanged(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-28: sin entorno, la evidencia va tal cual (sin prefijo «Entorno:»)."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    assert _tm(container).executions == [
        ("DEMO-501", "paso", ""),
        ("DEMO-502", "fallo", EVIDENCE),
    ]


def test_save_orders_results_as_cases_and_normalizes_keys(graph: CompiledStateGraph) -> None:
    """RF-28: los resultados se ordenan como los casos y la clave se normaliza a mayúsculas."""
    config = _config()
    _start(graph, config)
    payload = _save(
        graph,
        config,
        results=[
            {"case_key": "demo-502", "status": "bloqueado", "evidence_md": "  "},
            {"case_key": "DEMO-501", "status": "sin-ejecutar"},
        ],
    )
    assert payload["error"] is None
    assert payload["results"] == [
        {"case_key": "DEMO-501", "status": "sin-ejecutar", "evidence_md": ""},
        {"case_key": "DEMO-502", "status": "bloqueado", "evidence_md": ""},
    ]
    assert [op["label"] for op in payload["plan"]] == ["Sin ejecutar", "Bloqueado"]


# --- aprobaciones que no valen -----------------------------------------------------------------


def test_approve_with_old_fingerprint_stays_in_review_without_writing(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Principio 1: la huella de un registro anterior no aprueba el actual."""
    config = _config()
    first = _start(graph, config)
    _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": first["fingerprint"]})
    payload = _payload(graph, config)
    assert (
        payload["error"] == "La aprobación no corresponde al registro revisado; vuelve a revisarlo."
    )
    assert _tm(container).executions == []
    stored = container.state_store.load(config["configurable"]["thread_id"]) or {}
    assert (stored.get("execution") or {}).get("approved") is None


def test_approve_without_results_stays_in_review_without_writing(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-28: no se aprueba un registro vacío."""
    config = _config()
    payload = _start(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    after = _payload(graph, config)
    assert after["error"] == "Elige el resultado de al menos un caso."
    assert _tm(container).executions == []


@pytest.mark.parametrize(
    "answer", ["aprobar", 42, {"decision": "publicar"}, {"fingerprint": "f" * 64}]
)
def test_invalid_answer_returns_to_review_with_error(
    graph: CompiledStateGraph, container: Container, answer: Any
) -> None:
    """Respuestas no válidas: la revisión sigue con el motivo y nada se escribe."""
    config = _config()
    _start(graph, config)
    _resume(graph, config, answer)
    payload = _payload(graph, config)
    assert payload["error"] == "Decisión no válida: usa guardar, aprobar o descartar."
    assert _tm(container).executions == []


# --- validación del borrador --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("results", "message"),
    [
        (
            [{"case_key": "DEMO-502", "status": "fallo", "evidence_md": "   "}],
            "Un caso fallido necesita evidencia (DEMO-502).",
        ),
        (
            [{"case_key": "DEMO-999", "status": "paso", "evidence_md": ""}],
            "DEMO-999 no es un caso de esta HU.",
        ),
        (
            [
                {"case_key": "DEMO-501", "status": "paso"},
                {"case_key": "demo-501", "status": "bloqueado"},
            ],
            "El caso DEMO-501 aparece dos veces.",
        ),
        (
            [{"case_key": "DEMO-501", "status": "aprobado", "evidence_md": ""}],
            "El resultado de DEMO-501 no es válido.",
        ),
        (
            [
                {
                    "case_key": "DEMO-501",
                    "status": "paso",
                    "evidence_md": "x" * (MAX_EVIDENCE_CHARS + 1),
                }
            ],
            f"La evidencia de DEMO-501 supera los {MAX_EVIDENCE_CHARS} caracteres.",
        ),
        ("no-es-lista", "Los resultados deben ser una lista, uno por caso."),
        (["DEMO-501"], "Cada resultado necesita el caso, el estado y la evidencia."),
    ],
    ids=[
        "fallo-sin-evidencia",
        "otra-hu",
        "duplicado",
        "estado",
        "evidencia-larga",
        "tipo",
        "item",
    ],
)
def test_invalid_save_keeps_review_with_error_and_previous_draft(
    graph: CompiledStateGraph, container: Container, results: Any, message: str
) -> None:
    """RF-28: un borrador no válido no se aplica; la revisión sigue con el motivo."""
    config = _config()
    _start(graph, config)
    before = _save(graph, config)
    _resume(graph, config, {"decision": "save", "results": results, "environment": ""})
    payload = _payload(graph, config)
    assert payload["error"] == message
    assert payload["results"] == before["results"]  # se conserva el borrador anterior
    assert payload["fingerprint"] == before["fingerprint"]
    assert _tm(container).executions == []


def test_environment_over_limit_is_review_error(graph: CompiledStateGraph) -> None:
    """Límite: el entorno admite como mucho 100 caracteres."""
    config = _config()
    _start(graph, config)
    _resume(
        graph,
        config,
        {"decision": "save", "results": RESULTS, "environment": "e" * (MAX_ENVIRONMENT_CHARS + 1)},
    )
    payload = _payload(graph, config)
    assert payload["error"] == f"El entorno admite como mucho {MAX_ENVIRONMENT_CHARS} caracteres."
    assert payload["results"] == []


def test_environment_at_limit_and_control_chars_are_accepted() -> None:
    """Límite: 100 caracteres valen; los caracteres de control se sustituyen por espacios."""
    assert clean_environment("e" * MAX_ENVIRONMENT_CHARS) == "e" * MAX_ENVIRONMENT_CHARS
    assert clean_environment("pre\x00pro\nducción\x7f") == "pre pro ducción"
    assert clean_environment(None) == ""


def test_evidence_at_limit_is_accepted() -> None:
    """Límite: exactamente 20 000 caracteres de evidencia son válidos."""
    rows = validate_results(
        [{"case_key": "DEMO-501", "status": "paso", "evidence_md": "x" * MAX_EVIDENCE_CHARS}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert len(rows[0]["evidence_md"]) == MAX_EVIDENCE_CHARS


def test_validate_results_rejects_with_execution_rejected_error() -> None:
    """La validación pura lanza `ExecutionRejectedError` (no escribe ni toca el estado)."""
    with pytest.raises(ExecutionRejectedError):
        validate_results([{"case_key": "DEMO-501", "status": ""}], _cases_rows())  # type: ignore[arg-type]


def test_evidence_at_limit_with_environment_is_rejected_in_review(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Límite: con el entorno delante, la evidencia que llegaría a Jira no puede pasar del máximo.

    Se rechaza en la revisión (con su motivo) en lugar de fallar en Jira después de aprobarla.
    """
    config = _config()
    _start(graph, config)
    payload = _save(
        graph,
        config,
        results=[
            {"case_key": "DEMO-501", "status": "paso", "evidence_md": "x" * MAX_EVIDENCE_CHARS}
        ],
        environment="preproducción ficticia",
    )
    assert payload["error"] is not None
    assert "con el entorno supera" in payload["error"]
    assert payload["results"] == []  # el borrador anterior se conserva


# --- huella y recibo -----------------------------------------------------------------------------


def test_fingerprint_changes_with_results_and_environment() -> None:
    """Principio 1: la huella cubre cada resultado y el entorno; es estable si nada cambia."""
    base = _state()
    thread = str(uuid4())
    fp = execution_fingerprint(base, thread)
    assert fp == execution_fingerprint(_state(), thread)
    changed_status = _state(
        results=[RESULTS[0] | {"status": "bloqueado"}, RESULTS[1]]  # type: ignore[list-item]
    )
    changed_evidence = _state(
        results=[RESULTS[0], RESULTS[1] | {"evidence_md": "Otra evidencia ficticia."}]  # type: ignore[list-item]
    )
    changed_env = _state(environment="preproducción ficticia")
    fingerprints = {
        fp,
        execution_fingerprint(changed_status, thread),
        execution_fingerprint(changed_evidence, thread),
        execution_fingerprint(changed_env, thread),
        execution_fingerprint(base, str(uuid4())),
    }
    assert len(fingerprints) == 5


def test_fingerprint_in_review_changes_after_each_save(graph: CompiledStateGraph) -> None:
    """La huella mostrada cambia al guardar otros resultados o otro entorno."""
    config = _config()
    empty = _start(graph, config)["fingerprint"]
    with_results = _save(graph, config)["fingerprint"]
    with_env = _save(graph, config, environment="preproducción ficticia")["fingerprint"]
    assert len({empty, with_results, with_env}) == 3


def test_plan_has_one_operation_per_case_without_evidence_text() -> None:
    """RF-31: el recibo lleva una operación por caso y nunca el texto de la evidencia."""
    plan = execution_plan(_state())
    assert plan == [
        {
            "op": "record_execution",
            "key": "DEMO-501",
            "status": "paso",
            "label": "Pasó",
            "evidence": "no",
        },
        {
            "op": "record_execution",
            "key": "DEMO-502",
            "status": "fallo",
            "label": "Falló",
            "evidence": "sí",
        },
    ]
    assert EVIDENCE not in str(plan)


# --- descartar ---------------------------------------------------------------------------------


def test_discard_ends_without_writing(graph: CompiledStateGraph, container: Container) -> None:
    """Principio 1: descartar termina el registro sin escribir en Jira."""
    config = _config()
    _start(graph, config)
    _save(graph, config)
    _resume(graph, config, {"decision": "discard"})
    assert not _in_review(graph, config)
    assert graph.get_state(config).values["decision"] == "discard"
    assert _tm(container).executions == []
    actions = [e.action for e in _audit(container)]
    assert actions == ["discard"]


# --- publish: aprobación del servidor ----------------------------------------------------------


def _approved_state(container: Container, thread_id: str, **stored: Any) -> ExecutionState:
    state = _state(decision="approve")
    fp = execution_fingerprint(state, thread_id)
    container.state_store.save(thread_id, {"execution": {"approved": fp, "used": False} | stored})
    return state


def test_publish_without_stored_approval_raises_and_does_not_write(container: Container) -> None:
    """Principio 1: sin aprobación guardada en el servidor, publish no escribe."""
    nodes = ExecutionNodes(container)
    config = _config()
    state = _state(decision="approve")
    with pytest.raises(PublishError, match="aprobación humana vigente"):
        nodes.publish(state, config)  # type: ignore[arg-type]
    assert _tm(container).executions == []


def test_publish_with_used_approval_raises_and_does_not_write(container: Container) -> None:
    """Principio 1: la aprobación es de un solo uso."""
    nodes = ExecutionNodes(container)
    config = _config()
    state = _approved_state(container, config["configurable"]["thread_id"], used=True)
    with pytest.raises(PublishError, match="aprobación humana vigente"):
        nodes.publish(state, config)  # type: ignore[arg-type]
    assert _tm(container).executions == []


def test_publish_with_tampered_state_raises_and_does_not_write(container: Container) -> None:
    """Principio 1: si el estado del grafo se altera tras aprobar, la huella no casa."""
    nodes = ExecutionNodes(container)
    config = _config()
    state = _approved_state(container, config["configurable"]["thread_id"])
    state["environment"] = "otro entorno ficticio"
    with pytest.raises(PublishError):
        nodes.publish(state, config)  # type: ignore[arg-type]
    assert _tm(container).executions == []


def test_publish_without_approve_decision_raises(container: Container) -> None:
    """Principio 1: publish exige la decisión explícita `approve`."""
    nodes = ExecutionNodes(container)
    config = _config()
    state = _approved_state(container, config["configurable"]["thread_id"])
    state["decision"] = "save"
    with pytest.raises(PublishError, match="confirmación explícita"):
        nodes.publish(state, config)  # type: ignore[arg-type]
    assert _tm(container).executions == []


def test_publish_marks_approval_used_and_second_call_fails(container: Container) -> None:
    """Principio 1: tras publicar la aprobación queda usada; repetir no vuelve a escribir."""
    nodes = ExecutionNodes(container)
    config = _config()
    thread_id = config["configurable"]["thread_id"]
    state = _approved_state(container, thread_id)
    nodes.publish(state, config)  # type: ignore[arg-type]
    assert len(_tm(container).executions) == 2
    assert container.state_store.load(thread_id)["execution"]["used"] is True
    with pytest.raises(PublishError):
        nodes.publish(state, config)  # type: ignore[arg-type]
    assert len(_tm(container).executions) == 2


def test_partial_failure_records_failed_and_errors_and_uses_approval(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RNF-13: un caso que falla queda en `failed`/`errors`; el resto se registra."""
    _tm(container).fail_execution_keys = {"DEMO-502"}
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    values = graph.get_state(config).values
    assert values["recorded"] == ["DEMO-501"]
    assert values["failed"] == ["DEMO-502"]
    assert values["errors"] == ["No se pudo registrar la ejecución en DEMO-502."]
    stored = container.state_store.load(config["configurable"]["thread_id"])["execution"]
    assert stored["used"] is True and stored["failed"] == ["DEMO-502"]
    assert [k for k, _s, _e in _tm(container).executions] == ["DEMO-501"]


# --- propiedad del hilo -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "configurable",
    [
        {"thread_id": "PLACEHOLDER", "user": "af-demo"},
        {"thread_id": "PLACEHOLDER"},
        {"thread_id": "id con espacios", "user": USER},
    ],
    ids=["otro-user", "sin-user", "thread-invalido"],
)
def test_config_of_other_user_or_bad_thread_is_not_found(
    container: Container, configurable: dict[str, str]
) -> None:
    """T-52: solo la dueña actúa sobre su registro; si no, NotFoundError (mismo mensaje)."""
    if configurable["thread_id"] == "PLACEHOLDER":
        configurable = configurable | {"thread_id": str(uuid4())}
    nodes = ExecutionNodes(container)
    state = initial_execution_state(USER, STORY)
    for node in (nodes.load_cases, nodes.review, nodes.publish):
        with pytest.raises(NotFoundError):
            node(state, {"configurable": configurable})  # type: ignore[arg-type]
    assert _tm(container).executions == []


def test_graph_invoked_with_other_user_is_not_found(graph: CompiledStateGraph) -> None:
    """T-52: arrancar el grafo con una config de otra persona falla con NotFoundError."""
    with pytest.raises(NotFoundError):
        graph.invoke(initial_execution_state(USER, STORY), _config(user="af-demo"))


# --- auditoría -----------------------------------------------------------------------------------


def _audit(container: Container) -> list[Any]:
    audit = container.audit
    assert isinstance(audit, InMemoryAuditTrail)
    return audit.recorded


def test_audit_has_approve_and_publish_without_evidence_text(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Trazabilidad: se audita aprobar y publicar con claves y recuentos, nunca la evidencia."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config, environment="preproducción ficticia")
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    entries = _audit(container)
    assert [e.action for e in entries] == ["approve", "publish"]
    assert all(e.user == USER and e.detail["story"] == STORY for e in entries)
    assert entries[1].jira_keys == ["DEMO-501", "DEMO-502"]
    assert entries[1].detail["recorded"] == 2
    dumped = " ".join(e.model_dump_json() for e in entries)
    assert "ficticio-7f3a" not in dumped
    assert EVIDENCE not in dumped


# --- protocolo y pendiente -----------------------------------------------------------------------


def test_fake_satisfies_test_management_protocol() -> None:
    """El fake cumple el Protocol `TestManagement` (runtime_checkable) con `record_execution`."""
    assert isinstance(FakeTestManagement(), base.TestManagement)
    assert hasattr(base.TestManagement, "record_execution")


def test_pending_test_management_record_execution_raises_publish_error() -> None:
    """Sin adaptador real configurado, registrar lanza PublishError (mensaje en español)."""
    with pytest.raises(PublishError, match="T-47"):
        PendingTestManagement().record_execution("DEMO-501", ExecutionStatus.PASSED, "")


# --- endurecimiento (security-reviewer de T-47) -------------------------------------------------


def test_unexpected_error_marks_approval_used_and_hides_its_text(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un error no previsto en un caso no corta el registro, no repite nada y no se muestra."""
    tm = _tm(container)
    original = tm.record_execution

    def flaky(case_key: str, status: str, evidence_md: str) -> None:
        if case_key == RESULTS[0]["case_key"]:
            raise RuntimeError("detalle-interno-ficticio")
        original(case_key, status, evidence_md)

    monkeypatch.setattr(tm, "record_execution", flaky)
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    values = graph.get_state(config).values
    assert values["failed"] == [RESULTS[0]["case_key"]]
    assert all("detalle-interno-ficticio" not in e for e in values["errors"])
    stored = container.state_store.load(config["configurable"]["thread_id"]) or {}
    assert stored["execution"]["used"] is True


def test_approval_is_used_before_the_first_write(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La aprobación queda usada antes de escribir: si algo corta a medias, no se reutiliza."""
    tm = _tm(container)
    thread: dict[str, str] = {}

    def check_used(case_key: str, status: str, evidence_md: str) -> None:
        stored = container.state_store.load(thread["id"]) or {}
        assert stored["execution"]["used"] is True
        tm.executions.append((case_key, status, evidence_md))

    monkeypatch.setattr(tm, "record_execution", check_used)
    config = _config()
    thread["id"] = config["configurable"]["thread_id"]
    _start(graph, config)
    payload = _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    assert len(tm.executions) == len(RESULTS)


def test_evidence_control_characters_are_removed_but_lines_kept(
    graph: CompiledStateGraph, container: Container
) -> None:
    config = _config()
    _start(graph, config)
    row = {
        "case_key": RESULTS[0]["case_key"],
        "status": "fallo",
        "evidence_md": "Paso 1\x00\x07\n\tPaso 2\x1b (ficticio)",
    }
    payload = _save(graph, config, results=[row])
    assert payload["results"][0]["evidence_md"] == "Paso 1\n\tPaso 2 (ficticio)"


def test_simulation_mode_audits_the_plan_and_writes_nothing(tmp_path: Path) -> None:
    """T-25: en `simulation` el nodo publish no escribe; la aprobación se consume igual."""
    container = fake_container(tmp_path, publish_mode="simulation")
    _tm(container).cases[STORY] = list(CASES)
    graph = build_execution_graph(container, checkpointer=memory_checkpointer())
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    _resume(graph, config, {"decision": "approve", "fingerprint": payload["fingerprint"]})
    values = graph.get_state(config).values
    assert values["simulated"] is True and values["recorded"] == []
    assert _tm(container).executions == []
    publish = [e for e in container.audit.recorded if e.action == "publish"]
    assert publish and publish[-1].detail["simulated"] is True
    assert len(publish[-1].detail["plan"]) == len(RESULTS)
    stored = container.state_store.load(config["configurable"]["thread_id"]) or {}
    assert stored["execution"]["used"] is True


def test_fake_container_defaults_to_live_for_graph_tests(container: Container) -> None:
    """Las demás pruebas del grafo usan el Jira de los fakes en `live` (escriben en el fake)."""
    assert container.publish_mode == "live"
