"""Versionado de artefactos en `artifact_versions` (RF-05, RF-19, RNF-16).

Cada versión es inmutable: guardar otra vez la misma versión con el mismo contenido no hace
nada y con contenido distinto es un error. Como `artifact_versions` tiene clave foránea a
`artifacts`, `save` también inserta o actualiza la fila del artefacto (decisión de T-19).
"""

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError, NotFoundError
from core.impact.diff import diff_stories
from schemas.artifact import Artifact
from schemas.impact import StoryDiff
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

SERVICE = "postgres"
CONNECT_TIMEOUT_S = 5
STATEMENT_TIMEOUT_MS = 10_000

# Réplica de las columnas de la migración 0001 que se leen o escriben.
_METADATA = sa.MetaData()
ARTIFACTS = sa.Table(
    "artifacts",
    _METADATA,
    sa.Column("id", sa.Uuid(), primary_key=True),
    sa.Column("type", sa.Text(), nullable=False),
    sa.Column("status", sa.Text(), nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.Column("origin_key", sa.Text()),
    sa.Column("jira_key", sa.Text()),
    sa.Column("content", postgresql.JSONB(), nullable=False),
    sa.Column("impact", postgresql.JSONB()),
    sa.Column("created_by", sa.Text(), nullable=False),
    sa.Column("model_used", sa.Text()),
    sa.Column("prompt_version", sa.Text()),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)
ARTIFACT_VERSIONS = sa.Table(
    "artifact_versions",
    _METADATA,
    sa.Column("artifact_id", sa.Uuid(), primary_key=True),
    sa.Column("version", sa.Integer(), primary_key=True),
    sa.Column("content", postgresql.JSONB(), nullable=False),
)


class VersionConflictError(ExternalServiceError):
    """Se intenta sobrescribir una versión ya guardada con otro contenido."""


class StoryVersionStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "StoryVersionStore":
        """Solo `sa.URL`: su repr oculta la contraseña si la URL resultara inválida."""
        engine = sa.create_engine(
            url,
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": CONNECT_TIMEOUT_S,
                "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            },
        )
        return cls(engine)

    def save(self, artifact: Artifact) -> None:
        """Guarda la versión actual del artefacto y actualiza su fila en `artifacts`."""
        content = artifact.content.model_dump(mode="json")
        row = {
            "id": artifact.id,
            "type": artifact.type.value,
            "status": artifact.status.value,
            "version": artifact.version,
            "origin_key": artifact.origin_key,
            "jira_key": getattr(artifact.content, "jira_key", None),
            "content": content,
            "impact": artifact.impact.model_dump(mode="json") if artifact.impact else None,
            "created_by": artifact.created_by,
            "model_used": artifact.model_used,
            "prompt_version": artifact.prompt_version,
        }
        upsert = postgresql.insert(ARTIFACTS).values(**row)
        upsert = upsert.on_conflict_do_update(
            index_elements=[ARTIFACTS.c.id],
            set_={k: upsert.excluded[k] for k in row if k not in ("id", "created_by")}
            | {"updated_at": sa.func.now()},
            # Volver a guardar una versión antigua no hace retroceder la fila del artefacto.
            where=ARTIFACTS.c.version <= upsert.excluded.version,
        )
        with self._transaction() as conn:
            existing = conn.execute(
                sa.select(ARTIFACT_VERSIONS.c.content).where(
                    ARTIFACT_VERSIONS.c.artifact_id == artifact.id,
                    ARTIFACT_VERSIONS.c.version == artifact.version,
                )
            ).scalar_one_or_none()
            if existing is not None and _canonical(existing) != _canonical(content):
                raise VersionConflictError(
                    f"La versión {artifact.version} de este artefacto ya existe con otro "
                    "contenido; las versiones no se pueden modificar.",
                    service=SERVICE,
                )
            conn.execute(upsert)
            if existing is None:
                conn.execute(
                    ARTIFACT_VERSIONS.insert().values(
                        artifact_id=artifact.id, version=artifact.version, content=content
                    )
                )

    def update_status(self, artifact_id: UUID, status: str, jira_key: str | None = None) -> None:
        """Actualiza estado (y clave de Jira, si llega) sin tocar el contenido de las versiones."""
        values: dict[str, Any] = {"status": status, "updated_at": sa.func.now()}
        if jira_key:
            values["jira_key"] = jira_key
        with self._transaction() as conn:
            conn.execute(ARTIFACTS.update().where(ARTIFACTS.c.id == artifact_id).values(**values))

    def published_by_agent(self, jira_key: str) -> bool:
        """El agente publicó en Jira una HU con esta clave (PA-104, tarjeta de QA 1)."""
        query = sa.select(
            sa.exists().where(
                ARTIFACTS.c.jira_key == jira_key,
                ARTIFACTS.c.type == "user_story",
                ARTIFACTS.c.status == "published",
            )
        )
        with self._transaction() as conn:
            return bool(conn.execute(query).scalar())

    def versions(self, artifact_id: UUID) -> list[int]:
        query = (
            sa.select(ARTIFACT_VERSIONS.c.version)
            .where(ARTIFACT_VERSIONS.c.artifact_id == artifact_id)
            .order_by(ARTIFACT_VERSIONS.c.version)
        )
        with self._transaction() as conn:
            return list(conn.execute(query).scalars())

    def get(self, artifact_id: UUID, version: int) -> UserStory | TestSuite:
        with self._transaction() as conn:
            kind = conn.execute(
                sa.select(ARTIFACTS.c.type).where(ARTIFACTS.c.id == artifact_id)
            ).scalar_one_or_none()
            content = conn.execute(
                sa.select(ARTIFACT_VERSIONS.c.content).where(
                    ARTIFACT_VERSIONS.c.artifact_id == artifact_id,
                    ARTIFACT_VERSIONS.c.version == version,
                )
            ).scalar_one_or_none()
        if kind is None or content is None:
            raise NotFoundError(
                f"No existe la versión {version} del artefacto solicitado.", service=SERVICE
            )
        model = TestSuite if kind == "test_suite" else UserStory
        return model.model_validate(content)

    def latest(self, artifact_id: UUID) -> UserStory | TestSuite:
        versions = self.versions(artifact_id)
        if not versions:
            raise NotFoundError("El artefacto solicitado no tiene versiones.", service=SERVICE)
        return self.get(artifact_id, versions[-1])

    def diff(self, artifact_id: UUID, before: int, after: int) -> list[StoryDiff]:
        """Diff por campo entre dos versiones de una HU (RF-19)."""
        old, new = self.get(artifact_id, before), self.get(artifact_id, after)
        if not isinstance(old, UserStory) or not isinstance(new, UserStory):
            raise NotFoundError("El diff por campo solo está disponible para HU.", service=SERVICE)
        return diff_stories(old, new)

    def _transaction(self) -> AbstractContextManager[sa.Connection]:
        return _transaction(self._engine)


@contextmanager
def _transaction(engine: sa.Engine) -> Iterator[sa.Connection]:
    """`engine.begin()` que traduce los errores de base de datos a `ExternalServiceError`."""
    try:
        with engine.begin() as conn:
            yield conn
    except sa.exc.OperationalError:
        raise ExternalServiceError(
            "No se pudo acceder a la base de datos de versiones.", service=SERVICE
        ) from None
    except sa.exc.DBAPIError:
        raise ExternalServiceError(
            "La base de datos de versiones rechazó la operación.", service=SERVICE
        ) from None


def _canonical(content: Any) -> str:
    return json.dumps(content, sort_keys=True, ensure_ascii=False)
