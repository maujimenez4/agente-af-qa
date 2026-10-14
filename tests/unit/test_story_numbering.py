"""PA-202 (R-05) · Una HU nueva recibe su número `HU-NN` antes de la revisión.

El núcleo lee los títulos `[HU-NN]` del proyecto en Jira (solo lectura) y asigna el siguiente libre;
se respeta el del modelo si es válido y está libre, y una iteración conserva el suyo. Datos
ficticios: el `FakeIssueTracker` ya tiene `[HU-01]`…`[HU-03]` en DEMO.
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from structlog.testing import capture_logs

from adapters.base import IssueDetail, IssueSummary
from adapters.errors import ExternalServiceError
from adapters.jira.story_template import story_summary
from core.approvals import content_fingerprint
from core.container import Container
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import next_story_id
from schemas.user_story import UserStory
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider

AF_USER = "af-demo"
NEED: Origin = {"kind": "need", "text": "Avisar del vencimiento de un préstamo", "project": "DEMO"}
STORY: Origin = {"kind": "story", "key": "DEMO-3"}  # «[HU-02] Renovar un préstamo»
FEEDBACK = "Añade un criterio sobre el aviso por correo (ficticio)."


def _llm_with_id(internal_id: str | None) -> FakeLLMProvider:
    """LLM falso cuyas HU traen el `internal_id` indicado (como si lo pusiera el modelo)."""
    llm = FakeLLMProvider()
    original = llm.builders[UserStory]

    def build(messages: list[Any]) -> UserStory:
        return original(messages).model_copy(update={"internal_id": internal_id})

    llm.builders[UserStory] = build
    return llm


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _start(
    tmp_path: Path, origin: Origin = NEED, **overrides: Any
) -> tuple[Container, CompiledStateGraph, dict[str, Any]]:
    container = fake_container(tmp_path, publish_mode="live", **overrides)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-pa202"}}
    graph.invoke(initial_state(AF_USER, "functional", origin), config)
    return container, graph, config


def _proposed_id(graph: CompiledStateGraph, config: dict[str, Any]) -> str | None:
    return _pending(graph, config)["artifact"]["content"]["internal_id"]


def _tracker(container: Container) -> FakeIssueTracker:
    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    return tracker


# --- next_story_id -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model_id", "taken", "expected"),
    [
        (None, {1, 2, 3}, "HU-04"),
        ("HU-07", {1, 2, 3}, "HU-07"),  # válido y libre: se respeta
        ("HU-02", {1, 2, 3}, "HU-04"),  # choca: se reasigna
        ("CP-01", {1}, "HU-02"),  # sin formato HU-NN
        ("HU-0", set(), "HU-01"),
        (None, set(), "HU-01"),
        (None, {9, 120}, "HU-121"),
        ("HU-7", {1}, "HU-07"),  # el del modelo, normalizado a dos cifras
        ("HU-\u0663", set(), "HU-01"),  # un dígito de otra escritura no es un número
        (None, {9999}, None),  # sin números libres en el rango: no se repite HU-10000
        ("HU-10000", {1}, "HU-02"),
    ],
)
def test_next_story_id(model_id: str | None, taken: set[int], expected: str | None) -> None:
    assert next_story_id(model_id, taken) == expected


# --- Grafo ---------------------------------------------------------------------------------------


def test_new_story_gets_next_free_number_and_is_published_with_prefix(tmp_path: Path) -> None:
    container, graph, config = _start(tmp_path, llm=_llm_with_id(None))
    assert _proposed_id(graph, config) == "HU-04"

    fingerprint = _pending(graph, config)["fingerprint"]
    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": fingerprint}), config
    )

    story = final["artifact"].content
    assert story_summary(story).startswith("[HU-04] ")  # el título que publica el tracker real
    created = [k for k, i in _tracker(container).issues.items() if i.summary.startswith("[HU-04] ")]
    assert len(created) == 1


def test_number_is_part_of_the_approved_fingerprint(tmp_path: Path) -> None:
    _container, graph, config = _start(tmp_path)
    artifact = graph.get_state(config).values["artifact"]
    assert artifact.content.internal_id == "HU-04"
    other = artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"internal_id": "HU-05"})}
    )
    assert content_fingerprint(artifact) != content_fingerprint(other)


def test_model_id_that_clashes_is_reassigned(tmp_path: Path) -> None:
    _container, graph, config = _start(tmp_path, llm=_llm_with_id("HU-02"))
    assert _proposed_id(graph, config) == "HU-04"


def test_free_model_id_is_respected(tmp_path: Path) -> None:
    _container, graph, config = _start(tmp_path, llm=_llm_with_id("HU-07"))
    assert _proposed_id(graph, config) == "HU-07"


def test_out_of_range_numbers_in_jira_are_ignored(tmp_path: Path) -> None:
    tracker = FakeIssueTracker()
    tracker.issues["DEMO-90"] = IssueDetail(
        key="DEMO-90",
        summary="[HU-999999] Puesta a mano (ficticia)",
        issue_type="Story",
        status="Por hacer",
    )
    with capture_logs() as logs:
        _container, graph, config = _start(tmp_path, issue_tracker=tracker)
    assert _proposed_id(graph, config) == "HU-04"
    assert any(e.get("action") == "number_story" for e in logs)


def test_iteration_keeps_its_number_even_if_jira_changes(tmp_path: Path) -> None:
    container, graph, config = _start(tmp_path)
    assert _proposed_id(graph, config) == "HU-04"
    _tracker(container).issues["DEMO-91"] = IssueDetail(
        key="DEMO-91",
        summary="[HU-04] Otra HU publicada entre tanto",
        issue_type="Story",
        status="Por hacer",
    )
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    assert _proposed_id(graph, config) == "HU-04"


class DownForSearch(FakeIssueTracker):
    """Jira no responde a la búsqueda de números (sí a lo demás)."""

    def __init__(self) -> None:
        super().__init__()
        self.down = True

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        if self.down and jql.endswith("ORDER BY key DESC"):
            raise ExternalServiceError("Jira no responde (ficticio).", service="jira")
        return super().search(jql, limit)


def test_jira_down_does_not_block_and_drops_unverified_model_id(tmp_path: Path) -> None:
    with capture_logs() as logs:
        _container, graph, config = _start(
            tmp_path, issue_tracker=DownForSearch(), llm=_llm_with_id("HU-07")
        )
    assert _proposed_id(graph, config) is None  # sin número, como antes de PA-202
    (warning,) = [e for e in logs if e.get("action") == "number_story"]
    assert warning["log_level"] == "warning" and warning["error_type"] == "ExternalServiceError"


def test_jira_down_on_iteration_keeps_previous_number(tmp_path: Path) -> None:
    tracker = DownForSearch()
    tracker.down = False
    _container, graph, config = _start(tmp_path, issue_tracker=tracker)
    assert _proposed_id(graph, config) == "HU-04"
    tracker.down = True
    graph.invoke(Command(resume={"decision": "iterate", "feedback": FEEDBACK}), config)
    assert _proposed_id(graph, config) == "HU-04"


# --- Regresión: las HU sembradas con número --------------------------------------------------


def test_evolving_seeded_story_keeps_its_number(tmp_path: Path) -> None:
    """DEMO-3 es «[HU-02] …»: al evolucionarla conserva HU-02 y se publica con ese prefijo."""
    container, graph, config = _start(tmp_path, origin=STORY)
    assert _proposed_id(graph, config) == "HU-02"

    fingerprint = _pending(graph, config)["fingerprint"]
    final = graph.invoke(
        Command(resume={"decision": "approve", "fingerprint": fingerprint}), config
    )

    assert story_summary(final["artifact"].content).startswith("[HU-02] ")
    assert ("update_story", {"key": "DEMO-3"}) in _tracker(container).writes


def test_numbering_writes_nothing_in_jira_before_approval(tmp_path: Path) -> None:
    """Principio 1: numerar solo lee de Jira; antes de aprobar no hay ninguna escritura."""
    container, graph, config = _start(tmp_path)
    assert _proposed_id(graph, config) == "HU-04"
    assert _tracker(container).writes == []


def test_published_prefix_ignores_digits_of_other_scripts() -> None:
    """Un `internal_id` con un dígito de otra escritura no se publica como prefijo."""
    story = UserStory.model_validate(
        _llm_with_id(None).builders[UserStory]([]).model_dump()
        | {"internal_id": "HU-" + chr(0x0663)}
    )
    assert not story_summary(story).startswith("[HU-")
