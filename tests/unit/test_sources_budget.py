"""Presupuesto rápido en Origen: tokens por fuente y presupuesto total (ronda 13 · PA-330).

Cubren `SourcePreview.tokens` en `GuidedStart.preview_sources_with_budget` (incidencia, también
recortada, y documento con varios fragmentos), `ContextBudgetOut.fixed`/`total` en
`POST /api/v1/start/sources`, el ejemplo `SOURCES_OUT` y que el contrato publicado sigue al día.
Solo fakes de `tests/fakes/`, sin LLM ni red; datos 100 % ficticios (Villaficticia, DEMO-N).
"""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from adapters.base import Chunk
from api import examples as ex
from api.app import API_PREFIX, create_app
from api.models import ContextBudgetOut, SourcesOut
from api.runtime import Runtime
from core.container import Container
from core.context.budget import chunk_tokens, estimate_tokens, issue_tokens
from core.context.service import DEFAULT_TOKEN_BUDGET, build_context_service
from core.graph import Origin
from core.guided_start import GuidedStart
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore

STORY: Origin = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}
NEED_TEXT = "Avisar por correo del vencimiento del préstamo con tres días de antelación (ficticio)."
NEED: Origin = {"kind": "need", "text": NEED_TEXT, "project": "DEMO"}
FILLER = "Descripción ficticia muy larga de la renovación de préstamos en Villaficticia. "
AF = ("af-demo", dataset.DEMO_USERS["af-demo"][0])


# --- utilidades --------------------------------------------------------------------------------


@pytest.fixture
def container(tmp_path: Path) -> Container:
    return fake_container(tmp_path)


def _tracker(container: Container) -> FakeIssueTracker:
    assert isinstance(container.issue_tracker, FakeIssueTracker)
    return container.issue_tracker


def _add_chunk(container: Container, document_id: str, ordinal: int, content: str) -> None:
    store = container.vector_store
    assert isinstance(store, FakeVectorStore)
    (vector,) = container.embeddings.embed([content])
    store.upsert(
        [
            Chunk(
                id=f"{document_id}-{ordinal}",
                document_id=document_id,
                ordinal=ordinal,
                section=dataset.DOCUMENTS[document_id]["title"],
                content=content,
                embedding=vector,
                metadata={"category": dataset.DOCUMENTS[document_id]["category"]},
            )
        ]
    )


def _lengthen_origin(container: Container) -> None:
    """La HU de origen con una descripción que no cabe: se recorta (PA-102)."""
    tracker = _tracker(container)
    origin = tracker.issues["DEMO-3"]
    tracker.issues["DEMO-3"] = origin.model_copy(update={"description_text": FILLER * 400})


class Api:
    def __init__(self, rt: Runtime) -> None:
        self.client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
        response = self.client.post(
            f"{API_PREFIX}/auth/login", json={"username": AF[0], "password": AF[1]}
        )
        assert response.status_code == 200
        self.csrf = response.json()["csrf_token"]

    def sources(self, origin: dict[str, Any], excluded: list[str] | None = None) -> Any:
        body: dict[str, Any] = {"origin": origin}
        if excluded is not None:
            body["excluded_sources"] = excluded
        return self.client.post(
            f"{API_PREFIX}/start/sources", json=body, headers={"X-CSRF-Token": self.csrf}
        )


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


@pytest.fixture
def api(rt: Runtime) -> Api:
    return Api(rt)


def _base(rt: Runtime) -> Container:
    return rt.workspace_factory().container


# --- 1 · tokens por fuente (GuidedStart) -------------------------------------------------------


def test_issue_row_tokens_match_issue_tokens(container: Container) -> None:
    """PA-330: la fila de una incidencia lleva `issue_tokens` de la incidencia enviada."""
    rows, _report = GuidedStart(container).preview_sources_with_budget(STORY)

    origin = next(r for r in rows if r.ref == "DEMO-3")
    assert origin.tokens == issue_tokens(_tracker(container).issues["DEMO-3"])
    assert all(r.tokens is not None and r.tokens > 0 for r in rows)


def test_document_with_several_chunks_sums_their_tokens(container: Container) -> None:
    """PA-330: un documento con varios fragmentos suma `chunk_tokens` de todos ellos."""
    extra = "Artículo 9 ficticio: renovar un préstamo dos veces como máximo, sin reservas."
    _add_chunk(container, "doc-reglamento", 1, extra)
    tracker = _tracker(container)
    gathered = build_context_service(container, "DEMO").gather(STORY, tracker.issues["DEMO-3"])
    hits = [h for h in gathered.rag if h.source.ref == "doc-reglamento"]
    assert len(hits) >= 2, "la prueba necesita dos fragmentos del mismo documento"

    rows, _report = GuidedStart(container).preview_sources_with_budget(STORY)

    (row,) = [r for r in rows if r.ref == "doc-reglamento"]
    assert row.tokens == sum(chunk_tokens(h) for h in hits)
    assert row.tokens > max(chunk_tokens(h) for h in hits)


def test_row_tokens_add_up_to_budget_used(container: Container) -> None:
    """PA-330: la suma de `tokens` de las fuentes es `used` del presupuesto."""
    rows, report = GuidedStart(container).preview_sources_with_budget(STORY)

    assert sum(r.tokens or 0 for r in rows) == report.used


