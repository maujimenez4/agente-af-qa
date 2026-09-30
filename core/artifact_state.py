"""Estado de trabajo de cada artefacto que debe sobrevivir a un reinicio (T-25).

Guarda, por artefacto, el registro de aprobaciones (PA-06) y la versión de partida de Jira
(PA-37). Es persistencia del núcleo en su propia tabla `artifact_state` (anexo §11).
"""

from typing import Any, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError

SERVICE = "postgres"
_METADATA = sa.MetaData()
ARTIFACT_STATE = sa.Table(
    "artifact_state",
    _METADATA,
    sa.Column("artifact_id", sa.Uuid, primary_key=True),
    sa.Column("state", postgresql.JSONB, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


class ArtifactStateStore(Protocol):
    def load(self, artifact_id: str) -> dict[str, Any] | None: ...
    def save(self, artifact_id: str, state: dict[str, Any]) -> None: ...


class InMemoryArtifactStateStore:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        state = self.states.get(artifact_id)
        return dict(state) if state is not None else None

    def save(self, artifact_id: str, state: dict[str, Any]) -> None:
        self.states[artifact_id] = dict(state)


class SqlArtifactStateStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlArtifactStateStore":
        return cls(sa.create_engine(url, pool_pre_ping=True))

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        query = sa.select(ARTIFACT_STATE.c.state).where(
            ARTIFACT_STATE.c.artifact_id == UUID(artifact_id)
        )
        try:
            with self._engine.begin() as conn:
                return conn.execute(query).scalar_one_or_none()
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo leer el estado del artefacto.", service=SERVICE
            ) from None

    def save(self, artifact_id: str, state: dict[str, Any]) -> None:
        upsert = postgresql.insert(ARTIFACT_STATE).values(
            artifact_id=UUID(artifact_id), state=state, updated_at=sa.func.now()
        )
        upsert = upsert.on_conflict_do_update(
            index_elements=[ARTIFACT_STATE.c.artifact_id],
            set_={"state": upsert.excluded.state, "updated_at": sa.func.now()},
        )
        try:
            with self._engine.begin() as conn:
                conn.execute(upsert)
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo guardar el estado del artefacto.", service=SERVICE
            ) from None
