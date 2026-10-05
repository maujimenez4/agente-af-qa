"""PA-282: `QualityReviewer` repara las citas del informe sin LLM tras cada llamada (primera y
reintento), como ya hacían el writer de HU y el de suites.

Contenedor de fakes (`tests/fakes/`), sin red ni LLM reales. Datos 100 % sintéticos.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from adapters.base import Message, TaskType
from core.container import Container
from core.functional.citations import CitationError
from core.quality import QualityReview, QualityReviewer
from schemas.common import SourceRef
from schemas.quality import QualityReport
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report

AF = dataset.DEMO_USERS["af-demo"][1]
KEY = "DEMO-3"
EPIC = dataset.EPIC_KEY
HU_TEXT = dataset.STORIES[KEY].description_text
INVENTED_REF = "DOC-INVENTADO-77"


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path / "memoria")


def _llm(container: Container) -> FakeLLMProvider:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm


def _report(*sources: SourceRef) -> QualityReport:
    return renewal_quality_report().model_copy(update={"sources": list(sources)})


def _epic_with_hu_text() -> QualityReport:
    return _report(SourceRef(kind="jira", ref=EPIC, excerpt=HU_TEXT))


def _invented() -> QualityReport:
    return _report(SourceRef(kind="rag", ref=INVENTED_REF, excerpt="Extracto inventado."))


def _sequence(*reports: QualityReport) -> Callable[[list[Message]], BaseModel]:
    pending = list(reports)

    def build(_messages: list[Message]) -> BaseModel:
        return pending.pop(0) if len(pending) > 1 else pending[0]

    return build


def _review_calls(container: Container) -> list[dict[str, Any]]:
    return [c for c in _llm(container).calls if c["task"] is TaskType.REVIEW_STORY]


def _review(container: Container, **kwargs: Any) -> QualityReview:
    return QualityReviewer(container).review(AF, KEY, **kwargs)


def _real_excerpt_of(container: Container, key: str) -> str:
    issue = container.issue_tracker.get_issue(key)
    return issue.summary


def test_review_repairs_epic_not_in_context_with_hu_text_without_retry(
    container: Container,
) -> None:
    """Criterio 2: el informe cita la épica (excluida del contexto) con el texto de la HU →
    informe válido, una sola llamada de REVIEW_STORY y cita corregida a la HU."""
    _llm(container).builders[QualityReport] = _sequence(_epic_with_hu_text())

    review = _review(container, excluded_sources=[EPIC])

    assert len(_review_calls(container)) == 1
    (source,) = review.report.sources
    assert (source.kind, source.ref) == ("jira", KEY)
    assert source.excerpt is not None and source.excerpt.startswith(
        _real_excerpt_of(container, KEY)
    )


def test_review_repairs_epic_in_context_with_hu_text_without_retry(container: Container) -> None:
    """Criterio 2 + PA-283: la épica sí está en el contexto, pero el extracto es de la HU."""
    _llm(container).builders[QualityReport] = _sequence(_epic_with_hu_text())

    review = _review(container)

    assert len(_review_calls(container)) == 1
    assert [s.ref for s in review.report.sources] == [KEY]


def test_review_still_retries_invented_citation(container: Container) -> None:
    """Criterio 2 (negativa): una cita inventada no se puede reparar y sigue reintentando."""
    valid = _report(SourceRef(kind="jira", ref=KEY))
    _llm(container).builders[QualityReport] = _sequence(_invented(), valid)

    review = _review(container)

    assert len(_review_calls(container)) == 2
    assert [s.ref for s in review.report.sources] == [KEY]


def test_review_invented_citation_persisting_still_raises(container: Container) -> None:
    """Criterio 2 (error): la cita inventada persiste tras el reintento → CitationError."""
    _llm(container).builders[QualityReport] = _sequence(_invented())

    with pytest.raises(CitationError):
        _review(container)

    assert len(_review_calls(container)) == 2


def test_review_repairs_the_retry_response(container: Container) -> None:
    """Criterio 2: la respuesta del reintento también se repara (épica fuera del contexto con
    el texto de la HU) y no lanza CitationError."""
    _llm(container).builders[QualityReport] = _sequence(_invented(), _epic_with_hu_text())

    review = _review(container, excluded_sources=[EPIC])

    assert len(_review_calls(container)) == 2
    assert [(s.kind, s.ref) for s in review.report.sources] == [("jira", KEY)]


def test_review_repairs_valid_but_wrong_citation_in_retry(container: Container) -> None:
    """Criterio 2 + PA-283: en el reintento, una cita a la épica (en el contexto) con el texto
    de la HU se corrige a la HU."""
    _llm(container).builders[QualityReport] = _sequence(_invented(), _epic_with_hu_text())

    review = _review(container)

    assert len(_review_calls(container)) == 2
    assert [s.ref for s in review.report.sources] == [KEY]
