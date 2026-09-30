"""Registro del consumo de los LLM en la tabla `llm_usage` (RF-43, RNF-27).

Cada llamada correcta genera un `UsageRecord`. `SqlUsageRecorder` lo guarda en PostgreSQL y
`InMemoryUsageRecorder` sirve para pruebas y para ejecutar sin base de datos.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID

import sqlalchemy as sa

from adapters.base import TaskType

# Réplica de las columnas de `llm_usage` (migrations/versions/0001_initial.py) que se escriben;
# `id` lo genera la base de datos.
_METADATA = sa.MetaData()
LLM_USAGE_TABLE = sa.Table(
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
class UsageRecord:
    task: TaskType
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    est_cost: Decimal = Decimal("0")  # modelos gratuitos (D-14)
    artifact_id: UUID | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class UsageRecorder(Protocol):
    def record(self, usage: UsageRecord) -> None: ...
    def tokens_since(self, since: datetime) -> int: ...


@dataclass
class InMemoryUsageRecorder:
    records: list[UsageRecord] = field(default_factory=list)

    def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    def tokens_since(self, since: datetime) -> int:
        return sum(r.total_tokens for r in self.records if r.at >= since)


class SqlUsageRecorder:
    """Escribe en `llm_usage` con SQLAlchemy Core (una transacción por registro)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(self, usage: UsageRecord) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                LLM_USAGE_TABLE.insert().values(
                    task=usage.task.value,
                    provider=usage.provider,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    est_cost=usage.est_cost,
                    latency_ms=usage.latency_ms,
                    artifact_id=usage.artifact_id,
                    at=usage.at,
                )
            )

    def tokens_since(self, since: datetime) -> int:
        table = LLM_USAGE_TABLE
        query = sa.select(
            sa.func.coalesce(sa.func.sum(table.c.input_tokens + table.c.output_tokens), 0)
        ).where(table.c.at >= since)
        with self._engine.connect() as conn:
            return int(conn.execute(query).scalar_one())
