"""Comportamiento de FakeTestManagement: Jira nativo con subtareas y adjuntos (CA-00-03)."""

import pytest

from adapters import base
from adapters.errors import PublishError
from tests.fakes import FakeTestManagement
from tests.fakes.llm import renewal_test_suite


def test_publish_suite_creates_keys_for_every_case() -> None:
    """CA-00-03: publish_suite crea una clave por caso y no hay fallos."""
    fake = FakeTestManagement()
    result = fake.publish_suite(renewal_test_suite())
    assert isinstance(result, base.PublishResult)
    assert len(result.created) == 2
    assert len(set(result.created)) == 2
    assert all(key.startswith("DEMO-") for key in result.created)
    assert result.failed == []
    assert fake.publish_calls == 1


def test_publish_suite_attaches_strategy_and_matrix() -> None:
    """CA-00-03: adjuntos estrategia-<CLAVE>.md y matriz-<CLAVE>.md."""
    fake = FakeTestManagement()
    suite = renewal_test_suite()
    fake.publish_suite(suite)
    attachments = fake.attachments["DEMO-3"]
    assert set(attachments) == {"estrategia-DEMO-3.md", "matriz-DEMO-3.md"}
    assert attachments["estrategia-DEMO-3.md"] == suite.strategy_md
    assert attachments["matriz-DEMO-3.md"] == suite.coverage_md()
    assert "CA-01" in attachments["matriz-DEMO-3.md"]


def test_publish_suite_partial_failure_reports_created_and_failed() -> None:
    """CA-00-03 (error parcial, RNF-13): fail_case_ids → PublishResult con created y failed."""
    fake = FakeTestManagement(fail_case_ids={"CP-02"})
    result = fake.publish_suite(renewal_test_suite())
    assert len(result.created) == 1
    assert result.failed == ["CP-02"]
    assert [c.summary for c in fake.list_cases("DEMO-3")] == [
        "[CP-01] Renovar un préstamo sin reservas"
    ]


def test_publish_suite_all_cases_failing_creates_nothing() -> None:
    """CA-00-03 (límite): si fallan todos los casos no se crea ninguna subtarea."""
    fake = FakeTestManagement(fail_case_ids={"CP-01", "CP-02"})
    result = fake.publish_suite(renewal_test_suite())
    assert result.created == []
    assert result.failed == ["CP-01", "CP-02"]
    assert fake.list_cases("DEMO-3") == []


def test_list_cases_returns_published_subtasks() -> None:
    """CA-00-03: list_cases devuelve las subtareas creadas con su prefijo [CP-XX]."""
    fake = FakeTestManagement()
    result = fake.publish_suite(renewal_test_suite())
    cases = fake.list_cases("DEMO-3")
    assert [c.key for c in cases] == result.created
    assert [c.summary.split("]")[0] + "]" for c in cases] == ["[CP-01]", "[CP-02]"]
    assert all(isinstance(c, base.IssueSummary) for c in cases)


def test_list_cases_unknown_story_returns_empty() -> None:
    """CA-00-03 (límite): HU sin casos publicados → lista vacía."""
    assert FakeTestManagement().list_cases("DEMO-4") == []


def test_list_cases_returns_copy_of_list() -> None:
    """CA-00-03: modificar la lista devuelta no altera el fake."""
    fake = FakeTestManagement()
    fake.publish_suite(renewal_test_suite())
    fake.list_cases("DEMO-3").clear()
    assert len(fake.list_cases("DEMO-3")) == 2


def test_publish_suite_twice_reuses_the_same_cases() -> None:
    """PA-05 · PA-450: como el real, publicar dos veces la misma suite reutiliza sus casos."""
    fake = FakeTestManagement()
    first = fake.publish_suite(renewal_test_suite())
    second = fake.publish_suite(renewal_test_suite())
    assert second.created == first.created
    assert len(fake.list_cases("DEMO-3")) == 2
    assert fake.publish_calls == 2


def test_publish_suite_of_other_suite_with_same_ids_is_a_conflict() -> None:
    """PA-450: otra suite de la misma HU con los mismos CP no se da por publicada."""
    fake = FakeTestManagement()
    fake.publish_suite(renewal_test_suite())
    other = renewal_test_suite().model_copy(update={"strategy_md": "Otra estrategia ficticia."})
    with pytest.raises(PublishError, match="No se ha publicado nada"):
        fake.publish_suite(other)
    assert len(fake.list_cases("DEMO-3")) == 2
