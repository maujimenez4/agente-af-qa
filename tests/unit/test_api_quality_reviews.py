"""Revisiones de calidad guardadas por la API (PA-272, PA-103 · RF-18).

`POST/GET /quality-reviews` y `GET /quality-reviews/{id}` sobre `fake_runtime` (almacén
`InMemoryQualityReviewStore`), el arranque de `build_runtime` (las revisiones en marcha pasan a
error) y el contrato publicado. Solo fakes, sin red, sin `.env`, sin Jira ni LLM reales; datos
100 % ficticios.
"""

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import yaml

import core.config
import core.container
import core.factories
import core.graph
import core.graph.execution
import core.quality
import core.usage
from adapters.base import User
from adapters.errors import ExternalServiceError, RateLimitError
from api.app import API_PREFIX
from api.export_openapi import OPENAPI_PATH, openapi_document
from api.runtime import Runtime, build_runtime
from core.handoff import InMemoryHandoffStore
from core.quality import INTERRUPTED, InMemoryQualityReviewStore, new_review
from schemas.quality import QualityReport
from tests.fakes import dataset
from tests.fakes.api import api_settings, fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.llm import FakeLLMProvider, renewal_quality_report
from tests.unit.test_api_app import AF, QA, Api, _nothing_written

AF2 = ("af-ficticia-2", "contrasena-ficticia-af2")
SUMMARY_KEYS = {"id", "issue_key", "project", "title", "state", "created_at", "updated_at"}


def _add_af2(rt: Runtime) -> None:
    rt.auth.users[AF2[0]] = (AF2[1], User(username=AF2[0], role="functional"))  # type: ignore[attr-defined]


def _login(rt: Runtime, who: tuple[str, str] = AF) -> Api:
    a = Api(rt)
    assert a.login(who).status_code == 200
    return a


def _deferred(rt: Runtime) -> list[Callable[[], None]]:
    """Las tareas se guardan en vez de ejecutarse: así se ve la revisión `running`."""
    pending: list[Callable[[], None]] = []
    rt.submit = pending.append  # type: ignore[method-assign]
    return pending


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


# --- Crear, listar y consultar -----------------------------------------------------------------


def test_create_quality_review_is_202_running_then_listed_and_done(rt: Runtime) -> None:
    """Criterio 4: POST → 202 running; aparece en la lista (sin texto del informe) y, al
    terminar, pasa a done con el informe en el detalle."""
    pending = _deferred(rt)
    af = _login(rt)

    created = af.post("/quality-reviews", {"issue_key": "DEMO-3"})

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["state"] == "running"
    assert body["report"] is None and body["error"] is None
    assert body["created_at"] and body["updated_at"]
    listed = af.get("/quality-reviews")
    assert listed.status_code == 200
    (row,) = listed.json()
    assert set(row) == SUMMARY_KEYS
    assert row["id"] == body["id"]
    assert row["title"] == "Revisar la calidad de DEMO-3"
    assert row["project"] == "DEMO"
    assert row["issue_key"] == "DEMO-3"
    assert row["state"] == "running"

    (task,) = pending
    task()

    (row,) = af.get("/quality-reviews").json()
    assert row["state"] == "done"
    assert set(row) == SUMMARY_KEYS
    report = renewal_quality_report()
    assert report.summary not in listed.text and report.summary not in str(row)
    assert all(f.proposal not in str(row) for f in report.findings)
    detail = af.get(f"/quality-reviews/{body['id']}")
    assert detail.status_code == 200
    out = detail.json()
    assert out["state"] == "done"
    assert QualityReport.model_validate(out["report"]).summary == report.summary
    assert out["evolve_feedback"][0].startswith("CA-02: ")
    assert out["report_markdown"]
    assert out["created_at"] == body["created_at"]
    assert out["updated_at"] >= out["created_at"]
    _nothing_written(rt)


