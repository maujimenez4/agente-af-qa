"""Consultas de lectura sobre el consumo de los LLM para la UI (RF-43, RNF-27).

`SqlUsageQueries` lee la tabla `llm_usage` (la escribe `adapters/llm/usage.SqlUsageRecorder`) y
`InMemoryUsageQueries` lee los registros de un `InMemoryUsageRecorder`; las dos ofrecen la misma
API. Las agregaciones se hacen en Python sobre una ventana de fechas: el volumen del MVP es
pequeño y así el resultado no depende del motor de base de datos. Los días se cuentan en la zona
horaria indicada (`Europe/Madrid` por defecto).
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from decimal import Decimal
from typing import Literal, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa

Dimension = Literal["day", "task", "model", "provider"]
DIMENSIONS: tuple[Dimension, ...] = ("day", "task", "model", "provider")


def _madrid() -> tzinfo:
    try:
        return ZoneInfo("Europe/Madrid")
    except ZoneInfoNotFoundError:  # imagen sin datos de zonas horarias (tzdata)
        return UTC


DEFAULT_TZ = _madrid()
MAX_RECENT = 200

# Columnas de `llm_usage` que se leen (migrations/versions/0001_initial.py).
_METADATA = sa.MetaData()
LLM_USAGE = sa.Table(
    "llm_usage",
    _METADATA,
    sa.Column("task", sa.Text(), nullable=False),
    sa.Column("provider", sa.Text(), nullable=False),
    sa.Column("model", sa.Text(), nullable=False),
    sa.Column("input_tokens", sa.Integer(), nullable=False),
    sa.Column("output_tokens", sa.Integer(), nullable=False),
    sa.Column("est_cost", sa.Numeric(12, 6), nullable=False),
    sa.Column("latency_ms", sa.Integer()),
    sa.Column("artifact_id", sa.Uuid()),
    sa.Column("at", sa.DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class UsageCall:
    """Una llamada registrada, tal como la muestra la UI (sin prompts ni contenido)."""

    at: datetime
    task: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    est_cost: Decimal
    latency_ms: int | None
    artifact_id: UUID | None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class UsageTotal:
    """Suma de las llamadas de un grupo (`key`: el día ISO, la tarea, el modelo o el proveedor)."""

    key: str
    calls: int
    input_tokens: int
    output_tokens: int
    est_cost: Decimal

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class UsageQueries(Protocol):
    def calls(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageCall]:
        """Llamadas con `since <= at < until`, de la más reciente a la más antigua."""
        ...


def totals_by(
    queries: UsageQueries,
    dimension: Dimension,
    since: datetime | None = None,
    until: datetime | None = None,
    *,
    tz: tzinfo = DEFAULT_TZ,
) -> list[UsageTotal]:
    """Tokens y coste estimado por día, tarea, modelo o proveedor.

    Por día, en orden cronológico; en el resto, de mayor a menor consumo de tokens.
    """
    return aggregate(queries.calls(since, until), dimension, tz=tz)


def recent(queries: UsageQueries, limit: int = 20) -> list[UsageCall]:
    """Últimas `limit` llamadas (como mucho `MAX_RECENT`), de la más reciente a la más antigua."""
    if limit < 1:
        raise ValueError("El número de llamadas debe ser un entero positivo.")
    return queries.calls(limit=min(limit, MAX_RECENT))


def aggregate(
    calls: Iterable[UsageCall], dimension: Dimension, *, tz: tzinfo = DEFAULT_TZ
) -> list[UsageTotal]:
    if dimension not in DIMENSIONS:
        raise ValueError(f"Dimensión de consumo no válida; usa una de: {', '.join(DIMENSIONS)}.")
    key_of = _key_function(dimension, tz)
    groups: dict[str, list[UsageCall]] = {}
    for call in calls:
        groups.setdefault(key_of(call), []).append(call)
    totals = [_total(key, group) for key, group in groups.items()]
    if dimension == "day":
        return sorted(totals, key=lambda t: t.key)
    return sorted(totals, key=lambda t: (-t.total_tokens, t.key))


class SqlUsageQueries:
    """Lectura de `llm_usage` con SQLAlchemy Core."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlUsageQueries":
        return cls(sa.create_engine(url, pool_pre_ping=True, hide_parameters=True))

    def calls(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageCall]:
        table = LLM_USAGE
        query = sa.select(table).order_by(table.c.at.desc())
        if since is not None:
            query = query.where(table.c.at >= since)
        if until is not None:
            query = query.where(table.c.at < until)
        if limit is not None:
            query = query.limit(limit)
        with self._engine.connect() as conn:
            rows = conn.execute(query).mappings().all()
        return [_from_row(row) for row in rows]


class _RecordLike(Protocol):
    task: object
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    est_cost: Decimal
    latency_ms: int
    artifact_id: UUID | None
    at: datetime


class InMemoryUsageQueries:
    """Las mismas consultas sobre los registros en memoria (pruebas y ejecución sin BD)."""

    def __init__(self, records: Callable[[], Sequence[_RecordLike]]) -> None:
        self._records = records

    def calls(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> list[UsageCall]:
        selected = [
            _from_record(r)
            for r in self._records()
            if (since is None or r.at >= since) and (until is None or r.at < until)
        ]
        ordered = sorted(selected, key=lambda c: c.at, reverse=True)
        return ordered if limit is None else ordered[:limit]


def _key_function(dimension: Dimension, tz: tzinfo) -> Callable[[UsageCall], str]:
    if dimension == "day":
        return lambda call: _local_day(call.at, tz).isoformat()
    return lambda call: str(getattr(call, dimension))


def _local_day(at: datetime, tz: tzinfo) -> date:
    return _aware(at).astimezone(tz).date()


def _aware(at: datetime) -> datetime:
    # SQLite devuelve fechas sin zona: se interpretan como UTC, igual que se escriben.
    return at if at.tzinfo is not None else at.replace(tzinfo=UTC)


def _total(key: str, calls: list[UsageCall]) -> UsageTotal:
    return UsageTotal(
        key=key,
        calls=len(calls),
        input_tokens=sum(c.input_tokens for c in calls),
        output_tokens=sum(c.output_tokens for c in calls),
        est_cost=sum((c.est_cost for c in calls), Decimal("0")),
    )


def _from_row(row: sa.RowMapping) -> UsageCall:
    return UsageCall(
        at=_aware(row["at"]),
        task=row["task"],
        provider=row["provider"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        est_cost=Decimal(row["est_cost"]),
        latency_ms=row["latency_ms"],
        artifact_id=row["artifact_id"],
    )


def _from_record(record: _RecordLike) -> UsageCall:
    task = record.task
    return UsageCall(
        at=record.at,
        task=str(getattr(task, "value", task)),
        provider=record.provider,
        model=record.model,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        est_cost=record.est_cost,
        latency_ms=record.latency_ms,
        artifact_id=record.artifact_id,
    )
