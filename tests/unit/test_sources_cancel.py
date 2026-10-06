"""PA-128 · La consulta de fuentes deja de calcular cuando la web cancela la petición.

`POST /start/sources` calcula en un hilo y mira cada `DISCONNECT_POLL_S` si el cliente se fue;
si se fue, el núcleo (`should_stop`) no empieza los pasos siguientes: ni los embeddings ni las
búsquedas. Dos consultas de la misma persona que se solapan terminan las dos. Datos ficticios.
"""

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from adapters.base import IssueDetail, User
from api import app as app_module
from api.app import API_PREFIX, SOURCES_CANCELLED, create_app
from api.errors import ApiError
from core.context.service import GatheringCancelledError
from core.guided_start import GuidedStart
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker

AF = ("af-demo", dataset.DEMO_USERS["af-demo"][0])
STORY = {"kind": "story", "key": "DEMO-3", "project": "DEMO"}


class CountingEmbeddings(FakeEmbeddingProvider):
    """Embeddings ficticios que cuentan las llamadas y pueden tardar."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls = 0
        self.delay_s = delay_s
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            self.calls += 1
        time.sleep(self.delay_s)
        return super().embed(texts)


class SlowTracker(FakeIssueTracker):
    """Jira ficticio lento al leer la incidencia de origen."""

    def __init__(self, delay_s: float) -> None:
        super().__init__()
        self.delay_s = delay_s

    def get_issue(self, key: str) -> IssueDetail:
        time.sleep(self.delay_s)
        return super().get_issue(key)


# --- Núcleo -------------------------------------------------------------------------------------


def test_should_stop_after_jira_skips_embeddings(tmp_path: Path) -> None:
    """PA-128: si piden parar mientras se lee Jira, no se calculan los embeddings."""
    embeddings = CountingEmbeddings()
    container = fake_container(tmp_path, embeddings=embeddings)
    checks = {"n": 0}

    def stop_after_first_check() -> bool:
        checks["n"] += 1
        return checks["n"] > 2  # las dos primeras (antes de Jira) dejan seguir

    with pytest.raises(GatheringCancelledError):
        GuidedStart(container).preview_sources_with_budget(STORY, None, stop_after_first_check)

    assert checks["n"] == 3  # se paró justo después de leer Jira
    assert embeddings.calls == 0


def test_without_should_stop_everything_is_calculated(tmp_path: Path) -> None:
    embeddings = CountingEmbeddings()
    container = fake_container(tmp_path, embeddings=embeddings)

    rows, _report = GuidedStart(container).preview_sources_with_budget(STORY, None)

    assert embeddings.calls >= 1
    assert {"DEMO-3", "DEMO-2"} <= {r.ref for r in rows}


def test_should_stop_from_the_start_does_nothing(tmp_path: Path) -> None:
    embeddings = CountingEmbeddings()
    container = fake_container(tmp_path, embeddings=embeddings)
    with pytest.raises(GatheringCancelledError):
        GuidedStart(container).preview_sources_with_budget(
            {"kind": "need", "text": "Renovar el carné de la biblioteca", "project": "DEMO"},
            None,
            lambda: True,
        )
    assert embeddings.calls == 0


# --- API ----------------------------------------------------------------------------------------


class FakeRequest:
    """Petición cuyo cliente se va al cabo de `gone_after` comprobaciones."""

    def __init__(self, gone_after: int | None) -> None:
        self.gone_after = gone_after
        self.checks = 0

    async def is_disconnected(self) -> bool:
        self.checks += 1
        return self.gone_after is not None and self.checks >= self.gone_after


class FakeWorkspace:
    def __init__(self, container: Any) -> None:
        self.container = container


def _preview(request: FakeRequest, container: Any) -> Any:
    return asyncio.run(
        app_module._preview_until_disconnected(
            request,  # type: ignore[arg-type]
            FakeWorkspace(container),  # type: ignore[arg-type]
            User(username="af-demo", role="functional"),
            STORY,  # type: ignore[arg-type]
            [],
        )
    )


def test_disconnected_request_stops_before_embeddings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-128: la web cancela mientras se lee Jira → 503 (nadie lo recibe) y sin embeddings."""
    monkeypatch.setattr(app_module, "DISCONNECT_POLL_S", 0.02)
    embeddings = CountingEmbeddings()
    container = fake_container(tmp_path, embeddings=embeddings, issue_tracker=SlowTracker(0.3))
    request = FakeRequest(gone_after=1)

    with capture_logs() as logs, pytest.raises(ApiError) as exc:
        _preview(request, container)

    assert exc.value.status == 503 and exc.value.code == "service_unavailable"
    assert exc.value.message == SOURCES_CANCELLED
    assert embeddings.calls == 0
    (entry,) = [e for e in logs if e.get("action") == "preview_sources"]
    assert entry["log_level"] == "info" and entry["user"] == "af-demo"


def test_connected_request_is_calculated_while_polling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el cliente conectado, se calcula todo aunque tarde varias comprobaciones."""
    monkeypatch.setattr(app_module, "DISCONNECT_POLL_S", 0.02)
    embeddings = CountingEmbeddings()
    container = fake_container(tmp_path, embeddings=embeddings, issue_tracker=SlowTracker(0.15))
    request = FakeRequest(gone_after=None)

    rows, _report = _preview(request, container)

    assert request.checks >= 2
    assert embeddings.calls >= 1
    assert "DEMO-3" in {r.ref for r in rows}


def test_two_overlapping_queries_of_same_person_both_finish(tmp_path: Path) -> None:
    """PA-128: la lista y el presupuesto de Origen (o dos pestañas) se solapan y terminan las dos;
    ninguna corta a la otra."""
    embeddings = CountingEmbeddings(delay_s=0.4)
    rt = fake_runtime(tmp_path, embeddings=embeddings)
    client = TestClient(create_app(runtime_instance=rt), base_url="https://testserver")
    login = client.post(f"{API_PREFIX}/auth/login", json={"username": AF[0], "password": AF[1]})
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    bodies = [
        {"origin": STORY},
        {"origin": STORY, "excluded_sources": ["doc-reglamento"]},
    ]
    results: list[Any] = [None, None]

    def ask(i: int) -> None:
        results[i] = client.post(f"{API_PREFIX}/start/sources", json=bodies[i], headers=headers)

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert [r.status_code for r in results] == [200, 200]
    assert embeddings.calls == 2
    assert "doc-reglamento" not in {r["ref"] for r in results[1].json()["sources"]}