def test_list_quality_reviews_newest_first_and_limit(rt: Runtime) -> None:
    """Criterio 4: la lista va de la más reciente a la más antigua y respeta `limit`."""
    af = _login(rt)
    ids = [af.post("/quality-reviews", {"issue_key": k}).json()["id"] for k in ("DEMO-3", "DEMO-2")]

    listed = af.get("/quality-reviews").json()

    assert [r["id"] for r in listed] == ids[::-1]
    assert [r["title"] for r in listed] == [
        "Revisar la calidad de DEMO-2",
        "Revisar la calidad de DEMO-3",
    ]
    assert len(af.get("/quality-reviews?limit=1").json()) == 1


@pytest.mark.parametrize("limit", [0, 21, -1])
def test_list_quality_reviews_rejects_out_of_range_limit(rt: Runtime, limit: int) -> None:
    """Criterio 4 (límite): `limit` fuera de 1..20 → 422 en la forma común."""
    af = _login(rt)

    response = af.get(f"/quality-reviews?limit={limit}")

    assert response.status_code == 422
    assert "error" in response.json()


def test_list_quality_reviews_only_returns_own(rt: Runtime) -> None:
    """Criterio 4: cada persona solo ve sus revisiones en la lista."""
    _add_af2(rt)
    af, af2 = _login(rt), _login(rt, AF2)
    mine = af.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]
    theirs = af2.post("/quality-reviews", {"issue_key": "DEMO-2"}).json()["id"]

    assert [r["id"] for r in af.get("/quality-reviews").json()] == [mine]
    assert [r["id"] for r in af2.get("/quality-reviews").json()] == [theirs]


def test_list_quality_reviews_as_qa_is_403(rt: Runtime) -> None:
    """Criterio 4 (permiso): el rol qa no tiene la lista de revisiones de calidad."""
    af = _login(rt)
    af.post("/quality-reviews", {"issue_key": "DEMO-3"})
    qa = _login(rt, QA)

    response = qa.get("/quality-reviews")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_list_quality_reviews_without_session_is_401(rt: Runtime) -> None:
    """Criterio 4 (sesión): sin sesión → 401."""
    response = Api(rt).get("/quality-reviews")

    assert response.status_code == 401


def test_foreign_and_missing_quality_review_give_identical_404(rt: Runtime) -> None:
    """Criterio 4: una revisión ajena (de otra persona funcional) y una inexistente dan el mismo
    404, con el mismo cuerpo."""
    _add_af2(rt)
    af, af2 = _login(rt), _login(rt, AF2)
    rid = af.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]

    foreign = af2.get(f"/quality-reviews/{rid}")
    missing = af2.get(f"/quality-reviews/{uuid4()}")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert foreign.json()["error"]["code"] == "not_found"
    assert af.get(f"/quality-reviews/{rid}").status_code == 200


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            RateLimitError("Límite ficticio del proveedor.", service="llm", retry_after=30),
            "rate_limited",
        ),
        (
            ExternalServiceError("El proveedor ficticio no responde.", service="llm"),
            "service_unavailable",
        ),
    ],
    ids=["rate-limit", "external"],
)
def test_llm_failure_leaves_review_in_error_with_spanish_body(
    tmp_path: Path, error: Exception, code: str
) -> None:
    """Criterio 4 (error): un fallo del LLM deja la revisión en error con ErrorBody en español,
    también en la lista; nada se escribe en Jira."""
    rt = fake_runtime(tmp_path, llm=FakeLLMProvider(error=error))
    af = _login(rt)

    created = af.post("/quality-reviews", {"issue_key": "DEMO-3"})

    assert created.status_code == 202
    detail = af.get(f"/quality-reviews/{created.json()['id']}").json()
    assert detail["state"] == "error"
    assert detail["report"] is None and detail["report_markdown"] is None
    assert detail["error"]["code"] == code
    assert detail["error"]["message"] == str(error)
    if code == "rate_limited":
        assert detail["error"]["retry_after"] == 30
    (row,) = af.get("/quality-reviews").json()
    assert row["state"] == "error"
    _nothing_written(rt)


