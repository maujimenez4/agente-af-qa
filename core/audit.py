"""Auditoría de cada acción sobre un artefacto (T-25, RF-35).

Registra usuario, acción, versión, modelo y claves de Jira. Nunca guarda prompts, contenido
completo de artefactos ni secretos: `detail` solo lleva metadatos (versión, huella, plan de
publicación, modo simulación). El núcleo persiste en su propia tabla `audit_log` (anexo §11).
"""

from typing import Any, Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, Field
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError

AuditAction = Literal["create", "iterate", "approve", "publish", "discard"]
SERVICE = "postgres"

_METADATA = sa.MetaData()
AUDIT_LOG = sa.Table(
    "audit_log",
    _METADATA,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("artifact_id", sa.Uuid),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("user", sa.Text, nullable=False),
    sa.Column("jira_keys", postgresql.ARRAY(sa.Text), nullable=False),
    sa.Column("model", sa.Text),
    sa.Column("detail", postgresql.JSONB, nullable=False),
    sa.Column("at", sa.DateTime(timezone=True)),
)


class AuditEntry(BaseModel):
    artifact_id: UUID | None
    action: AuditAction
    user: str
    jira_keys: list[str] = []
    model: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class AuditTrail(Protocol):
    def record(self, entry: AuditEntry) -> None: ...
    def entries(self, artifact_id: UUID) -> list[AuditEntry]: ...


class InMemoryAuditTrail:
    """Para pruebas y para ejecutar el grafo sin base de datos."""

    def __init__(self) -> None:
        self.recorded: list[AuditEntry] = []

    def record(self, entry: AuditEntry) -> None:
        self.recorded.append(entry.model_copy(deep=True))

    def entries(self, artifact_id: UUID) -> list[AuditEntry]:
        return [e for e in self.recorded if e.artifact_id == artifact_id]


class SqlAuditTrail:
    """`audit_log` de PostgreSQL. El artefacto debe existir antes (clave foránea)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlAuditTrail":
        return cls(sa.create_engine(url, pool_pre_ping=True))

    def record(self, entry: AuditEntry) -> None:
        values = entry.model_dump(mode="json")
        values["artifact_id"] = entry.artifact_id
        self._execute(AUDIT_LOG.insert().values(**values))

    def entries(self, artifact_id: UUID) -> list[AuditEntry]:
        query = (
            sa.select(
                AUDIT_LOG.c.artifact_id,
                AUDIT_LOG.c.action,
                AUDIT_LOG.c.user,
                AUDIT_LOG.c.jira_keys,
                AUDIT_LOG.c.model,
                AUDIT_LOG.c.detail,
            )
            .where(AUDIT_LOG.c.artifact_id == artifact_id)
            .order_by(AUDIT_LOG.c.id)
        )
        rows = self._execute(query, fetch=True)
        return [AuditEntry.model_validate(dict(row)) for row in rows]

    def _execute(self, statement: sa.Executable, fetch: bool = False) -> list[Any]:
        try:
            with self._engine.begin() as conn:
                result = conn.execute(statement)
                return list(result.mappings()) if fetch else []
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo acceder al registro de auditoría.", service=SERVICE
            ) from None
