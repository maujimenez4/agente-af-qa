"""Índice de conversaciones por usuario (T-52, RF-20, RF-47).

El estado de cada conversación vive en el checkpointer de LangGraph; esta tabla solo resume lo
que la barra lateral necesita (proyecto, flujo, estado y versión) y quién es su dueño. La
escriben los nodos del grafo, así que el listado coincide con el grafo. El título se compone
con el flujo y la clave: nunca guarda el texto libre de la persona (decisión del usuario).
"""

import re
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import uuid4

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError, NotFoundError

SERVICE = "postgres"
ConversationStatus = Literal[
    "started", "in_review", "approved", "published", "simulated", "discarded"
]
_FLOW_TITLES = {
    ("functional", "need"): "Nueva necesidad",
    ("functional", "story"): "Evolucionar",
    ("functional", "epic"): "HU nueva en la épica",  # PA-317
    ("qa", "story"): "Preparar pruebas de",
}

_METADATA = sa.MetaData()
CONVERSATIONS = sa.Table(
    "conversations",
    _METADATA,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("username", sa.String, nullable=False),
    sa.Column("project_key", sa.String, nullable=False),
    sa.Column("mode", sa.String, nullable=False),
    sa.Column("origin_kind", sa.String, nullable=False),
    sa.Column("origin_key", sa.String),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("artifact_id", sa.Uuid),
    sa.Column("version", sa.Integer),
    sa.Column("created_at", sa.DateTime(timezone=True)),
    sa.Column("updated_at", sa.DateTime(timezone=True)),
)


class ConversationSummary(BaseModel):
    """Una fila de la lista de conversaciones (UI.md, marco común)."""

    thread_id: str
    username: str
    project_key: str
    mode: Literal["functional", "qa"]
    origin_kind: Literal["epic", "story", "need"]
    origin_key: str | None = None
    title: str
    status: ConversationStatus
    artifact_id: str | None = None
    version: int | None = None
    created_at: datetime
    updated_at: datetime


def conversation_title(mode: str, origin_kind: str, origin_key: str | None, project: str) -> str:
    """«Evolucionar DEMO-3», «Nueva necesidad · DEMO»…: solo flujo y clave, sin texto libre."""
    flow = _FLOW_TITLES.get((mode, origin_kind), "Conversación")
    return f"{flow} {origin_key}" if origin_key else f"{flow} · {project}"


class ConversationStore(Protocol):
    def start(self, summary: ConversationSummary) -> None: ...
    def update(
        self,
        thread_id: str,
        *,
        status: ConversationStatus,
        artifact_id: str | None = None,
        version: int | None = None,
        username: str | None = None,
    ) -> None: ...
    def get(self, thread_id: str) -> ConversationSummary | None: ...
    def list_for(self, username: str, limit: int = 50) -> list[ConversationSummary]: ...


NOT_YOURS = "No existe esa conversación o no es tuya."
THREAD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def new_conversation_config(username: str) -> dict[str, object]:
    """Config de una conversación nueva: `thread_id` generado aquí, nunca por la UI ni la URL.

    `user` es la persona autenticada que actúa; el grafo exige que sea la dueña del hilo.
    """
    return {"configurable": {"thread_id": str(uuid4()), "user": username}}


def resume_config(store: ConversationStore, username: str, thread_id: str) -> dict[str, object]:
    """Config de LangGraph para retomar una conversación propia; nadie retoma la de otro."""
    found = store.get(thread_id) if THREAD_ID.fullmatch(thread_id or "") else None
    if found is None or found.username != username:
        # Mismo mensaje en los dos casos: no revela si el hilo existe.
        raise NotFoundError(NOT_YOURS, service="conversaciones")
    return {"configurable": {"thread_id": found.thread_id, "user": username}}