def test_unexpected_failure_does_not_leak_exception_text(tmp_path: Path) -> None:
    """Criterio 4 (error): una excepción inesperada queda como `unexpected` sin su texto."""
    secret = "detalle-interno-ficticio-0000"
    rt = fake_runtime(tmp_path, llm=FakeLLMProvider(error=RuntimeError(secret)))
    af = _login(rt)

    rid = af.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]

    detail = af.get(f"/quality-reviews/{rid}")
    assert detail.json()["error"]["code"] == "unexpected"
    assert secret not in detail.text


def test_store_failure_when_saving_error_is_swallowed(tmp_path: Path) -> None:
    """Criterio 4 (error): si la BD también falla al guardar el error, la tarea no revienta."""
    rt = fake_runtime(tmp_path, llm=FakeLLMProvider(error=RuntimeError("fallo ficticio")))
    store = rt.quality

    def broken_fail(*_a: Any, **_k: Any) -> None:
        raise ExternalServiceError("No se pudo guardar la revisión de calidad.", service="postgres")

    store.fail = broken_fail  # type: ignore[method-assign]
    af = _login(rt)

    created = af.post("/quality-reviews", {"issue_key": "DEMO-3"})

    assert created.status_code == 202
    assert created.json()["state"] == "running"


def test_reviews_persist_across_runtimes_sharing_the_store(tmp_path: Path) -> None:
    """Criterio 4 (persistencia): otro runtime con el mismo almacén ve la revisión y su informe."""
    rt1 = fake_runtime(tmp_path / "uno")
    rid = _login(rt1).post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]
    rt2 = fake_runtime(tmp_path / "dos")
    rt2.quality = rt1.quality

    af = _login(rt2)

    assert [r["id"] for r in af.get("/quality-reviews").json()] == [rid]
    detail = af.get(f"/quality-reviews/{rid}").json()
    assert detail["state"] == "done"
    assert detail["report"]["summary"] == renewal_quality_report().summary
    _nothing_written(rt1)
    _nothing_written(rt2)


def test_running_review_interrupted_is_shown_as_error(rt: Runtime) -> None:
    """Criterio 4/5: una revisión interrumpida se ve en la API como error con INTERRUPTED."""
    pending = _deferred(rt)
    af = _login(rt)
    rid = af.post("/quality-reviews", {"issue_key": "DEMO-3"}).json()["id"]
    assert pending

    assert rt.quality.interrupt_running() == 1

    detail = af.get(f"/quality-reviews/{rid}").json()
    assert detail["state"] == "error"
    assert detail["error"] == {
        "code": "operation_failed",
        "message": INTERRUPTED,
        "retry_after": None,
    }


# --- build_runtime: revisiones interrumpidas al arrancar ---------------------------------------


