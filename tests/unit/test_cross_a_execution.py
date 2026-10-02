"""Prueba cruzada T-35 (RNF-19): el área B prueba `core.graph.execution` del área A (T-47).

Cubre RF-28 (registrar el resultado y la evidencia por caso, R-01 opción A), el principio 1 de
CLAUDE.md (nada se escribe en Jira sin aprobación humana y solo desde `publish`), RNF-13
(publicación parcial sin dejar escrituras sin informar), RF-35 (auditoría sin contenido),
UI.md §5 (aprobación con huella, un solo uso; en simulación sigue vigente) y §6.6 (QA 6), y la
fila de T-47 del anexo §11 de SPEC-00. Se centra en los bordes que `test_execution_graph.py`
no fija: los cuatro resultados, claves de otra HU o mal formadas, la huella frente a cada
cambio, la aprobación ajena o repetida, datos personales en la evidencia, enlaces que no son
http(s), tamaños con caracteres de control, fallos del almacén y de la auditoría a mitad del
registro, mensajes y registros (logs) sin datos internos.

Solo fakes de `tests/fakes/`; nada de Jira ni LLM reales. Datos 100 % ficticios (claves
DEMO-6xx, textos «ficticio», dominio example.com). Los defectos confirmados van como
`xfail(strict=True)` con su PA provisional; el resto fija el comportamiento actual.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from structlog.testing import capture_logs

from adapters.base import IssueSummary
from adapters.errors import ExternalServiceError, NotFoundError, PublishError
from adapters.jira.adf import markdown_to_adf
from core.audit import AuditEntry, InMemoryAuditTrail
from core.container import Container
from core.conversations import NOT_YOURS
from core.graph import memory_checkpointer
from core.graph.execution import (
    MISMATCH,
    ExecutionNodes,
    ExecutionRejectedError,
    ExecutionState,
    build_execution_graph,
    evidence_for_jira,
    execution_fingerprint,
    execution_plan,
    initial_execution_state,
    validate_results,
)
from schemas.test_case import MAX_EVIDENCE_CHARS, ExecutionStatus
from tests.fakes.container import fake_container
from tests.fakes.test_management import FakeTestManagement

OWNER = "qa-ficticia"
OTHER = "qa-ajena-ficticia"
STORY = "DEMO-6"
CASE_KEYS = ["DEMO-601", "DEMO-602", "DEMO-603"]
CASES = [
    IssueSummary(
        key=key,
        summary=f"[CP-0{i}] Caso ficticio {i}",
        issue_type="Subtarea",
        status="Por hacer",
    )
    for i, key in enumerate(CASE_KEYS, start=1)
]
EVIDENCE = "Evidencia ficticia-c4e9: el formulario ficticio no guarda."
ENVIRONMENT = "preproducción ficticia-env-81"
RESULTS: list[dict[str, Any]] = [
    {"case_key": "DEMO-601", "status": "paso", "evidence_md": ""},
    {"case_key": "DEMO-602", "status": "fallo", "evidence_md": EVIDENCE},
    {"case_key": "DEMO-603", "status": "bloqueado", "evidence_md": "Entorno ficticio caído."},
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


def _audit(c: Container) -> list[AuditEntry]:
    audit = c.audit
    assert isinstance(audit, InMemoryAuditTrail)
    return audit.recorded


def _config(user: str = OWNER, thread_id: str | None = None) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id or str(uuid4()), "user": user}}


def _thread_id(config: dict[str, Any]) -> str:
    return str(config["configurable"]["thread_id"])


def _payload(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    snapshot = graph.get_state(config)
    values = [i.value for task in snapshot.tasks for i in task.interrupts]
    assert values, "el grafo no está en revisión"
    return values[-1]


def _start(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    graph.invoke(initial_execution_state(OWNER, STORY), config)
    return _payload(graph, config)


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


def _approve(graph: CompiledStateGraph, config: dict[str, Any], fingerprint: str) -> None:
    _resume(graph, config, {"decision": "approve", "fingerprint": fingerprint})


def _cases_rows() -> list[dict[str, str]]:
    return [{"key": c.key, "summary": c.summary, "status": c.status} for c in CASES]


def _state(**overrides: Any) -> ExecutionState:
    state = initial_execution_state(OWNER, STORY)
    state["cases"] = _cases_rows()  # type: ignore[typeddict-item]
    state["results"] = [dict(r) for r in RESULTS]  # type: ignore[typeddict-item]
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


def _stored(c: Container, config: dict[str, Any]) -> dict[str, Any]:
    return dict((c.state_store.load(_thread_id(config)) or {}).get("execution") or {})


# --- RF-28 · resultados válidos e inválidos ------------------------------------------------


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("paso", "Pasó"),
        ("fallo", "Falló"),
        ("bloqueado", "Bloqueado"),
        ("sin-ejecutar", "Sin ejecutar"),
    ],
)
def test_record_writes_each_valid_status_with_spanish_label(
    graph: CompiledStateGraph, container: Container, status: str, label: str
) -> None:
    """RF-28 · UI.md §6.6: los cuatro resultados se aceptan, el recibo los nombra en español y
    `publish` los escribe tal cual en la subtarea."""
    config = _config()
    _start(graph, config)
    row = {"case_key": "DEMO-601", "status": status, "evidence_md": "Nota ficticia."}
    payload = _save(graph, config, results=[row])
    assert payload["error"] is None
    assert payload["plan"][0]["label"] == label
    _approve(graph, config, payload["fingerprint"])
    assert _tm(container).executions == [("DEMO-601", status, "Nota ficticia.")]


@pytest.mark.parametrize(
    "status",
    ["Pasó", "PASO", "passed", "ok", "", None, 1, "paso "],
    ids=["etiqueta", "mayusculas", "ingles", "otro", "vacio", "none", "numero", "espacio"],
)
def test_validate_results_rejects_unknown_status_value(status: Any) -> None:
    """RF-28: solo valen los valores de `ExecutionStatus`; la etiqueta de la UI no es un valor."""
    with pytest.raises(ExecutionRejectedError) as exc:
        validate_results(
            [{"case_key": "DEMO-601", "status": status, "evidence_md": ""}],
            _cases_rows(),  # type: ignore[arg-type]
        )
    assert str(exc.value) == "El resultado de DEMO-601 no es válido."


def test_validate_results_accepts_enum_members_as_status() -> None:
    """RF-28: un miembro de `ExecutionStatus` vale igual que su valor."""
    rows = validate_results(
        [{"case_key": "DEMO-601", "status": ExecutionStatus.NOT_RUN}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert rows == [{"case_key": "DEMO-601", "status": "sin-ejecutar", "evidence_md": ""}]


@pytest.mark.parametrize(
    "evidence",
    ["", "   ", "\n\t\n", "\x00\x07\x1b", None],
    ids=["vacia", "espacios", "saltos", "control", "none"],
)
def test_failed_case_without_real_evidence_is_rejected(evidence: Any) -> None:
    """RF-28 · UI.md §6.6: «Un caso fallido necesita evidencia»; solo blancos o caracteres de
    control no cuentan como evidencia."""
    with pytest.raises(ExecutionRejectedError) as exc:
        validate_results(
            [{"case_key": "DEMO-602", "status": "fallo", "evidence_md": evidence}],
            _cases_rows(),  # type: ignore[arg-type]
        )
    assert str(exc.value) == "Un caso fallido necesita evidencia (DEMO-602)."


@pytest.mark.parametrize("status", ["paso", "bloqueado", "sin-ejecutar"])
def test_non_failed_status_without_evidence_is_accepted(status: str) -> None:
    """UI.md §6.6: la evidencia es opcional salvo si el caso falla."""
    rows = validate_results(
        [{"case_key": "DEMO-603", "status": status}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert rows[0]["evidence_md"] == ""


def test_failed_case_without_evidence_never_reaches_jira(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-28 · principio 1: el borrador con un fallo sin evidencia no se aplica y, al aprobar la
    huella mostrada (la del borrador vacío), no hay nada que registrar."""
    config = _config()
    first = _start(graph, config)
    payload = _save(
        graph, config, results=[{"case_key": "DEMO-602", "status": "fallo", "evidence_md": ""}]
    )
    assert payload["error"] == "Un caso fallido necesita evidencia (DEMO-602)."
    assert payload["fingerprint"] == first["fingerprint"]
    _approve(graph, config, payload["fingerprint"])
    assert _payload(graph, config)["error"] == "Elige el resultado de al menos un caso."
    assert _tm(container).executions == []