def new_summary(
    *,
    thread_id: str,
    username: str,
    project: str,
    mode: str,
    origin_kind: str,
    origin_key: str | None,
) -> ConversationSummary:
    now = datetime.now(UTC)
    return ConversationSummary(
        thread_id=thread_id,
        username=username,
        project_key=project,
        mode=mode,  # type: ignore[arg-type]
        origin_kind=origin_kind,  # type: ignore[arg-type]
        origin_key=origin_key,
        title=conversation_title(mode, origin_kind, origin_key, project),
        status="started",
        created_at=now,
        updated_at=now,
    )


class InMemoryConversationStore:
    def __init__(self) -> None:
        self.rows: dict[str, ConversationSummary] = {}

    def start(self, summary: ConversationSummary) -> None:
        # Si `load_origin` se repite (fallo antes del checkpoint), la fila se conserva.
        self.rows.setdefault(summary.thread_id, summary)

    def update(
        self,
        thread_id: str,
        *,
        status: ConversationStatus,
        artifact_id: str | None = None,
        version: int | None = None,
        username: str | None = None,
    ) -> None:
        row = self.rows.get(thread_id)
        if row is None or (username is not None and row.username != username):
            return
        changes: dict[str, object] = {"status": status, "updated_at": datetime.now(UTC)}
        if artifact_id is not None:
            changes["artifact_id"] = artifact_id
        if version is not None:
            changes["version"] = version
        self.rows[thread_id] = row.model_copy(update=changes)

    def get(self, thread_id: str) -> ConversationSummary | None:
        return self.rows.get(thread_id)

    def list_for(self, username: str, limit: int = 50) -> list[ConversationSummary]:
        mine = [r for r in self.rows.values() if r.username == username]
        return sorted(mine, key=lambda r: r.updated_at, reverse=True)[:limit]


class SqlConversationStore:
    """Tabla `conversations` (migración `0004`)."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlConversationStore":
        return cls(sa.create_engine(url, pool_pre_ping=True))

    def start(self, summary: ConversationSummary) -> None:
        row = summary.model_dump()
        row["artifact_id"] = None
        insert = postgresql.insert(CONVERSATIONS).values(**row)
        self._run(
            insert.on_conflict_do_nothing(index_elements=[CONVERSATIONS.c.thread_id]),
            "guardar",
        )

    def update(
        self,
        thread_id: str,
        *,
        status: ConversationStatus,
        artifact_id: str | None = None,
        version: int | None = None,
        username: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status, "updated_at": datetime.now(UTC)}
        if artifact_id is not None:
            values["artifact_id"] = artifact_id
        if version is not None:
            values["version"] = version
        query = sa.update(CONVERSATIONS).where(CONVERSATIONS.c.thread_id == thread_id)
        if username is not None:
            query = query.where(CONVERSATIONS.c.username == username)
        query = query.values(**values)
        self._run(query, "actualizar")

    def get(self, thread_id: str) -> ConversationSummary | None:
        query = sa.select(CONVERSATIONS).where(CONVERSATIONS.c.thread_id == thread_id)
        rows = self._fetch(query)
        return rows[0] if rows else None

    def list_for(self, username: str, limit: int = 50) -> list[ConversationSummary]:
        query = (
            sa.select(CONVERSATIONS)
            .where(CONVERSATIONS.c.username == username)
            .order_by(CONVERSATIONS.c.updated_at.desc())
            .limit(limit)
        )
        return self._fetch(query)

    def _run(self, statement: sa.Executable, verb: str) -> None:
        try:
            with self._engine.begin() as conn:
                conn.execute(statement)
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                f"No se pudo {verb} la conversación.", service=SERVICE
            ) from None

    def _fetch(self, query: sa.Select) -> list[ConversationSummary]:
        try:
            with self._engine.begin() as conn:
                rows = conn.execute(query).mappings().all()
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudieron leer las conversaciones.", service=SERVICE
            ) from None
        return [
            ConversationSummary.model_validate(
                {**row, "artifact_id": str(row["artifact_id"]) if row["artifact_id"] else None}
            )
            for row in rows
        ]
