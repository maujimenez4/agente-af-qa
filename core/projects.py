"""Proyecto de Jira de cada conversación (T-50, RF-02, RF-14).

El proyecto se elige al empezar entre los que ve la conexión (`list_projects`), viene
preseleccionado el último que usó la persona y queda fijo en la conversación. Una clave de
incidencia de otro proyecto lo cambia (`project_of`). También valida las claves escritas a mano.
"""

import re
from dataclasses import dataclass
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adapters.base import IssueTracker, ProjectSummary
from adapters.errors import ExternalServiceError, NotFoundError

PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
ISSUE_KEY = re.compile(r"^([A-Z][A-Z0-9_]+)-\d+$")
_MAX_SHOWN = 50
SERVICE = "postgres"

_METADATA = sa.MetaData()
USER_LAST_PROJECT = sa.Table(
    "user_last_project",
    _METADATA,
    sa.Column("username", sa.String, primary_key=True),
    sa.Column("project_key", sa.String, nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


def normalize_project_key(raw: str) -> str:
    """Clave de proyecto escrita a mano → `DEMO`; `ValueError` con mensaje para la UI."""
    key = raw.strip().upper()
    if not PROJECT_KEY.fullmatch(key):
        raise ValueError(
            f"«{raw.strip()[:_MAX_SHOWN]}» no es una clave de proyecto válida "
            "(formato esperado: PROYECTO)."
        )
    return key


def normalize_issue_key(raw: str) -> str:
    """Clave de incidencia escrita a mano → `DEMO-12`; `ValueError` con mensaje para la UI."""
    key = raw.strip().upper()
    if not ISSUE_KEY.fullmatch(key):
        raise ValueError(
            f"«{raw.strip()[:_MAX_SHOWN]}» no es una clave de Jira válida "
            "(formato esperado: PROYECTO-123)."
        )
    return key


def project_of(issue_key: str) -> str:
    """Proyecto al que pertenece una clave de incidencia (`DEMO-12` → `DEMO`)."""
    match = ISSUE_KEY.fullmatch(issue_key)
    if match is None:
        raise ValueError(f"Clave de Jira no válida: {issue_key[:_MAX_SHOWN]!r}.")
    return match.group(1)


# --- Último proyecto por usuario ---------------------------------------------------------------


class LastProjectStore(Protocol):
    def get(self, username: str) -> str | None: ...
    def set(self, username: str, project_key: str) -> None: ...


class InMemoryLastProjectStore:
    def __init__(self) -> None:
        self.projects: dict[str, str] = {}

    def get(self, username: str) -> str | None:
        return self.projects.get(username)

    def set(self, username: str, project_key: str) -> None:
        self.projects[username] = project_key


class SqlLastProjectStore:
    """Tabla `user_last_project` (migración `0003`)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlLastProjectStore":
        return cls(sa.create_engine(url, pool_pre_ping=True))

    def get(self, username: str) -> str | None:
        query = sa.select(USER_LAST_PROJECT.c.project_key).where(
            USER_LAST_PROJECT.c.username == username
        )
        try:
            with self._engine.begin() as conn:
                return conn.execute(query).scalar_one_or_none()
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo leer el último proyecto usado.", service=SERVICE
            ) from None

    def set(self, username: str, project_key: str) -> None:
        upsert = postgresql.insert(USER_LAST_PROJECT).values(
            username=username, project_key=project_key, updated_at=sa.func.now()
        )
        upsert = upsert.on_conflict_do_update(
            index_elements=[USER_LAST_PROJECT.c.username],
            set_={"project_key": upsert.excluded.project_key, "updated_at": sa.func.now()},
        )
        try:
            with self._engine.begin() as conn:
                conn.execute(upsert)
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo guardar el último proyecto usado.", service=SERVICE
            ) from None


# --- Elección del proyecto ----------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectChoice:
    """Lo que la UI muestra al empezar: proyectos visibles y el preseleccionado."""

    projects: list[ProjectSummary]
    preselected: str | None


class ProjectService:
    """Proyectos que ve la conexión, preselección y validación del proyecto elegido."""

    def __init__(
        self,
        tracker: IssueTracker,
        last_projects: LastProjectStore,
        default_project: str | None = None,
    ) -> None:
        self._tracker = tracker
        self._last = last_projects
        self._default = default_project

    def available(self, user: str) -> ProjectChoice:
        """Todos los proyectos visibles; preselecciona el último usado o, si no, el de `.env`."""
        projects = self._tracker.list_projects()
        visible = {p.key for p in projects}
        preselected = next(
            (key for key in (self._last.get(user), self._default) if key in visible), None
        )
        return ProjectChoice(projects=projects, preselected=preselected)

    def choose(self, user: str, raw_project: str) -> str:
        """Valida el proyecto escrito o elegido, lo recuerda como último usado y lo devuelve."""
        project = normalize_project_key(raw_project)
        if project not in {p.key for p in self._tracker.list_projects()}:
            raise NotFoundError(
                f"El proyecto {project} no existe o la conexión no tiene acceso a él.",
                service="jira",
            )
        self._last.set(user, project)
        return project