# --- RF-28 · casos que no son de la HU y claves mal formadas -------------------------------------


@pytest.mark.parametrize(
    ("case_key", "shown"),
    [
        ("DEMO-699", "DEMO-699"),
        ("OTRO-601", "OTRO-601"),
        ("601", "601"),
        ("DEMO 601", "DEMO 601"),
        ("DEMO-601-X", "DEMO-601-X"),
        ("", "El caso"),
        (None, "El caso"),
        ("DEMO-" + "9" * 40, "DEMO-" + "9" * 15),
    ],
    ids=["otra-hu", "otro-proyecto", "sin-proyecto", "espacio", "sufijo", "vacia", "none", "larga"],
)
def test_case_key_outside_the_story_is_rejected_and_truncated(case_key: Any, shown: str) -> None:
    """RF-28: solo se registran subtareas CP leídas de la HU; el mensaje muestra como mucho 20
    caracteres de la clave recibida."""
    with pytest.raises(ExecutionRejectedError) as exc:
        validate_results(
            [{"case_key": case_key, "status": "paso"}],
            _cases_rows(),  # type: ignore[arg-type]
        )
    assert str(exc.value) == f"{shown} no es un caso de esta HU."


def test_case_key_is_normalized_before_matching() -> None:
    """RF-28: «  demo-601 » es la subtarea DEMO-601 (se quitan blancos y se pasa a mayúsculas)."""
    rows = validate_results(
        [{"case_key": "  demo-601 ", "status": "paso"}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert rows[0]["case_key"] == "DEMO-601"


def test_case_key_of_another_story_never_reaches_jira(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-28 · principio 1: una subtarea de otra HU (que existe en el fake) no se registra."""
    _tm(container).cases["DEMO-7"] = [
        IssueSummary(
            key="DEMO-701",
            summary="[CP-01] Otro ficticio",
            issue_type="Subtarea",
            status="Por hacer",
        )
    ]
    config = _config()
    _start(graph, config)
    payload = _save(graph, config, results=[{"case_key": "DEMO-701", "status": "paso"}])
    assert payload["error"] == "DEMO-701 no es un caso de esta HU."
    assert payload["results"] == []
    assert _tm(container).executions == []


@pytest.mark.parametrize("raw", ["", "DEMO", "demo 6", "6-DEMO", "DEMO-6; DEMO-7"])
def test_initial_state_rejects_invalid_story_key_in_spanish(raw: str) -> None:
    """RF-28: la clave de la HU se valida al abrir el registro (mensaje en español)."""
    with pytest.raises(ValueError, match="no es una clave de Jira válida"):
        initial_execution_state(OWNER, raw)


def test_initial_state_normalizes_story_key_and_project() -> None:
    """RF-28: « demo-6 » abre el registro de DEMO-6, del proyecto DEMO, vacío."""
    state = initial_execution_state(OWNER, " demo-6 ")
    assert state["story_key"] == "DEMO-6" and state["project"] == "DEMO"
    assert state["results"] == [] and state["decision"] is None


# --- principio 1 · la huella cambia con cualquier resultado o evidencia ---------------------------


@pytest.mark.parametrize(
    ("index", "status"),
    [
        (i, s.value)
        for i, row in enumerate(RESULTS)
        for s in ExecutionStatus
        if s.value != row["status"]
    ],
)
def test_fingerprint_changes_when_any_single_status_changes(index: int, status: str) -> None:
    """UI.md §5: cambiar el resultado de cualquier caso cambia la huella."""
    thread = str(uuid4())
    base = execution_fingerprint(_state(), thread)
    results = [dict(r) for r in RESULTS]
    results[index]["status"] = status
    assert execution_fingerprint(_state(results=results), thread) != base


@pytest.mark.parametrize("index", range(len(RESULTS)))
def test_fingerprint_changes_when_any_evidence_changes_by_one_char(index: int) -> None:
    """UI.md §5: un carácter más en la evidencia de cualquier caso cambia la huella."""
    thread = str(uuid4())
    base = execution_fingerprint(_state(), thread)
    results = [dict(r) for r in RESULTS]
    results[index]["evidence_md"] += "."
    assert execution_fingerprint(_state(results=results), thread) != base


def test_fingerprint_changes_when_a_case_is_added_or_removed() -> None:
    """UI.md §5: registrar un caso más o uno menos es otro registro."""
    thread = str(uuid4())
    base = execution_fingerprint(_state(), thread)
    fewer = execution_fingerprint(_state(results=[dict(r) for r in RESULTS[:2]]), thread)
    assert len({base, fewer}) == 2


def test_fingerprint_changes_with_owner_and_story() -> None:
    """UI.md §5: la huella liga el registro a la persona y a la HU."""
    thread = str(uuid4())
    base = execution_fingerprint(_state(), thread)
    other_user = execution_fingerprint(_state(user=OTHER), thread)
    other_story = execution_fingerprint(_state(story_key="DEMO-60"), thread)
    assert len({base, other_user, other_story}) == 3


def test_fingerprint_is_stable_for_same_draft_in_any_order_and_padding(
    graph: CompiledStateGraph,
) -> None:
    """UI.md §5: el mismo registro (aunque llegue en otro orden o con blancos alrededor de la
    evidencia) tiene la misma huella: se aprueba lo que llegará a Jira."""
    config = _config()
    _start(graph, config)
    first = _save(graph, config)["fingerprint"]
    reordered = [dict(r) for r in reversed(RESULTS)]
    reordered[1]["evidence_md"] = f"  {EVIDENCE}\n"
    assert _save(graph, config, results=reordered)["fingerprint"] == first


# --- principio 1 · aprobación de un solo uso y de la dueña ----------------------------------------


def test_approve_ignores_results_sent_with_the_approval(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Principio 1: aprobar no cambia el borrador; se escribe lo revisado, no lo que venga
    junto a la huella."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    smuggled = [{"case_key": "DEMO-601", "status": "fallo", "evidence_md": "Colado ficticio."}]
    _resume(
        graph,
        config,
        {"decision": "approve", "fingerprint": payload["fingerprint"], "results": smuggled},
    )
    written = _tm(container).executions
    assert [(k, s) for k, s, _e in written] == [(r["case_key"], r["status"]) for r in RESULTS]
    assert all("Colado" not in e for _k, _s, e in written)


@pytest.mark.parametrize(
    "fingerprint",
    [None, "", "0" * 64, ["x"], 123],
    ids=["none", "vacia", "ceros", "lista", "numero"],
)
def test_approve_with_wrong_fingerprint_stores_nothing(
    graph: CompiledStateGraph, container: Container, fingerprint: Any
) -> None:
    """UI.md §5: sin la huella exacta no se guarda aprobación ni se escribe."""
    config = _config()
    _start(graph, config)
    _save(graph, config)
    _approve(graph, config, fingerprint)
    assert _payload(graph, config)["error"] == MISMATCH
    assert _stored(container, config) == {}
    assert _tm(container).executions == []


def test_other_user_cannot_approve_owner_thread_and_owner_still_can(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Principio 1 · T-52: otra persona con la huella correcta recibe el mismo NotFoundError, no
    deja aprobación ni escribe; la dueña puede aprobar después."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    intruder = _config(user=OTHER, thread_id=_thread_id(config))
    with pytest.raises(NotFoundError) as exc:
        _approve(graph, intruder, payload["fingerprint"])
    assert str(exc.value) == NOT_YOURS
    assert _thread_id(config) not in str(exc.value)
    assert _stored(container, config) == {}
    assert _tm(container).executions == []

    _approve(graph, config, payload["fingerprint"])
    assert len(_tm(container).executions) == len(RESULTS)


def test_resume_after_recording_does_not_write_again(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Principio 1: reenviar la misma aprobación cuando el registro ya terminó no escribe."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    _approve(graph, config, payload["fingerprint"])
    assert len(_tm(container).executions) == len(RESULTS)
    _approve(graph, config, payload["fingerprint"])
    graph.invoke(None, config)
    assert len(_tm(container).executions) == len(RESULTS)


def test_publish_rejects_reused_approval_even_with_restored_state(container: Container) -> None:
    """Principio 1: tras registrar, ni el mismo estado ni la misma huella vuelven a escribir."""
    nodes = ExecutionNodes(container)
    config = _config()
    state = _state(decision="approve")
    fp = execution_fingerprint(state, _thread_id(config))
    container.state_store.save(_thread_id(config), {"execution": {"approved": fp, "used": False}})
    nodes.publish(state, config)  # type: ignore[arg-type]
    with pytest.raises(PublishError, match="aprobación humana vigente"):
        nodes.publish(dict(state), config)  # type: ignore[arg-type]
    assert len(_tm(container).executions) == len(RESULTS)


def test_approval_keeps_other_keys_of_the_thread_record(
    graph: CompiledStateGraph, container: Container
) -> None:
    """La aprobación propia vive en `execution` y no pisa otras claves del mismo registro."""
    config = _config()
    container.state_store.save(_thread_id(config), {"otra": {"dato": "ficticio"}})
    _start(graph, config)
    _approve(graph, config, _save(graph, config)["fingerprint"])
    stored = container.state_store.load(_thread_id(config)) or {}
    assert stored["otra"] == {"dato": "ficticio"}
    assert stored["execution"]["used"] is True
    assert stored["execution"]["approved_by"] == OWNER


# --- principio 1 · nada se escribe en Jira sin aprobación ----------------------------------------


def test_only_publish_writes_across_saves_rejections_and_discard(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Principio 1: cargar, guardar varias veces, respuestas no válidas y descartar no escriben."""
    config = _config()
    _start(graph, config)
    _save(graph, config)
    _save(graph, config, environment=ENVIRONMENT)
    _resume(graph, config, {"decision": "publish"})
    _resume(graph, config, {"decision": "save", "results": "no-lista"})
    _resume(graph, config, {"decision": "discard"})
    assert _tm(container).executions == []
    assert [e.action for e in _audit(container)] == ["discard"]
    assert _stored(container, config) == {}


def test_review_and_load_nodes_never_call_record_execution(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Principio 1: `load_cases` y `review` no tocan `record_execution` (solo `publish`)."""

    def forbidden(*_args: Any) -> None:
        raise AssertionError("escritura fuera de publish")

    monkeypatch.setattr(_tm(container), "record_execution", forbidden)
    g = build_execution_graph(container, checkpointer=memory_checkpointer())
    config = _config()
    _start(g, config)
    _save(g, config)
    _resume(g, config, {"decision": "discard"})


# --- simulación (T-25, UI.md §5.6 y §6.5) ---------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-177): en `simulation` el registro de la ejecución consume la aprobación "
        "(used=True), al contrario que el grafo de HU y que UI.md §5.6/§6.5 y SPEC-00 §11 (T-25: "
        "«no consume la aprobación») (core/graph/execution.py:295-297)"
    ),
)
def test_simulation_keeps_approval_valid_for_live(tmp_path: Path) -> None:
    """UI.md §5.6 · SPEC-00 §11 (T-25): en simulación no se escribe y la aprobación sigue
    vigente para publicar cuando se active el modo real."""
    container = fake_container(tmp_path, publish_mode="simulation")
    _tm(container).cases[STORY] = list(CASES)
    g = build_execution_graph(container, checkpointer=memory_checkpointer())
    config = _config()
    _start(g, config)
    _approve(g, config, _save(g, config)["fingerprint"])
    assert _tm(container).executions == []
    assert _stored(container, config).get("used") is False


def test_simulation_audit_plan_has_no_evidence_nor_environment(tmp_path: Path) -> None:
    """T-25 · RF-35: el recibo simulado de la auditoría lleva operaciones, sin textos."""
    container = fake_container(tmp_path, publish_mode="simulation")
    _tm(container).cases[STORY] = list(CASES)
    g = build_execution_graph(container, checkpointer=memory_checkpointer())
    config = _config()
    _start(g, config)
    _approve(g, config, _save(g, config, environment=ENVIRONMENT)["fingerprint"])
    dumped = " ".join(e.model_dump_json() for e in _audit(container))
    assert "ficticia-c4e9" not in dumped and "env-81" not in dumped
    assert _tm(container).executions == []


# --- evidencia: datos personales, secretos y enlaces ---------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-178): la evidencia llega a Jira sin revisar datos que parecen personales "
        "o secretos (email, DNI, cabecera Authorization), a diferencia de la suite (RF-25, "
        "RNF-06, CLAUDE.md principios 2 y 3) (core/graph/execution.py:167-174)"
    ),
)
@pytest.mark.parametrize(
    "evidence",
    [
        "La persona usuaria escribió soporte.ficticio@example.com y falló.",
        "Se introdujo el documento 12345678Z y la pantalla falló.",
        "Respuesta con Authorization: Bearer TOKEN_FICTICIO_0000000000000000",
    ],
    ids=["email", "dni", "authorization"],
)
def test_evidence_with_personal_data_or_secrets_is_rejected(evidence: str) -> None:
    """RF-25 · RNF-06: como en la suite, un texto que irá a Jira y parece un dato personal o un
    secreto se rechaza en la revisión con un motivo en español."""
    with pytest.raises(ExecutionRejectedError):
        validate_results(
            [{"case_key": "DEMO-602", "status": "fallo", "evidence_md": evidence}],
            _cases_rows(),  # type: ignore[arg-type]
        )


def test_fictitious_email_in_evidence_is_accepted() -> None:
    """RNF-06: un email de dominio reservado (example.com) es claramente ficticio y vale."""
    rows = validate_results(
        [
            {
                "case_key": "DEMO-602",
                "status": "fallo",
                "evidence_md": "Registro con persona.ficticia@example.com: no llega el aviso.",
            }
        ],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert "example.com" in rows[0]["evidence_md"]


def _links(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for mark in node.get("marks") or []:
            if mark.get("type") == "link":
                found.append(mark["attrs"]["href"])
        for child in node.get("content") or []:
            found += _links(child)
    return found


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "data:text/html,ficticio", "file:///c:/ficticio.txt", "ftp://x.test/a"],
    ids=["javascript", "data", "file", "ftp"],
)
def test_non_http_links_in_evidence_are_not_links_in_jira(url: str) -> None:
    """RNF-03 · PA-49: un enlace que no es http(s) en la evidencia llega a Jira como texto."""
    evidence = f"Ver [captura ficticia]({url})"
    rows = validate_results(
        [{"case_key": "DEMO-602", "status": "fallo", "evidence_md": evidence}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    adf = markdown_to_adf(evidence_for_jira(ENVIRONMENT, rows[0]["evidence_md"]))
    assert _links(adf) == []


def test_https_link_in_evidence_is_kept_as_link() -> None:
    """UI.md §6.6: «Enlace o nota»: un enlace https de la evidencia llega como enlace."""
    url = "https://example.com/capturas/ficticia-01.png"
    adf = markdown_to_adf(evidence_for_jira("", f"Ver [captura]({url})"))
    assert _links(adf) == [url]


# --- tamaños máximos ---------------------------------------------------------------------------


def test_evidence_limit_counts_after_removing_control_chars_and_padding() -> None:
    """Límite: los caracteres de control y los blancos de los extremos no cuentan."""
    raw = "  " + "x" * MAX_EVIDENCE_CHARS + "\x00\x07  "
    rows = validate_results(
        [{"case_key": "DEMO-602", "status": "fallo", "evidence_md": raw}],
        _cases_rows(),  # type: ignore[arg-type]
    )
    assert rows[0]["evidence_md"] == "x" * MAX_EVIDENCE_CHARS


def test_evidence_with_environment_exactly_at_limit_is_recorded(
    graph: CompiledStateGraph, container: Container
) -> None:
    """Límite: «Entorno: …» + evidencia con exactamente el máximo llega entera a Jira."""
    config = _config()
    _start(graph, config)
    prefix = len(evidence_for_jira(ENVIRONMENT, "x")) - 1
    evidence = "x" * (MAX_EVIDENCE_CHARS - prefix)
    row = {"case_key": "DEMO-602", "status": "fallo", "evidence_md": evidence}
    payload = _save(graph, config, results=[row], environment=ENVIRONMENT)
    assert payload["error"] is None
    _approve(graph, config, payload["fingerprint"])
    (written,) = _tm(container).executions
    assert len(written[2]) == MAX_EVIDENCE_CHARS


def test_one_char_over_limit_with_environment_is_rejected_in_review(
    graph: CompiledStateGraph,
) -> None:
    """Límite: un carácter más (con el entorno delante) se rechaza antes de aprobar."""
    config = _config()
    _start(graph, config)
    prefix = len(evidence_for_jira(ENVIRONMENT, "x")) - 1
    row = {
        "case_key": "DEMO-602",
        "status": "fallo",
        "evidence_md": "x" * (MAX_EVIDENCE_CHARS - prefix + 1),
    }
    payload = _save(graph, config, results=[row], environment=ENVIRONMENT)
    assert payload["error"] == (
        f"La evidencia de DEMO-602 con el entorno supera los {MAX_EVIDENCE_CHARS} caracteres."
    )


# --- RNF-13 · fallos parciales al escribir e idempotencia -----------------------------------------


def test_all_cases_failing_reports_each_and_uses_approval(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RNF-13: si fallan todos, nada consta como registrado, cada clave queda en `failed` con
    su mensaje en el mismo orden y la aprobación no se reutiliza."""
    _tm(container).fail_execution_keys = set(CASE_KEYS)
    config = _config()
    _start(graph, config)
    _approve(graph, config, _save(graph, config)["fingerprint"])
    values = graph.get_state(config).values
    assert values["recorded"] == []
    assert values["failed"] == CASE_KEYS
    assert values["errors"] == [f"No se pudo registrar la ejecución en {k}." for k in CASE_KEYS]
    assert _stored(container, config)["used"] is True
    publish = [e for e in _audit(container) if e.action == "publish"]
    assert publish[-1].jira_keys == [] and publish[-1].detail["recorded"] == 0


def test_middle_case_failure_does_not_stop_the_rest(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RNF-13: cada caso es independiente; el siguiente al que falla se registra."""
    _tm(container).fail_execution_keys = {"DEMO-602"}
    config = _config()
    _start(graph, config)
    _approve(graph, config, _save(graph, config)["fingerprint"])
    values = graph.get_state(config).values
    assert values["recorded"] == ["DEMO-601", "DEMO-603"]
    assert values["failed"] == ["DEMO-602"]
    assert [k for k, _s, _e in _tm(container).executions] == ["DEMO-601", "DEMO-603"]


def test_keyless_service_errors_stay_aligned_with_failed_keys(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-13 · SPEC-00 §8: un error del servicio sin clave se muestra tal cual (en español) y
    `errors` va en el mismo orden que `failed`, para que la UI sepa qué caso falló."""
    message = "No se pudo conectar con Jira. Revisa la URL del sitio y la red."

    def down(case_key: str, status: str, evidence_md: str) -> None:
        if case_key != "DEMO-601":
            raise ExternalServiceError(message, service="jira")
        _tm(container).executions.append((case_key, str(status), evidence_md))

    monkeypatch.setattr(_tm(container), "record_execution", down)
    config = _config()
    _start(graph, config)
    _approve(graph, config, _save(graph, config)["fingerprint"])
    values = graph.get_state(config).values
    assert values["failed"] == ["DEMO-602", "DEMO-603"]
    assert values["errors"] == [message, message]


def test_state_store_failure_before_writing_writes_nothing(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Principio 1 · RNF-13: si no se puede marcar la aprobación como usada, no se escribe."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    store = container.state_store
    original = store.save
    calls = {"n": 0}

    def flaky(thread_id: str, state: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # 1 = guardar la aprobación, 2 = marcarla usada
            raise ExternalServiceError("No se pudo guardar el estado del artefacto.")
        original(thread_id, state)

    monkeypatch.setattr(store, "save", flaky)
    with pytest.raises(ExternalServiceError, match="No se pudo guardar"):
        _approve(graph, config, payload["fingerprint"])
    assert _tm(container).executions == []


def test_audit_failure_after_writing_never_repeats_writes(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-13 · principio 1: si la auditoría falla tras escribir, reintentar el nodo `publish`
    no repite ninguna escritura (la aprobación ya está usada)."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    audit = container.audit
    original = audit.record

    def broken(entry: AuditEntry) -> None:
        if entry.action == "publish":
            raise ExternalServiceError("No se pudo guardar la auditoría.")
        original(entry)

    monkeypatch.setattr(audit, "record", broken)
    with pytest.raises(ExternalServiceError):
        _approve(graph, config, payload["fingerprint"])
    assert len(_tm(container).executions) == len(RESULTS)
    monkeypatch.setattr(audit, "record", original)
    with pytest.raises(PublishError, match="aprobación humana vigente"):
        graph.invoke(None, config)
    assert len(_tm(container).executions) == len(RESULTS)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-35 (PA-179): si falla el guardado final en `state_store` tras escribir en Jira, "
        "la entrada `publish` de la auditoría no se registra: en el `finally` `_save` va antes que "
        "`_audit` (el grafo de HU audita primero) (core/graph/execution.py:328-335)"
    ),
)
def test_writes_are_audited_even_if_final_state_save_fails(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-13 · RF-35: lo ya escrito en Jira queda en la auditoría aunque falle el almacén al
    guardar el resultado final («no deja escrituras sin informar»)."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    store = container.state_store
    original = store.save
    calls = {"n": 0}

    def flaky(thread_id: str, state: dict[str, Any]) -> None:
        calls["n"] += 1
        if calls["n"] == 3:  # 1 = aprobación, 2 = usada, 3 = resultado final
            raise ExternalServiceError("No se pudo guardar el estado del artefacto.")
        original(thread_id, state)

    monkeypatch.setattr(store, "save", flaky)
    with pytest.raises(ExternalServiceError):
        _approve(graph, config, payload["fingerprint"])
    assert len(_tm(container).executions) == len(RESULTS)
    publish = [e for e in _audit(container) if e.action == "publish"]
    assert publish and publish[-1].jira_keys == CASE_KEYS


# --- mensajes en español sin datos internos y auditoría sin contenido -----------------------------


def test_unexpected_error_text_is_hidden_from_errors_audit_and_logs(
    graph: CompiledStateGraph, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SPEC-00 §8 · CLAUDE.md (logs): un error no previsto se muestra con un mensaje genérico en
    español y su texto no llega al estado, a la auditoría ni a los logs."""

    def boom(case_key: str, status: str, evidence_md: str) -> None:
        raise RuntimeError("traza-interna-ficticia http://interno.invalid/x")

    monkeypatch.setattr(_tm(container), "record_execution", boom)
    config = _config()
    _start(graph, config)
    payload = _save(graph, config)
    with capture_logs() as logs:
        _approve(graph, config, payload["fingerprint"])
    values = graph.get_state(config).values
    assert values["errors"] == [f"No se pudo registrar el resultado en {k}." for k in CASE_KEYS]
    dumped = " ".join(e.model_dump_json() for e in _audit(container)) + repr(logs)
    assert "traza-interna" not in dumped


def test_audit_and_logs_never_contain_evidence_or_environment(
    graph: CompiledStateGraph, container: Container
) -> None:
    """RF-35 · CLAUDE.md (logs): aprobar, publicar y descartar se auditan con claves y
    recuentos; ni la evidencia ni el entorno van a la auditoría ni a los logs."""
    config = _config()
    _start(graph, config)
    payload = _save(graph, config, environment=ENVIRONMENT)
    with capture_logs() as logs:
        _approve(graph, config, payload["fingerprint"])
    other = _config()
    _start(graph, other)
    _save(graph, other, environment=ENVIRONMENT)
    _resume(graph, other, {"decision": "discard"})

    entries = _audit(container)
    assert [e.action for e in entries] == ["approve", "publish", "discard"]
    assert all(e.artifact_id is None and e.detail["execution"] is True for e in entries)
    assert entries[2].detail["cases"] == len(RESULTS)
    dumped = " ".join(e.model_dump_json() for e in entries) + repr(logs)
    for secret_like in ("ficticia-c4e9", "env-81", "Entorno ficticio caído"):
        assert secret_like not in dumped
    assert any(log.get("action") == "record_execution" for log in logs)
    assert all(log.get("user") == OWNER for log in logs if log.get("action"))


def test_receipt_plan_never_carries_evidence_text() -> None:
    """RF-31: el recibo dice si hay evidencia, nunca su texto ni el entorno."""
    plan = execution_plan(_state(environment=ENVIRONMENT))
    assert [op["evidence"] for op in plan] == ["no", "sí", "sí"]
    assert all(set(op) == {"op", "key", "status", "label", "evidence"} for op in plan)
    assert "ficticia-c4e9" not in str(plan) and "env-81" not in str(plan)


@pytest.mark.parametrize(
    "answer",
    [
        {"decision": "save", "results": [{"case_key": "DEMO-601", "status": "x"}]},
        {"decision": "save", "results": RESULTS, "environment": "e" * 101},
        {"decision": "approve", "fingerprint": "f" * 64},
        {"decision": "otra"},
    ],
    ids=["estado", "entorno", "huella", "decision"],
)
def test_review_errors_are_spanish_and_have_no_internal_data(
    graph: CompiledStateGraph, answer: dict[str, Any]
) -> None:
    """SPEC-00 §8: los motivos de la revisión son frases en español sin trazas, hilos ni
    nombres de clases."""
    config = _config()
    _start(graph, config)
    _save(graph, config)
    _resume(graph, config, answer)
    error = _payload(graph, config)["error"]
    assert error and error[0].isupper() and error.endswith(".")
    for internal in (_thread_id(config), "Traceback", "Error", "ExecutionStatus", "{", "'"):
        assert internal not in error
