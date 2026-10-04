"""PA-279 (RGPD): conservación de las revisiones de calidad guardadas.

`QUALITY_RETENTION_DAYS`, `purge_older_than`/`delete_for` (memoria y SQL), `retention_cutoff`,
`purge_expired`, la CLI `python -m core.quality --purgar` y la purga al arrancar la API.
Sin red ni `.env`: motores de mentira y `monkeypatch`; las de PostgreSQL llevan
`@pytest.mark.integration`. Datos 100 % ficticios.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from structlog.testing import capture_logs

import core.config
import core.container
import core.factories
import core.graph
import core.graph.execution
import core.quality
import core.usage
from adapters.errors import ExternalServiceError
from api.runtime import build_runtime
from core.config import Settings
from core.handoff import InMemoryHandoffStore
from core.quality import (
    InMemoryQualityReviewStore,
    SqlQualityReviewStore,
    StoredQualityReview,
    purge_expired,
    retention_cutoff,
)
from tests.fakes.api import api_settings
from tests.fakes.container import fake_container
from tests.pg_temp import temporary_database
from tests.unit.test_quality_store import FAKE_PASSWORD as LEAKED_DETAIL
from tests.unit.test_quality_store import BrokenEngine, RecordingEngine, _sql

ANA = "ana-ficticia"
BEA = "bea-ficticia"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def _stored(username: str = ANA, *, days_ago: float, key: str = "DEMO-3") -> StoredQualityReview:
    at = NOW - timedelta(days=days_ago)
    return StoredQualityReview(
        id=str(uuid4()), username=username, issue_key=key, created_at=at, updated_at=at
    )


def _store_with(*reviews: StoredQualityReview) -> InMemoryQualityReviewStore:
    store = InMemoryQualityReviewStore()
    for review in reviews:
        store.rows[review.id] = review
    return store


# --- Settings ------------------------------------------------------------------------------


def test_settings_quality_retention_days_defaults_to_90(clean_env: pytest.MonkeyPatch) -> None:
    """Criterio 5: sin variable, se conservan 90 días."""
    clean_env.delenv("QUALITY_RETENTION_DAYS", raising=False)

    assert Settings(_env_file=None).quality_retention_days == 90  # type: ignore[call-arg]


def test_settings_reads_quality_retention_days_from_env(clean_env: pytest.MonkeyPatch) -> None:
    """Criterio 5: `QUALITY_RETENTION_DAYS` se lee del entorno."""
    clean_env.setenv("QUALITY_RETENTION_DAYS", "30")

    assert Settings(_env_file=None).quality_retention_days == 30  # type: ignore[call-arg]


@pytest.mark.parametrize("value", ["0", "-1", "no-es-un-numero"])
def test_settings_rejects_non_positive_retention(clean_env: pytest.MonkeyPatch, value: str) -> None:
    """Criterio 5 (límite/error): 0, negativo o no numérico → error de validación."""
    clean_env.setenv("QUALITY_RETENTION_DAYS", value)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_accepts_one_day_retention(clean_env: pytest.MonkeyPatch) -> None:
    """Criterio 5 (límite): 1 día es el mínimo válido."""
    clean_env.setenv("QUALITY_RETENTION_DAYS", "1")

    assert Settings(_env_file=None).quality_retention_days == 1  # type: ignore[call-arg]


# --- retention_cutoff y almacén en memoria -------------------------------------------------


def test_retention_cutoff_subtracts_days_from_now() -> None:
    """Criterio 5: el corte es `now - days` (y por defecto, la hora actual en UTC)."""
    assert retention_cutoff(90, NOW) == NOW - timedelta(days=90)
    before = datetime.now(UTC) - timedelta(days=7)
    cutoff = retention_cutoff(7)
    assert cutoff.tzinfo is not None
    assert before <= cutoff <= datetime.now(UTC) - timedelta(days=7)


def test_in_memory_purge_older_than_deletes_only_older_and_returns_count() -> None:
    """Criterio 5: solo se borran las anteriores al corte; devuelve cuántas."""
    old_a, old_b = _stored(days_ago=120), _stored(BEA, days_ago=91)
    recent, edge = _stored(days_ago=10), _stored(BEA, days_ago=90)
    store = _store_with(old_a, old_b, recent, edge)

    purged = store.purge_older_than(NOW - timedelta(days=90))

    assert purged == 2
    assert set(store.rows) == {recent.id, edge.id}  # justo en el corte no se borra


def test_in_memory_purge_older_than_without_matches_returns_zero() -> None:
    """Criterio 5 (límite): sin revisiones caducadas → 0 y nada cambia."""
    recent = _stored(days_ago=1)
    store = _store_with(recent)

    assert store.purge_older_than(NOW - timedelta(days=90)) == 0
    assert InMemoryQualityReviewStore().purge_older_than(NOW) == 0
    assert set(store.rows) == {recent.id}


def test_in_memory_delete_for_deletes_only_that_person() -> None:
    """Criterio 5: `delete_for` borra todas las de esa persona y ninguna de otra."""
    mine = [_stored(days_ago=d) for d in (1, 50, 200)]
    other = _stored(BEA, days_ago=1)
    store = _store_with(*mine, other)

    assert store.delete_for(ANA) == 3
    assert set(store.rows) == {other.id}
    assert store.delete_for(ANA) == 0
    assert store.delete_for("persona-inexistente") == 0


# --- purge_expired -------------------------------------------------------------------------


def test_purge_expired_logs_only_the_count() -> None:
    """Criterio 5: registra solo el número (y los días), sin usuarios, claves ni ids."""
    old = _stored(days_ago=100, key="DEMO-4")
    store = _store_with(old, _stored(BEA, days_ago=3))

    with capture_logs() as logs:
        purged = purge_expired(store, 90, NOW)

    assert purged == 1
    [event] = [e for e in logs if e.get("action") == "purge_quality"]
    assert event["count"] == 1 and event["days"] == 90
    dump = repr(event)
    assert ANA not in dump and BEA not in dump and "DEMO-4" not in dump and old.id not in dump


def test_purge_expired_without_expired_does_not_log() -> None:
    """Criterio 5 (límite): nada que purgar → 0 y sin log."""
    store = _store_with(_stored(days_ago=2))

    with capture_logs() as logs:
        assert purge_expired(store, 90, NOW) == 0

    assert [e for e in logs if e.get("action") == "purge_quality"] == []


def test_purge_expired_passes_the_retention_cutoff_to_the_store() -> None:
    """Criterio 5: `purge_expired` pide al almacén el corte de `retention_cutoff`."""
    seen: list[datetime] = []
    store = SimpleNamespace(purge_older_than=lambda cutoff: seen.append(cutoff) or 0)

    purge_expired(store, 15, NOW)  # type: ignore[arg-type]

    assert seen == [NOW - timedelta(days=15)]


# --- build_runtime purga al arrancar -------------------------------------------------------


def _patch_build_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, quality: InMemoryQualityReviewStore, days: int
) -> None:
    config = SimpleNamespace(
        settings=api_settings(quality_retention_days=days),
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
    monkeypatch.setattr(
        core.quality.SqlQualityReviewStore, "from_url", classmethod(lambda _cls, _u: quality)
    )


def _aged(days: int, state: str, key: str = "DEMO-3") -> StoredQualityReview:
    at = datetime.now(UTC) - timedelta(days=days)
    return StoredQualityReview(
        id=str(uuid4()), username=ANA, issue_key=key, created_at=at, updated_at=at, state=state
    )  # type: ignore[arg-type]


def test_build_runtime_purges_expired_reviews_at_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Criterio 5: al arrancar la API se borran las revisiones terminadas de más de N días."""
    old_done, old_error = _aged(40, "done"), _aged(35, "error", "DEMO-4")
    recent = _aged(2, "done", "DEMO-2")
    quality = _store_with(old_done, old_error, recent)
    _patch_build_runtime(monkeypatch, tmp_path, quality, days=30)

    rt = build_runtime()

    assert rt.quality is quality
    assert set(quality.rows) == {recent.id}


