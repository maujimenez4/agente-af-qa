"""PA-450 · Una segunda suite de la misma HU continúa la numeración y se publica de verdad.

La numeración se decide en `generate` (antes de la revisión), leyendo los `[CP-XX]` que la HU ya
tiene en Jira; `publish_suite` (también el fake, idempotente como el real) reutiliza solo los CP
de la misma suite y trata como conflicto los de otra. Datos ficticios (proyecto DEMO).
"""

from pathlib import Path
from typing import Any

import pytest
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from adapters.base import IssueSummary
from adapters.errors import ExternalServiceError, PublishError
from core.graph import Origin, build_graph, initial_state
from core.graph.nodes import _apply_case_ids, renumber_cases
from schemas.common import ArtifactStatus
from schemas.test_case import TestSuite
from tests.fakes.container import fake_container
from tests.fakes.llm import renewal_test_suite
from tests.fakes.test_management import FakeTestManagement

QA_USER = "qa-demo"
STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}


# --- renumber_cases / _apply_case_ids ---------------------------------------------------------


def test_no_clash_keeps_every_id() -> None:
    assert renumber_cases(["CP-01", "CP-02"], {5, 6}) == {}
    assert renumber_cases(["CP-01"], set()) == {}


def test_clashing_ids_continue_after_highest_number() -> None:
    assert renumber_cases(["CP-01", "CP-02", "CP-03"], {1, 2, 3, 4, 5, 6}) == {
        "CP-01": "CP-07",
        "CP-02": "CP-08",
        "CP-03": "CP-09",
    }


def test_only_clashing_ids_change_and_kept_ones_are_respected() -> None:
    """Al iterar, un caso que ya tenía CP-07 lo conserva; el nuevo CP-01 pasa tras el mayor."""
    assert renumber_cases(["CP-07", "CP-01"], {1, 2, 3, 4, 5, 6}) == {"CP-01": "CP-08"}


def test_apply_case_ids_changes_ids_and_mentions_but_not_criteria() -> None:
    suite = renewal_test_suite()
    first = suite.cases[0]
    gherkin = f"# {first.internal_id}\nEscenario: {first.title}"
    suite = suite.model_copy(
        update={
            "cases": [first.model_copy(update={"gherkin": gherkin}), *suite.cases[1:]],
            "strategy_md": f"Priorizar {first.internal_id}; CP-010 no es un caso.",
        }
    )
    mapping = {c.internal_id: f"CP-{i:02d}" for i, c in enumerate(suite.cases, 7)}

    renamed = _apply_case_ids(suite, mapping)

    assert [c.internal_id for c in renamed.cases] == list(mapping.values())
    assert renamed.cases[0].gherkin is not None and "# CP-07" in renamed.cases[0].gherkin
    assert renamed.strategy_md == "Priorizar CP-07; CP-010 no es un caso."
    assert [c.criterion_ids for c in renamed.cases] == [c.criterion_ids for c in suite.cases]
    assert "CP-07" in renamed.coverage_md()


def test_apply_case_ids_keeps_story_key_and_sources() -> None:
    """Una clave de un proyecto `CP` (HU o fuente) no se toma por un ID de caso."""
    suite = renewal_test_suite().model_copy(update={"story_jira_key": "CP-01"})
    sources = [s.model_copy(update={"ref": "CP-02"}) for s in suite.sources[:1]]
    suite = suite.model_copy(update={"sources": sources})
    renamed = _apply_case_ids(suite, {"CP-01": "CP-07", "CP-02": "CP-08"})
    assert renamed.story_jira_key == "CP-01"
    assert [s.ref for s in renamed.sources] == [s.ref for s in sources]


def test_out_of_range_case_number_in_jira_is_ignored(tmp_path: Path) -> None:
    """Un `[CP-999999]` puesto a mano en Jira no dispara la numeración a CP-1000000."""
    cases = [
        IssueSummary(key="DEMO-21", summary="[CP-01] A", issue_type="Subtarea", status="Por hacer"),
        IssueSummary(
            key="DEMO-22", summary="[CP-999999] Raro", issue_type="Subtarea", status="Por hacer"
        ),
    ]
    graph = build_graph(
        fake_container(tmp_path, test_management=FakeTestManagement(cases={"DEMO-3": cases}))
    )
    _config, suite = _qa_conversation(graph, "hilo-qa-rango")
    # CP-02 no choca y se conserva; CP-01 choca y pasa al siguiente libre (no a CP-1000000).
    assert [c.internal_id for c in suite.cases] == ["CP-03", "CP-02"]


# --- Grafo -------------------------------------------------------------------------------------


