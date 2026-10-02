"""Pruebas de core/usage.py (T-32 · RF-43, RNF-27).

Consultas de consumo para la UI sobre registros sintéticos, en memoria y en SQLite en memoria.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

from adapters.base import TaskType
from adapters.llm.usage import LLM_USAGE_TABLE, InMemoryUsageRecorder, SqlUsageRecorder, UsageRecord
from core.usage import (
    DIMENSIONS,
    MAX_RECENT,
    InMemoryUsageQueries,
    SqlUsageQueries,
    UsageCall,
    UsageQueries,
    aggregate,
    recent,
    totals_by,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _record(
    input_tokens: int = 10,
    output_tokens: int = 5,
    *,
    at: datetime = NOW,
    task: TaskType = TaskType.GENERATE_STORY,
    provider: str = "proveedor-a",
    model: str = "modelo-a",
    est_cost: Decimal = Decimal("0"),
    **kwargs: Any,
) -> UsageRecord:
    return UsageRecord(
        task=task,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=25,
        est_cost=est_cost,
        at=at,
        **kwargs,
    )


def _queries(*records: UsageRecord) -> InMemoryUsageQueries:
    recorder = InMemoryUsageRecorder()
    for record in records:
        recorder.record(record)
    return InMemoryUsageQueries(lambda: recorder.records)


@pytest.fixture
def engine() -> sa.Engine:
    engine = sa.create_engine("sqlite://")
    LLM_USAGE_TABLE.metadata.create_all(engine)
    return engine


def _mixed_records() -> list[UsageRecord]:
    artifact = uuid4()
    return [
        _record(100, 50, at=NOW, task=TaskType.GENERATE_STORY, provider="groq-ficticio",
                model="modelo-grande", est_cost=Decimal("0.001500"), artifact_id=artifact),
        _record(10, 5, at=NOW + timedelta(hours=1), task=TaskType.NL_TO_JQL,
                provider="local-ficticio", model="modelo-pequeno", est_cost=Decimal("0.000100")),
        _record(30, 20, at=NOW - timedelta(days=1), task=TaskType.GENERATE_STORY,
                provider="local-ficticio", model="modelo-grande", est_cost=Decimal("0.000400")),
        _record(1, 1, at=NOW - timedelta(days=2, minutes=5), task=TaskType.CLASSIFY_SOURCE,
                provider="groq-ficticio", model="modelo-pequeno"),
    ]  # fmt: skip


# --- totals_by: día y zona horaria ---------------------------------------------------------


def test_totals_by_day_counts_late_utc_call_as_next_day_in_madrid() -> None:
    """CA-7: 23:30 UTC (verano, CEST +2) es el día siguiente en Europe/Madrid."""
    queries = _queries(
        _record(10, 0, at=datetime(2026, 10, 1, 23, 30, tzinfo=UTC)),
        _record(5, 0, at=datetime(2026, 10, 1, 21, 59, tzinfo=UTC)),  # 23:59 en Madrid
    )

    totals = totals_by(queries, "day")

    assert [(t.key, t.total_tokens, t.calls) for t in totals] == [
        ("2026-10-01", 5, 1),
        ("2026-10-02", 10, 1),
    ]


def test_totals_by_day_uses_winter_offset_in_madrid() -> None:
    """CA-7: en invierno (CET +1) 23:30 UTC también es el día siguiente; 22:59 UTC no."""
    queries = _queries(
        _record(1, 0, at=datetime(2026, 1, 15, 23, 30, tzinfo=UTC)),
        _record(2, 0, at=datetime(2026, 1, 15, 22, 59, tzinfo=UTC)),
    )

    assert [t.key for t in totals_by(queries, "day")] == ["2026-01-15", "2026-01-16"]


def test_totals_by_day_uses_configured_timezone() -> None:
    """CA-7: la zona horaria es configurable (UTC → mismo día)."""
    queries = _queries(_record(10, 0, at=datetime(2026, 10, 1, 23, 30, tzinfo=UTC)))

    assert [t.key for t in totals_by(queries, "day", tz=ZoneInfo("UTC"))] == ["2026-10-01"]
    assert [t.key for t in totals_by(queries, "day", tz=ZoneInfo("America/Bogota"))] == [
        "2026-10-01"
    ]


def test_totals_by_day_orders_chronologically() -> None:
    """CA-7: por día el orden es cronológico, no por consumo."""
    totals = totals_by(_queries(*_mixed_records()), "day")

    assert [t.key for t in totals] == ["2026-09-28", "2026-09-29", "2026-09-30"]
    assert [t.calls for t in totals] == [1, 1, 2]


def test_aggregate_treats_naive_datetimes_as_utc() -> None:
    """CA-7 (límite): una fecha sin zona (SQLite) se interpreta como UTC."""
    call = UsageCall(
        at=datetime(2026, 10, 1, 23, 30),
        task="generate_story",
        provider="p",
        model="m",
        input_tokens=1,
        output_tokens=1,
        est_cost=Decimal("0"),
        latency_ms=None,
        artifact_id=None,
    )

    assert [t.key for t in aggregate([call], "day")] == ["2026-10-02"]


# --- totals_by: tarea, modelo, proveedor ---------------------------------------------------


def test_totals_by_task_sums_and_orders_by_tokens_desc() -> None:
    """CA-7: por tarea, suma de tokens y orden de mayor a menor consumo."""
    totals = totals_by(_queries(*_mixed_records()), "task")

    assert [(t.key, t.calls, t.input_tokens, t.output_tokens) for t in totals] == [
        ("generate_story", 2, 130, 70),
        ("nl_to_jql", 1, 10, 5),
        ("classify_source", 1, 1, 1),
    ]


def test_totals_by_model_and_provider_group_by_key() -> None:
    """CA-7: agrupación por modelo y por proveedor."""
    queries = _queries(*_mixed_records())

    by_model = {t.key: t.total_tokens for t in totals_by(queries, "model")}
    by_provider = {t.key: t.total_tokens for t in totals_by(queries, "provider")}

    assert by_model == {"modelo-grande": 200, "modelo-pequeno": 17}
    assert by_provider == {"groq-ficticio": 152, "local-ficticio": 65}
    assert [t.key for t in totals_by(queries, "provider")] == ["groq-ficticio", "local-ficticio"]


def test_totals_by_breaks_ties_by_key() -> None:
    """CA-7 (límite): con el mismo consumo, el orden es alfabético por clave."""
    queries = _queries(
        _record(5, 5, provider="zeta-ficticio"),
        _record(4, 6, provider="alfa-ficticio"),
        _record(1, 0, provider="beta-ficticio"),
    )

    assert [t.key for t in totals_by(queries, "provider")] == [
        "alfa-ficticio",
        "zeta-ficticio",
        "beta-ficticio",
    ]


def test_totals_by_sums_est_cost_as_decimal() -> None:
    """CA-7: el coste estimado se suma con Decimal, sin errores de coma flotante."""
    queries = _queries(
        _record(est_cost=Decimal("0.1")),
        _record(est_cost=Decimal("0.2")),
        _record(est_cost=Decimal("0.000001")),
    )

    (total,) = totals_by(queries, "task")

    assert isinstance(total.est_cost, Decimal)
    assert total.est_cost == Decimal("0.300001")


def test_totals_by_returns_zero_cost_when_free_models() -> None:
    """CA-7 · D-14: con modelos gratuitos el coste es Decimal 0."""
    (total,) = totals_by(_queries(_record()), "model")

    assert total.est_cost == Decimal("0")
    assert isinstance(total.est_cost, Decimal)


def test_totals_by_returns_empty_when_no_calls() -> None:
    """CA-7 (límite): sin registros, lista vacía en cualquier dimensión."""
    for dimension in DIMENSIONS:
        assert totals_by(_queries(), dimension) == []


@pytest.mark.parametrize("dimension", ["user", "DAY", "", "artifact_id"])
def test_totals_by_raises_value_error_when_dimension_invalid(dimension: str) -> None:
    """CA-7 (error): una dimensión no válida → ValueError en español."""
    with pytest.raises(ValueError, match="no válida"):
        totals_by(_queries(_record()), dimension)  # type: ignore[arg-type]


# --- Ventana since/until -------------------------------------------------------------------


def test_totals_by_window_includes_since_and_excludes_until() -> None:
    """CA-7 (límite): `since` es inclusivo y `until` exclusivo."""
    queries = _queries(
        _record(1, 0, at=NOW - timedelta(seconds=1)),
        _record(10, 0, at=NOW),
        _record(100, 0, at=NOW + timedelta(hours=1) - timedelta(microseconds=1)),
        _record(1000, 0, at=NOW + timedelta(hours=1)),
    )

    (total,) = totals_by(queries, "task", since=NOW, until=NOW + timedelta(hours=1))

    assert total.input_tokens == 110
    assert total.calls == 2


def test_totals_by_window_with_only_since_or_until() -> None:
    """CA-7: cada extremo de la ventana es opcional."""
    queries = _queries(_record(1, 0, at=NOW - timedelta(days=1)), _record(2, 0, at=NOW))

    assert totals_by(queries, "task", since=NOW)[0].input_tokens == 2
    assert totals_by(queries, "task", until=NOW)[0].input_tokens == 1


# --- recent --------------------------------------------------------------------------------


def test_recent_returns_latest_first_with_limit() -> None:
    """CA-7: últimas llamadas de la más reciente a la más antigua, con límite."""
    records = [_record(i, 0, at=NOW + timedelta(minutes=i)) for i in range(5)]
    queries = _queries(*reversed(records))

    calls = recent(queries, limit=3)

    assert [c.input_tokens for c in calls] == [4, 3, 2]
    assert all(isinstance(c, UsageCall) for c in calls)


def test_recent_defaults_to_twenty_calls() -> None:
    """CA-7: por defecto, 20 llamadas."""
    queries = _queries(*[_record(at=NOW + timedelta(seconds=i)) for i in range(25)])

    assert len(recent(queries)) == 20


def test_recent_caps_limit_at_max_recent() -> None:
    """CA-7 (límite): nunca más de MAX_RECENT (200) llamadas."""
    queries = _queries(*[_record(at=NOW + timedelta(seconds=i)) for i in range(MAX_RECENT + 5)])

    assert MAX_RECENT == 200
    assert len(recent(queries, limit=1000)) == MAX_RECENT
    assert len(recent(queries, limit=MAX_RECENT)) == MAX_RECENT


class SpyQueries:
    def __init__(self) -> None:
        self.limits: list[int | None] = []

    def calls(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageCall]:
        self.limits.append(limit)
        return []


def test_recent_passes_capped_limit_to_queries() -> None:
    """CA-7: el tope se aplica antes de consultar (no se leen 1000 filas)."""
    spy = SpyQueries()

    recent(spy, limit=1000)
    recent(spy, limit=1)

    assert spy.limits == [MAX_RECENT, 1]


@pytest.mark.parametrize("limit", [0, -1])
def test_recent_raises_value_error_when_limit_below_one(limit: int) -> None:
    """CA-7 (error): limit < 1 → ValueError en español."""
    with pytest.raises(ValueError, match="positivo"):
        recent(_queries(_record()), limit=limit)


def test_usage_call_hides_prompt_content() -> None:
    """CA-7 · RNF-02: UsageCall solo lleva metadatos, nunca contenido de prompts."""
    (call,) = recent(_queries(_record()))

    assert set(vars(call)) == {
        "at",
        "task",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "est_cost",
        "latency_ms",
        "artifact_id",
    }
    assert call.total_tokens == 15


# --- Equivalencia memoria / SQL -------------------------------------------------------------


def _sql_queries(engine: sa.Engine, records: list[UsageRecord]) -> SqlUsageQueries:
    recorder = SqlUsageRecorder(engine)
    for record in records:
        recorder.record(record)
    return SqlUsageQueries(engine)


def _normalized(call: UsageCall) -> tuple[Any, ...]:
    at = call.at if call.at.tzinfo else call.at.replace(tzinfo=UTC)
    return (
        at.astimezone(UTC),
        call.task,
        call.provider,
        call.model,
        call.input_tokens,
        call.output_tokens,
        call.est_cost,
        call.latency_ms,
        call.artifact_id,
    )


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_sql_and_memory_queries_give_same_totals(engine: sa.Engine, dimension: Any) -> None:
    """CA-7: InMemoryUsageQueries y SqlUsageQueries agregan igual los mismos registros."""
    records = _mixed_records()
    memory, sql = _queries(*records), _sql_queries(engine, records)

    assert totals_by(sql, dimension) == totals_by(memory, dimension)
    window: dict[str, datetime] = {"since": NOW - timedelta(days=1), "until": NOW}
    assert totals_by(sql, dimension, **window) == totals_by(memory, dimension, **window)


def test_sql_and_memory_queries_give_same_recent_calls(engine: sa.Engine) -> None:
    """CA-7: `recent` devuelve las mismas llamadas y en el mismo orden en memoria y en SQL."""
    records = _mixed_records()
    memory, sql = _queries(*records), _sql_queries(engine, records)

    for limit in (1, 3, 20):
        assert [_normalized(c) for c in recent(sql, limit)] == [
            _normalized(c) for c in recent(memory, limit)
        ]


def test_sql_queries_apply_window_and_limit(engine: sa.Engine) -> None:
    """CA-7: SqlUsageQueries filtra por ventana (until exclusivo) y limita en la consulta."""
    sql = _sql_queries(
        engine,
        [_record(i, 0, at=NOW + timedelta(minutes=i)) for i in range(5)],
    )

    calls = sql.calls(since=NOW + timedelta(minutes=1), until=NOW + timedelta(minutes=4))

    assert [c.input_tokens for c in calls] == [3, 2, 1]
    assert [c.input_tokens for c in sql.calls(limit=2)] == [4, 3]


def test_queries_satisfy_usage_queries_protocol() -> None:
    """CA-7: ambas implementaciones ofrecen la misma API (`calls`)."""
    implementations: list[Callable[..., Any]] = [
        InMemoryUsageQueries(lambda: []).calls,
        SqlUsageQueries(sa.create_engine("sqlite://")).calls,
    ]
    for calls in implementations:
        assert callable(calls)
    protocol_user: UsageQueries = InMemoryUsageQueries(lambda: [])
    assert protocol_user.calls() == []