def test_build_runtime_marks_running_reviews_as_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Criterio 5: al arrancar, build_runtime usa SqlQualityReviewStore y pasa a error las
    revisiones que estaban en marcha (las terminadas no cambian)."""
    store = InMemoryQualityReviewStore()
    running = new_review(str(uuid4()), "af-demo", "DEMO-3")
    done = new_review(str(uuid4()), "af-demo", "DEMO-2")
    store.create(running)
    store.create(done)
    store.finish(
        done.id,
        core.quality.QualityReview(
            jira_key="DEMO-2",
            report=renewal_quality_report(),
            story=dataset.renewal_story(),
            provider="ollama",
            model="modelo-ficticio",
            prompt_version="1",
            input_tokens=1,
            output_tokens=1,
        ),
    )
    urls: list[Any] = []

    def from_url(_cls: Any, url: Any) -> InMemoryQualityReviewStore:
        urls.append(url)
        return store

    config = SimpleNamespace(
        settings=api_settings(),
        models=SimpleNamespace(limits=SimpleNamespace(daily_token_warning=1000)),
        task_chain=lambda _task: [],
    )
    base = fake_container(tmp_path, require_actor=True)
    monkeypatch.setattr(core.config, "build_config", lambda: config)
    monkeypatch.setattr(core.container, "bootstrap_logging", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_app_container", lambda _c: base)
    monkeypatch.setattr(core.factories, "build_usage_recorder", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_checkpointer", lambda _c: "checkpointer")
    monkeypatch.setattr(core.factories, "build_handoffs", lambda _c: InMemoryHandoffStore())
    monkeypatch.setattr(core.factories, "model_router", lambda _c: None)
    monkeypatch.setattr(core.factories, "build_session_container", lambda _c, b, _r, _rec: b)
    monkeypatch.setattr(core.graph, "build_graph", lambda *_a, **_k: object())
    monkeypatch.setattr(core.graph.execution, "build_execution_graph", lambda *_a, **_k: None)
    monkeypatch.setattr(core.usage.SqlUsageQueries, "from_url", classmethod(lambda _cls, _u: None))
    monkeypatch.setattr(core.quality.SqlQualityReviewStore, "from_url", classmethod(from_url))

    rt = build_runtime()

    assert rt.quality is store
    assert len(urls) == 1
    row = store.get(running.id)
    assert row is not None
    assert (row.state, row.error_code, row.error_message) == (
        "error",
        "operation_failed",
        INTERRUPTED,
    )
    assert store.get(done.id).state == "done"  # type: ignore[union-attr]


# --- Contrato ----------------------------------------------------------------------------------

DOC = openapi_document()


def test_contract_lists_quality_reviews_with_summary_schema() -> None:
    """Criterio 6: GET /quality-reviews devuelve list[QualityReviewSummary] (código y YAML)."""
    published = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    for doc in (DOC, published):
        op = doc["paths"][f"{API_PREFIX}/quality-reviews"]["get"]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        assert schema["type"] == "array"
        assert schema["items"] == {"$ref": "#/components/schemas/QualityReviewSummary"}
        summary = doc["components"]["schemas"]["QualityReviewSummary"]
        assert set(summary["properties"]) == SUMMARY_KEYS
        assert set(summary["required"]) == SUMMARY_KEYS
        assert summary["properties"]["state"]["enum"] == ["running", "done", "error"]
        assert "summary" not in summary["properties"]
        assert "findings" not in summary["properties"]
        out = doc["components"]["schemas"]["QualityReviewOut"]
        assert {"created_at", "updated_at"} <= set(out["required"])


def test_contract_quality_list_example_has_no_report_text() -> None:
    """Criterio 6: el ejemplo de la lista es un QualityReviewSummary sin texto del informe."""
    op = DOC["paths"][f"{API_PREFIX}/quality-reviews"]["get"]
    (example,) = op["responses"]["200"]["content"]["application/json"]["example"]
    assert set(example) == SUMMARY_KEYS
    assert example["title"] == "Revisar la calidad de DEMO-3"
    assert example["project"] == "DEMO"


def test_contract_conversations_list_is_unchanged() -> None:
    """Criterio 6: GET /conversations sigue devolviendo list[ConversationSummary]."""
    op = DOC["paths"][f"{API_PREFIX}/conversations"]["get"]
    schema = op["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": "#/components/schemas/ConversationSummary"}


def test_conversations_list_does_not_include_quality_reviews(rt: Runtime) -> None:
    """Criterio 6: las revisiones de calidad no se mezclan en GET /conversations."""
    af = _login(rt)
    af.post("/quality-reviews", {"issue_key": "DEMO-3"})

    assert af.get("/conversations").json() == []


def test_unknown_error_code_from_store_is_shown_as_unexpected(tmp_path: Path) -> None:
    """El código de error sale de la BD: uno desconocido no rompe la respuesta (500)."""
    rt = fake_runtime(tmp_path)
    api = _login(rt)
    review = new_review(str(uuid4()), "af-demo", "DEMO-3")
    rt.quality.create(review)
    rt.quality.fail(review.id, "codigo-desconocido", "Fallo ficticio.")

    body = api.get(f"/quality-reviews/{review.id}").json()

    assert body["state"] == "error"
    assert body["error"]["code"] == "unexpected"
    assert body["error"]["message"] == "Fallo ficticio."