def _pending(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    return task.interrupts[-1].value


def _qa_conversation(graph: CompiledStateGraph, thread: str) -> tuple[dict[str, Any], TestSuite]:
    config = {"configurable": {"thread_id": thread}}
    graph.invoke(initial_state(QA_USER, "qa", STORY_ORIGIN), config)
    payload = _pending(graph, config)
    return config, TestSuite.model_validate(payload["artifact"]["content"])


def _approve(graph: CompiledStateGraph, config: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _pending(graph, config)["fingerprint"]
    return graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), config)


def test_second_suite_of_same_story_continues_numbering_and_is_published(tmp_path: Path) -> None:
    """PA-450: la segunda conversación de QA de DEMO-3 propone CP-03… (no CP-01…), se aprueba
    con esos IDs y se publica entera, sin tocar los casos de la primera."""
    testmgmt = FakeTestManagement()
    graph = build_graph(fake_container(tmp_path, test_management=testmgmt))

    first_config, first_suite = _qa_conversation(graph, "hilo-qa-uno")
    first = _approve(graph, first_config)
    assert [c.internal_id for c in first_suite.cases] == ["CP-01", "CP-02"]
    assert first["artifact"].status is ArtifactStatus.PUBLISHED

    second_config, second_suite = _qa_conversation(graph, "hilo-qa-dos")
    assert [c.internal_id for c in second_suite.cases] == ["CP-03", "CP-04"]
    second = _approve(graph, second_config)

    assert second["artifact"].status is ArtifactStatus.PUBLISHED
    assert second["artifact"].content == second_suite  # lo aprobado es lo publicado
    assert set(second["published_keys"]).isdisjoint(first["published_keys"])
    summaries = [c.summary[:7] for c in testmgmt.list_cases("DEMO-3")]
    assert summaries == ["[CP-01]", "[CP-02]", "[CP-03]", "[CP-04]"]
    assert "CP-03" in testmgmt.attachments["DEMO-3"]["matriz-DEMO-3.md"]


def test_legacy_cases_without_suite_label_are_skipped_by_numbering(tmp_path: Path) -> None:
    """PA-450 (caso real: AFQP-27 ya tiene CP-01…CP-06): la suite nueva empieza en CP-07."""
    legacy = [
        IssueSummary(
            key=f"DEMO-{20 + i}",
            summary=f"[CP-0{i}] Antiguo",
            issue_type="Subtarea",
            status="Por hacer",
        )
        for i in range(1, 7)
    ]
    testmgmt = FakeTestManagement(cases={"DEMO-3": legacy})
    graph = build_graph(fake_container(tmp_path, test_management=testmgmt))

    config, suite = _qa_conversation(graph, "hilo-qa-legado")
    final = _approve(graph, config)

    assert [c.internal_id for c in suite.cases] == ["CP-07", "CP-08"]
    assert final["artifact"].status is ArtifactStatus.PUBLISHED
    assert len(testmgmt.list_cases("DEMO-3")) == 8


class UnreadableCases(FakeTestManagement):
    """Jira no deja leer los casos al generar (pero sí al publicar)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.unreadable = True

    def list_cases(self, story_key: str) -> list[IssueSummary]:
        if self.unreadable:
            raise ExternalServiceError("Jira no responde (ficticio).", service="jira")
        return super().list_cases(story_key)


def test_unreadable_cases_keep_ids_and_publish_reports_conflict(tmp_path: Path) -> None:
    """PA-450: si no se pueden leer los casos al generar, la suite sigue con CP-01…; al publicar,
    el choque con los de otra suite es un conflicto: nada se crea ni se da por publicado."""
    legacy = [
        IssueSummary(
            key="DEMO-21", summary="[CP-01] Antiguo", issue_type="Subtarea", status="Por hacer"
        )
    ]
    testmgmt = UnreadableCases(cases={"DEMO-3": legacy})
    graph = build_graph(fake_container(tmp_path, test_management=testmgmt))

    config, suite = _qa_conversation(graph, "hilo-qa-sin-lectura")
    assert [c.internal_id for c in suite.cases] == ["CP-01", "CP-02"]
    testmgmt.unreadable = False

    with pytest.raises(PublishError, match=r"CP-01 \(DEMO-21\)"):
        _approve(graph, config)

    assert len(testmgmt.list_cases("DEMO-3")) == 1
    artifact = graph.get_state(config).values["artifact"]
    assert artifact.status is not ArtifactStatus.PUBLISHED


def test_retry_of_same_suite_reuses_its_cases(tmp_path: Path) -> None:
    """PA-05 con PA-450: el fake, como el real, reutiliza los CP de la misma suite."""
    testmgmt = FakeTestManagement()
    suite = renewal_test_suite()
    first = testmgmt.publish_suite(suite)
    second = testmgmt.publish_suite(suite)
    assert second.created == first.created
    assert len(testmgmt.list_cases(suite.story_jira_key)) == len(suite.cases)