def test_truncated_issue_reports_truncated_tokens(container: Container) -> None:
    """PA-330 (límite): la incidencia recortada lleva los tokens tras el recorte."""
    _lengthen_origin(container)
    original = issue_tokens(_tracker(container).issues["DEMO-3"])

    rows, report = GuidedStart(container).preview_sources_with_budget(STORY)

    origin = next(r for r in rows if r.ref == "DEMO-3")
    assert report.truncated_issues >= 1
    assert origin.tokens is not None and 0 < origin.tokens < original
    assert origin.tokens <= report.budget
    assert sum(r.tokens or 0 for r in rows) == report.used


def test_need_rows_have_tokens_and_add_up(tmp_path: Path) -> None:
    """PA-330: con una necesidad, las fuentes también traen `tokens` y suman `used`."""
    container = fake_container(tmp_path)

    rows, report = GuidedStart(container).preview_sources_with_budget(NEED)

    assert all(r.tokens is not None for r in rows)
    assert sum(r.tokens or 0 for r in rows) == report.used
    assert _llm_calls(container) == []


def _llm_calls(container: Container) -> list[Any]:
    assert isinstance(container.llm, FakeLLMProvider)
    return container.llm.calls


# --- 2 · POST /start/sources ------------------------------------------------------------------


def test_api_story_origin_has_fixed_zero_and_total_equal_limit(api: Api) -> None:
    """PA-330: con origen HU, `fixed` es 0 y `total == limit + fixed`."""
    response = api.sources(STORY)  # type: ignore[arg-type]

    assert response.status_code == 200
    budget = response.json()["budget"]
    assert budget["fixed"] == 0
    assert budget["total"] == budget["limit"] + budget["fixed"] == DEFAULT_TOKEN_BUDGET


def test_api_need_origin_reserves_the_need_text(api: Api) -> None:
    """PA-330: con una necesidad, `fixed` > 0 (su texto) y `total == limit + fixed`."""
    response = api.sources(NEED)  # type: ignore[arg-type]

    assert response.status_code == 200
    budget = response.json()["budget"]
    assert budget["fixed"] == estimate_tokens(NEED_TEXT) > 0
    assert budget["total"] == budget["limit"] + budget["fixed"]
    assert budget["limit"] == DEFAULT_TOKEN_BUDGET - budget["fixed"]


def test_api_rows_carry_tokens_that_add_up_to_used(api: Api) -> None:
    """PA-330: cada fila de `/start/sources` lleva `tokens` y su suma es `used`."""
    body = api.sources(STORY).json()  # type: ignore[arg-type]

    assert all(isinstance(r["tokens"], int) and r["tokens"] > 0 for r in body["sources"])
    assert sum(r["tokens"] for r in body["sources"]) == body["budget"]["used"]


def test_api_excluding_a_source_lowers_estimate_by_its_tokens(api: Api) -> None:
    """PA-330: sin relleno de otra fuente, desmarcar resta exactamente sus `tokens`."""
    before = api.sources(STORY).json()  # type: ignore[arg-type]
    row = next(r for r in before["sources"] if r["ref"] == "DEMO-2")

    after = api.sources(STORY, excluded=["DEMO-2"]).json()  # type: ignore[arg-type]

    assert "DEMO-2" not in {r["ref"] for r in after["sources"]}
    assert after["budget"]["total"] == before["budget"]["total"]
    jira_before = sum(r["tokens"] for r in before["sources"] if r["kind"] == "jira")
    jira_after = sum(r["tokens"] for r in after["sources"] if r["kind"] == "jira")
    assert jira_after == jira_before - row["tokens"]


def test_api_truncated_origin_reports_truncated_tokens(api: Api, rt: Runtime) -> None:
    """PA-330 (límite): por la API, la incidencia recortada lleva los tokens recortados."""
    container = _base(rt)
    _lengthen_origin(container)
    original = issue_tokens(_tracker(container).issues["DEMO-3"])

    body = api.sources(STORY).json()  # type: ignore[arg-type]

    origin = next(r for r in body["sources"] if r["ref"] == "DEMO-3")
    assert body["budget"]["truncated_sources"] >= 1
    assert 0 < origin["tokens"] < original
    assert sum(r["tokens"] for r in body["sources"]) == body["budget"]["used"]


# --- 3 · ejemplo y contrato ---------------------------------------------------------------------


def test_sources_out_example_validates_and_tokens_add_up() -> None:
    """PA-330: el ejemplo `SOURCES_OUT` valida y sus `tokens` suman `used`."""
    example = SourcesOut.model_validate(ex.SOURCES_OUT.model_dump(mode="json"))

    assert all(s.tokens is not None for s in example.sources)
    assert sum(s.tokens or 0 for s in example.sources) == example.budget.used
    assert example.budget.fixed == 0
    assert example.budget.total == example.budget.limit + (example.budget.fixed or 0)


def test_context_budget_fields_are_optional_and_non_negative() -> None:
    """PA-330 (compatibilidad): `fixed` y `total` son opcionales y no admiten negativos."""
    legacy = ContextBudgetOut(used=1, limit=2, dropped_sources=0, truncated_sources=0)
    assert legacy.fixed is None and legacy.total is None
    with pytest.raises(ValueError):
        ContextBudgetOut(used=1, limit=2, dropped_sources=0, truncated_sources=0, fixed=-1, total=1)
