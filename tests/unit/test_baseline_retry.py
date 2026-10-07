"""PA-339 · Un reintento de la primera versión no vuelve a estructurar la HU de Jira.

`structure_story` (40–50 s con el modelo local) pasa la HU de origen a la plantilla. Si la
primera versión falla o se detiene después, el reintento reutiliza esa versión de partida
guardada por conversación, salvo que la incidencia de origen haya cambiado. Datos ficticios.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from langgraph.graph.state import CompiledStateGraph

import core.graph.nodes as nodes
from adapters.base import Message
from core.artifact_state import InMemoryArtifactStateStore
from core.container import Container
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import _pending_baseline_key
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider

STRUCTURE_MARK = "Pasas a la plantilla"  # prompts/structure_story.md
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}


class Flaky:
    """Hace fallar la primera llamada que no es de estructuración (el paso siguiente)."""

    def __init__(self, original: Callable[[list[Message]], Any]) -> None:
        self.original = original
        self.failing = True

    def __call__(self, messages: list[Message]) -> Any:
        if self.failing and STRUCTURE_MARK not in messages[0].content:
            raise RuntimeError("generación detenida (ficticio)")
        return self.original(messages)


def _structure_calls(llm: FakeLLMProvider) -> int:
    return sum(1 for c in llm.calls if c["messages"] and STRUCTURE_MARK in c["messages"][0].content)


def _setup(
    tmp_path: Path, schema: type, thread: str
) -> tuple[FakeLLMProvider, Flaky, Container, CompiledStateGraph, dict[str, Any]]:
    llm = FakeLLMProvider()
    flaky = Flaky(llm.builders[schema])
    llm.builders[schema] = flaky
    container = fake_container(tmp_path, llm=llm)
    graph = build_graph(container)
    return llm, flaky, container, graph, {"configurable": {"thread_id": thread}}


def _store(container: Container) -> InMemoryArtifactStateStore:
    store = container.state_store
    assert isinstance(store, InMemoryArtifactStateStore)
    return store


def test_retry_after_failed_evolution_does_not_structure_again(tmp_path: Path) -> None:
    """PA-339: detenida la evolución tras estructurar, el reintento no llama a structure_story."""
    llm, flaky, container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-hu")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    assert _structure_calls(llm) == 1

    flaky.failing = False
    graph.invoke(None, config)  # reintento del mismo paso en el mismo hilo

    assert _structure_calls(llm) == 1
    artifact = graph.get_state(config).values["artifact"]
    assert artifact is not None and artifact.version == 1
    # La versión de partida queda en el artefacto y la de la conversación se borra.
    store = _store(container)
    assert "baseline" in store.states[str(artifact.id)]
    pending = _pending_baseline_key(config)
    assert pending is not None and "baseline" not in (store.load(pending) or {})


def test_retry_after_failed_suite_does_not_structure_again(tmp_path: Path) -> None:
    """PA-339: también en QA, que estructura la HU antes de escribir la suite (PA-61)."""
    llm, flaky, _container, graph, config = _setup(tmp_path, TestSuite, "hilo-pa339-qa")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("qa-demo", "qa", STORY_ORIGIN), config)
    assert _structure_calls(llm) == 1

    flaky.failing = False
    graph.invoke(None, config)

    assert _structure_calls(llm) == 1
    assert graph.get_state(config).values["artifact"] is not None


def test_changed_origin_issue_is_structured_again(tmp_path: Path) -> None:
    """PA-339: si la HU de Jira cambió entre intentos, no se reutiliza la estructura vieja."""
    llm, flaky, _container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-cambio")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    jira = graph.get_state(config).values["jira_context"]
    changed = [
        i.model_copy(update={"summary": i.summary + " (editada en Jira)"})
        if i.key == "DEMO-3"
        else i
        for i in jira
    ]
    graph.update_state(config, {"jira_context": changed}, as_node="retrieve_context")

    flaky.failing = False
    graph.invoke(None, config)

    assert _structure_calls(llm) == 2


def _shared_ids(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """PA-432: anota los ids de la estructura compartida que calcula `_baseline`."""
    ids: list[str | None] = []
    original = nodes._shared_baseline_id

    def spy(issue_key: str | None, origin_only: Any) -> str | None:
        ids.append(original(issue_key, origin_only))
        return ids[-1]

    monkeypatch.setattr(nodes, "_shared_baseline_id", spy)
    return ids


def test_invalid_saved_baseline_uses_shared_structure_when_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-339 · PA-432: una versión de partida guardada que no valida no se usa; si hay una
    estructura compartida válida de la misma HU, se usa esa (sin llamar al modelo)."""
    ids = _shared_ids(monkeypatch)
    llm, flaky, container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-danada")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    store, pending = _store(container), _pending_baseline_key(config)
    assert pending is not None
    saved = store.load(pending) or {}
    store.save(pending, {**saved, "baseline": {"title": 1}})
    shared = store.load(ids[0] or "") or {}

    flaky.failing = False
    graph.invoke(None, config)

    assert _structure_calls(llm) == 1
    artifact = graph.get_state(config).values["artifact"]
    assert store.states[str(artifact.id)]["baseline"] == shared["baseline"]


def test_invalid_saved_baseline_is_structured_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-339: una versión de partida guardada que no valida no se usa; sin estructura
    compartida (PA-432) se vuelve a pedir."""
    ids = _shared_ids(monkeypatch)
    llm, flaky, container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-danada-2")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    store, pending = _store(container), _pending_baseline_key(config)
    assert pending is not None
    saved = store.load(pending) or {}
    store.save(pending, {**saved, "baseline": {"title": 1}})
    store.states.pop(ids[0] or "")

    flaky.failing = False
    graph.invoke(None, config)

    assert _structure_calls(llm) == 2


def test_other_conversation_reuses_shared_structure_when_unchanged(tmp_path: Path) -> None:
    """PA-432: la versión de partida de la conversación es suya (PA-339), pero otra
    conversación sobre la misma HU sin cambios reutiliza la estructura compartida."""
    llm, flaky, _container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-a")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    flaky.failing = False

    graph.invoke(
        initial_state("af-demo", "functional", STORY_ORIGIN),
        {"configurable": {"thread_id": "hilo-pa339-b"}},
    )

    assert _structure_calls(llm) == 1


def test_other_conversation_structures_again_when_story_changed(tmp_path: Path) -> None:
    """PA-339 · PA-432: si la HU cambió en Jira, la otra conversación estructura la suya."""
    llm, flaky, container, graph, config = _setup(tmp_path, UserStory, "hilo-pa339-c")
    with pytest.raises(RuntimeError):
        graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    flaky.failing = False
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    tracker.issues["DEMO-3"].summary += " (editada en Jira)"

    graph.invoke(
        initial_state("af-demo", "functional", STORY_ORIGIN),
        {"configurable": {"thread_id": "hilo-pa339-d"}},
    )

    assert _structure_calls(llm) == 2


@pytest.mark.parametrize("thread_id", [None, "", "con espacios", "x" * 65])
def test_pending_key_requires_valid_thread(thread_id: str | None) -> None:
    assert _pending_baseline_key({"configurable": {"thread_id": thread_id}}) is None
    assert _pending_baseline_key(None) is None


def test_pending_key_is_stable_per_thread() -> None:
    a = _pending_baseline_key({"configurable": {"thread_id": "hilo-a"}})
    assert a == _pending_baseline_key({"configurable": {"thread_id": "hilo-a"}})
    assert a != _pending_baseline_key({"configurable": {"thread_id": "hilo-b"}})