def test_build_runtime_purges_expired_review_left_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Criterio 5 (límite): una revisión que quedó «en marcha» hace más de N días (proceso
    caído) también debe purgarse al arrancar."""
    stale = _aged(40, "running")
    quality = _store_with(stale)
    _patch_build_runtime(monkeypatch, tmp_path, quality, days=30)

    build_runtime()

    assert stale.id not in quality.rows


# --- CLI `python -m core.quality` ----------------------------------------------------------


def test_quality_main_without_flag_prints_help_and_returns_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Criterio 5: sin `--purgar` muestra la ayuda y devuelve 2 (no toca nada)."""
    assert core.quality.main([]) == 2

    out = capsys.readouterr().out
    assert "--purgar" in out


def test_quality_main_purge_uses_settings_and_prints_only_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 5: `--purgar` lee la configuración, purga y muestra solo el número."""
    old = _stored(days_ago=4000, key="DEMO-4")
    store = _store_with(old, _stored(BEA, days_ago=0))
    urls: list[Any] = []
    settings = SimpleNamespace(
        quality_retention_days=45, sqlalchemy_url=lambda: "postgresql+psycopg://ficticia/bd"
    )
    monkeypatch.setattr(core.config, "build_config", lambda: SimpleNamespace(settings=settings))

    def fake_from_url(_cls: Any, url: Any) -> InMemoryQualityReviewStore:
        urls.append(url)
        return store

    monkeypatch.setattr(SqlQualityReviewStore, "from_url", classmethod(fake_from_url))

    assert core.quality.main(["--purgar"]) == 0

    out = capsys.readouterr().out
    assert "45 días" in out and out.strip().endswith(": 1")
    assert old.id not in out and ANA not in out and "DEMO-4" not in out
    assert "ficticia/bd" not in out
    assert urls == ["postgresql+psycopg://ficticia/bd"]
    assert old.id not in store.rows


# --- SqlQualityReviewStore sin red ---------------------------------------------------------


def test_sql_purge_older_than_is_a_delete_by_updated_at() -> None:
    """Criterio 5: la purga SQL es un DELETE con `updated_at < corte`."""
    engine = RecordingEngine()
    cutoff = NOW - timedelta(days=90)

    assert SqlQualityReviewStore(engine).purge_older_than(cutoff) == 0  # type: ignore[arg-type]

    (statement,) = engine.statements
    assert _sql(statement).startswith(
        "DELETE FROM quality_reviews WHERE quality_reviews.updated_at <"
    )
    assert list(statement.compile().params.values()) == [cutoff]


def test_sql_delete_for_is_a_delete_by_username() -> None:
    """Criterio 5: el borrado de una persona es un DELETE por `username`."""
    engine = RecordingEngine()

    SqlQualityReviewStore(engine).delete_for(ANA)  # type: ignore[arg-type]

    (statement,) = engine.statements
    assert _sql(statement).startswith(
        "DELETE FROM quality_reviews WHERE quality_reviews.username ="
    )
    assert list(statement.compile().params.values()) == [ANA]


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (
            lambda s: s.purge_older_than(NOW),
            "No se pudo purgar las revisiones de calidad antiguas.",
        ),
        (
            lambda s: s.delete_for(ANA),
            "No se pudo borrar las revisiones de calidad de la persona.",
        ),
    ],
    ids=["purge_older_than", "delete_for"],
)
def test_sql_purge_and_delete_wrap_database_errors_in_spanish(call: Any, message: str) -> None:
    """Criterio 5 (error): BD caída → ExternalServiceError en español, sin SQL ni secretos."""
    store = SqlQualityReviewStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        call(store)

    assert str(exc_info.value) == message
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None
    assert LEAKED_DETAIL not in str(exc_info.value)
    assert "quality_reviews" not in str(exc_info.value)


# --- SqlQualityReviewStore contra PostgreSQL -----------------------------------------------


@pytest.fixture
def sql_store() -> Iterator[tuple[SqlQualityReviewStore, sa.Engine]]:
    with temporary_database("quality_retention_test") as (_url, engine):
        yield SqlQualityReviewStore(engine), engine


def _backdate(engine: sa.Engine, review_id: str, days: int) -> None:
    table = core.quality.QUALITY_REVIEWS
    at = datetime.now(UTC) - timedelta(days=days)
    with engine.begin() as conn:
        conn.execute(
            table.update().where(table.c.id == review_id).values(created_at=at, updated_at=at)
        )


@pytest.mark.integration
def test_sql_purge_and_delete_against_postgres(
    sql_store: tuple[SqlQualityReviewStore, sa.Engine],
) -> None:
    """Criterio 5 (PostgreSQL): purga solo las caducadas y `delete_for` solo las de la persona."""
    store, engine = sql_store
    old, recent, other = (
        _stored(days_ago=0),
        _stored(days_ago=0, key="DEMO-2"),
        _stored(BEA, days_ago=0),
    )
    for review in (old, recent, other):
        store.create(review)
    _backdate(engine, old.id, 200)

    assert store.purge_older_than(retention_cutoff(90)) == 1
    assert store.get(old.id) is None
    assert store.get(recent.id) is not None

    assert store.delete_for(ANA) == 1
    assert store.list_for(ANA) == []
    assert [r.id for r in store.list_for(BEA)] == [other.id]
