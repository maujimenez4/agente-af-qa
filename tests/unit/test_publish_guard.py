"""PA-141: una sola publicación a la vez por artefacto y auditoría antes de consumir.

Grafo real con los fakes en `live` (el Jira de los fakes es de mentira). Datos ficticios.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from core.approvals import ApprovalError
from core.container import Container
from core.graph import build_graph, initial_state, memory_checkpointer
from core.graph.nodes import _target
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker

USER = "af-demo"


def _config() -> dict[str, Any]:
    return {"configurable": {"thread_id": str(uuid4()), "user": USER}}


def _in_review(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
    graph.invoke(initial_state(USER, "functional", origin), config)  # type: ignore[arg-type]
    tasks = graph.get_state(config).tasks
    return next(i.value for t in tasks for i in t.interrupts)


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path, publish_mode="live")


@pytest.fixture
def graph(container: Container) -> CompiledStateGraph:
    return build_graph(container, memory_checkpointer())


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def test_second_publish_while_one_is_running_writes_nothing(
    container: Container, graph: CompiledStateGraph
) -> None:
    """Mientras hay una publicación en curso del artefacto, otra falla antes de escribir."""
    config = _config()
    payload = _in_review(graph, config)
    graph.invoke(Command(resume={"decision": "approve", "fingerprint": "0" * 64}), config)
    values = graph.get_state(config).values
    artifact, state = values["artifact"], dict(values)
    # Se simula la publicación en curso reservando el artefacto en el registro.
    ledger = container.approvals
    target = _target(state, config, container.require_actor)  # type: ignore[arg-type]
    with ledger.publishing(artifact, target), pytest.raises(ApprovalError):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]}),
            config,
        )
    assert _tracker(container).writes == []


def test_writes_are_audited_even_if_consuming_the_approval_fails(
    container: Container, graph: CompiledStateGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auditoría antes del consumo: si `consume` falla, lo escrito en Jira ya consta."""
    config = _config()
    payload = _in_review(graph, config)

    def failing_consume(*_a: object, **_k: object) -> None:
        raise ApprovalError("Consumo ficticio rechazado.")

    monkeypatch.setattr(container.approvals, "consume", failing_consume)
    with pytest.raises(ApprovalError):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]}),
            config,
        )
    assert _tracker(container).writes  # se llegó a escribir en el Jira de los fakes
    actions = [e.action for e in container.audit.recorded]  # type: ignore[attr-defined]
    assert "publish" in actions


def test_publishing_releases_the_artifact_after_an_error(
    container: Container, graph: CompiledStateGraph
) -> None:
    """El cerrojo se libera aunque la publicación falle: se puede volver a intentar."""
    config = _config()
    _in_review(graph, config)
    values = graph.get_state(config).values
    artifact, ledger = values["artifact"], container.approvals
    target = _target(dict(values), config, container.require_actor)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError), ledger.publishing(artifact, target):
        raise RuntimeError("fallo ficticio")
    with ledger.publishing(artifact, target):  # vuelve a estar libre
        pass


def test_retry_after_a_failed_consume_does_not_write_again(
    container: Container, graph: CompiledStateGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-1: si el consumo falla tras escribir, la aprobación queda gastada y no se reescribe."""
    config = _config()
    payload = _in_review(graph, config)
    original = container.approvals.consume

    def failing_consume(*_a: object, **_k: object) -> None:
        raise ApprovalError("Consumo ficticio rechazado.")

    monkeypatch.setattr(container.approvals, "consume", failing_consume)
    answer = {"decision": "approve", "fingerprint": payload["fingerprint"]}
    with pytest.raises(ApprovalError):
        graph.invoke(Command(resume=answer), config)
    writes = len(_tracker(container).writes)
    monkeypatch.setattr(container.approvals, "consume", original)
    values = graph.get_state(config).values
    target = _target(dict(values), config, container.require_actor)  # type: ignore[arg-type]
    assert container.approvals.find(values["artifact"], target) is None
    assert len(_tracker(container).writes) == writes


def test_interrupted_write_is_audited_before_the_error(
    container: Container, graph: CompiledStateGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M-2 (RNF-13): una escritura que lanza a mitad deja su rastro en la auditoría."""
    config = _config()
    payload = _in_review(graph, config)

    def broken_update(*_a: object, **_k: object) -> None:
        raise RuntimeError("fallo ficticio a mitad")

    monkeypatch.setattr(_tracker(container), "update_story", broken_update)
    with pytest.raises(RuntimeError):
        graph.invoke(
            Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]}),
            config,
        )
    entries = [e for e in container.audit.recorded if e.action == "publish"]  # type: ignore[attr-defined]
    assert entries and entries[-1].detail.get("interrupted") is True
    assert entries[-1].detail.get("error_type") == "RuntimeError"


def test_simulation_inside_publishing_writes_and_consumes_nothing(tmp_path: Path) -> None:
    """Simulación: sin escrituras ni consumo; la reserva se libera y la aprobación sigue vigente."""
    container = fake_container(tmp_path, publish_mode="simulation")
    graph = build_graph(container, memory_checkpointer())
    config = _config()
    payload = _in_review(graph, config)
    graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": payload["fingerprint"]}), config
    )
    values = graph.get_state(config).values
    target = _target(dict(values), config, container.require_actor)  # type: ignore[arg-type]
    assert _tracker(container).writes == []
    assert container.approvals.find(values["artifact"], target) is not None
    with container.approvals.publishing(values["artifact"], target):
        pass  # la reserva está libre
