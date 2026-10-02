"""Flujo unido HU → QA: entregas de HU aprobadas a QA (T-54, D-01).

El analista funcional no genera pruebas: «Pasar a QA» (`hand_off`) deja su HU aprobada o
publicada en la lista de QA, y una persona con rol QA la recoge (`take_handoff`) y empieza una
conversación de QA con esa HU, sin releer Jira ni volver a estructurarla con el LLM.

La HU sale **siempre del servidor**: del estado del grafo en el checkpointer, contrastado con la
fila de la conversación y con el registro de aprobaciones. Nunca de un contenido que envíe la UI
o la API. Se copia en la entrega (`Handoff.story`) y el grafo de QA la carga de aquí por su id.

Funciones para la API (PA-105): `hand_off`, `list_handoffs` y `take_handoff`.
"""

import re
import secrets
import threading
from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from sqlalchemy.dialects import postgresql

from adapters.base import User
from adapters.errors import AgentError, ExternalServiceError
from core.approvals import PublishTarget
from core.container import Container
from core.conversations import new_conversation_config, resume_config
from core.logging import get_logger
from core.permissions import Permission, require
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from schemas.user_story import UserStory

if TYPE_CHECKING:  # el grafo importa este módulo: sin ciclos al cargar
    from core.graph.state import AgentState

log = get_logger("core.handoff")

SERVICE = "postgres"
HANDOFF_ID = re.compile(r"^[0-9a-f]{32}$")
# Estados de la conversación funcional desde los que se puede pasar a QA (requisito 10).
HANDOFF_FROM_STATUSES = frozenset({"approved", "simulated", "published"})
MAX_TITLE = 120
DEFAULT_LIMIT = 50
NOT_AVAILABLE = "Esa HU ya no está disponible para QA: puede que la haya recogido otra persona."

HandoffStatus = Literal["pending", "taken"]


class HandoffError(AgentError):
    """No se puede pasar la HU a QA o recogerla; mensaje en español para la UI."""


class Handoff(BaseModel):
    """Una HU aprobada o publicada lista para preparar sus pruebas."""

    id: str
    artifact_id: UUID
    version: int
    project_key: str
    story_key: str | None  # solo si esa versión está publicada en Jira
    title: str
    story: UserStory
    from_user: str
    from_thread_id: str
    created_at: datetime
    status: HandoffStatus = "pending"
    taken_by: str | None = None
    taken_at: datetime | None = None
    qa_thread_id: str | None = None

    @property
    def published(self) -> bool:
        """Esa versión está publicada en Jira: sus casos se pueden publicar."""
        return self.story_key is not None


class HandoffStore(Protocol):
    def create(self, handoff: Handoff) -> Handoff:
        """Guarda la entrega; idempotente por versión y publicación.

        Si esa versión ya se entregó igual (sin publicar o publicada), devuelve la existente. Si
        ahora está publicada y había una entrega sin clave pendiente, esa entrega recibe la clave
        y la HU publicada; si ya estaba recogida, se crea otra con clave.
        """
        ...

    def get(self, handoff_id: str) -> Handoff | None: ...

    def list_pending(
        self, projects: Collection[str] | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Handoff]: ...

    def take(
        self, handoff_id: str, username: str, qa_thread_id: str, at: datetime
    ) -> Handoff | None:
        """Marca la entrega como recogida si sigue pendiente (una sola vez); si no, None."""
        ...

    def release(self, handoff_id: str, username: str, qa_thread_id: str) -> bool:
        """Vuelve a pendiente la entrega recogida por `username` para ese hilo (PA-113).

        Solo si coinciden quien la recogió y la conversación: nadie libera la de otra persona.
        """
        ...


class StateReader(Protocol):
    """Lo que `hand_off` necesita del grafo compilado: leer el estado de un hilo."""

    def get_state(self, config: Any) -> Any: ...


@dataclass(frozen=True)
class QaStart:
    """Conversación de QA lista para invocar el grafo: `graph.invoke(state, config)`."""

    config: dict[str, object]
    state: "AgentState"
    handoff: Handoff


# --- Servicio ------------------------------------------------------------------------------------


def hand_off(
    container: Container, graph: StateReader, store: HandoffStore, user: User, thread_id: str
) -> Handoff:
    """«Pasar a QA»: la HU aprobada o publicada de una conversación propia (requisito 10)."""
    require(user, Permission.GENERATE_STORY)
    config = resume_config(container.conversations, user.username, thread_id)
    summary = container.conversations.get(thread_id)
    if (
        summary is None
        or summary.mode != "functional"
        or summary.status not in HANDOFF_FROM_STATUSES
    ):
        raise HandoffError("Solo se pasa a QA una HU aprobada o publicada.")
    values = graph.get_state(config).values or {}
    artifact = values.get("artifact")
    origin = values.get("origin") or {}
    if (
        not isinstance(artifact, Artifact)
        or artifact.type is not ArtifactType.USER_STORY
        or not isinstance(artifact.content, UserStory)
        or str(artifact.id) != summary.artifact_id
        or artifact.version != summary.version
    ):
        raise HandoffError("La HU de esta conversación no coincide con la versión aprobada.")
    published = _confirmed_by_ledger(container, artifact, origin, user.username, thread_id)
    story = artifact.content
    handoff = Handoff(
        id=secrets.token_hex(16),
        artifact_id=artifact.id,
        version=artifact.version,
        project_key=summary.project_key,
        # En simulación esta versión no está en Jira, aunque la HU de partida tenga clave.
        story_key=story.jira_key if published else None,
        title=" ".join(story.title.split())[:MAX_TITLE],
        story=story,
        from_user=user.username,
        from_thread_id=thread_id,
        created_at=datetime.now(UTC),
    )
    saved = store.create(handoff)
    log.info(
        "HU pasada a QA",
        user=user.username,
        action="handoff",
        artifact_id=str(artifact.id),
        version=artifact.version,
        handoff_id=saved.id,
    )
    return saved


def list_handoffs(
    store: HandoffStore,
    user: User,
    projects: Collection[str] | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[Handoff]:
    """HU pendientes de preparar pruebas, para cualquier persona con rol QA (D-01)."""
    require(user, Permission.GENERATE_TESTS)
    return store.list_pending(projects, max(1, min(limit, DEFAULT_LIMIT)))


def take_handoff(store: HandoffStore, user: User, handoff_id: str) -> QaStart:
    """Recoge la entrega (una sola persona) y prepara su conversación de QA."""
    require(user, Permission.GENERATE_TESTS)
    if not HANDOFF_ID.fullmatch(handoff_id or ""):
        raise HandoffError(NOT_AVAILABLE)
    config = new_conversation_config(user.username)
    thread_id = str(config["configurable"]["thread_id"])  # type: ignore[index]
    taken = store.take(handoff_id, user.username, thread_id, datetime.now(UTC))
    if taken is None:
        raise HandoffError(NOT_AVAILABLE)
    from core.graph.state import Origin, initial_state

    origin = Origin(kind="story", project=taken.project_key)
    if taken.story_key:
        origin["key"] = taken.story_key
    state = initial_state(user.username, "qa", origin, handoff_id=taken.id)
    log.info(
        "HU recogida por QA",
        user=user.username,
        action="take_handoff",
        artifact_id=str(taken.artifact_id),
        handoff_id=taken.id,
    )
    return QaStart(config=config, state=state, handoff=taken)


def release_failed_take(
    store: HandoffStore, handoff_id: str, username: str, qa_thread_id: str
) -> bool:
    """PA-113: si la conversación de QA falla antes de su primera versión, la HU vuelve a la
    lista de QA (la puede recoger cualquiera) y ese hilo ya no puede usar la entrega."""
    released = store.release(handoff_id, username, qa_thread_id)
    if released:
        log.info(
            "entrega devuelta a QA tras un fallo",
            user=username,
            action="release_handoff",
            handoff_id=handoff_id,
        )
    return released


def load_taken_handoff(
    store: HandoffStore | None, handoff_id: str, user: str, thread_id: str
) -> Handoff:
    """La entrega recogida por `user` para este hilo; el grafo de QA no se fía del estado."""
    valid = store is not None and HANDOFF_ID.fullmatch(handoff_id or "")
    found = store.get(handoff_id) if store is not None and valid else None
    if (
        found is None
        or found.status != "taken"
        or found.taken_by != user
        or found.qa_thread_id != thread_id
    ):
        raise HandoffError(NOT_AVAILABLE)
    return found


def _confirmed_by_ledger(
    container: Container, artifact: Artifact, origin: dict[str, Any], user: str, thread_id: str
) -> bool:
    """True si esa versión está publicada; False si solo aprobada. Si no consta, error."""
    if artifact.status is ArtifactStatus.PUBLISHED and container.approvals.was_published(artifact):
        return True
    target = PublishTarget(
        mode="functional",
        origin_kind=str(origin.get("kind") or ""),
        origin_key=origin.get("key"),
        project_key=str(origin.get("project") or ""),
        user=user,
        thread_id=thread_id,
    )
    if (
        artifact.status is ArtifactStatus.APPROVED
        and container.approvals.find(artifact, target) is not None
    ):
        return False
    raise HandoffError("No consta la aprobación de esta versión de la HU.")


# --- Almacenes -----------------------------------------------------------------------------------


class InMemoryHandoffStore:
    def __init__(self) -> None:
        self.rows: dict[str, Handoff] = {}
        self._lock = threading.Lock()  # la recogida es de una sola persona también en memoria

    def create(self, handoff: Handoff) -> Handoff:
        same = [
            row
            for row in self.rows.values()
            if row.artifact_id == handoff.artifact_id and row.version == handoff.version
        ]
        if existing := next((r for r in same if r.published == handoff.published), None):
            return existing
        if handoff.published and (
            pending := next((r for r in same if r.status == "pending"), None)
        ):
            upgraded = pending.model_copy(
                update={"story_key": handoff.story_key, "story": handoff.story}
            )
            self.rows[pending.id] = upgraded
            return upgraded
        self.rows[handoff.id] = handoff
        return handoff

    def get(self, handoff_id: str) -> Handoff | None:
        return self.rows.get(handoff_id)

    def list_pending(
        self, projects: Collection[str] | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Handoff]:
        pending = [
            row
            for row in self.rows.values()
            if row.status == "pending" and (projects is None or row.project_key in projects)
        ]
        return sorted(pending, key=lambda row: row.created_at, reverse=True)[:limit]

    def take(
        self, handoff_id: str, username: str, qa_thread_id: str, at: datetime
    ) -> Handoff | None:
        with self._lock:
            row = self.rows.get(handoff_id)
            if row is None or row.status != "pending":
                return None
            taken = row.model_copy(
                update={
                    "status": "taken",
                    "taken_by": username,
                    "taken_at": at,
                    "qa_thread_id": qa_thread_id,
                }
            )
            self.rows[handoff_id] = taken
            return taken

    def release(self, handoff_id: str, username: str, qa_thread_id: str) -> bool:
        with self._lock:
            row = self.rows.get(handoff_id)
            if (
                row is None
                or row.status != "taken"
                or row.taken_by != username
                or row.qa_thread_id != qa_thread_id
            ):
                return False
            self.rows[handoff_id] = row.model_copy(
                update={
                    "status": "pending",
                    "taken_by": None,
                    "taken_at": None,
                    "qa_thread_id": None,
                }
            )
            return True


_METADATA = sa.MetaData()
QA_HANDOFFS = sa.Table(
    "qa_handoffs",
    _METADATA,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("artifact_id", sa.Uuid, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("project_key", sa.String, nullable=False),
    sa.Column("story_key", sa.String),
    sa.Column("published", sa.Boolean, nullable=False),
    sa.Column("title", sa.String, nullable=False),
    sa.Column("story", postgresql.JSONB, nullable=False),
    sa.Column("from_user", sa.String, nullable=False),
    sa.Column("from_thread_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.String, nullable=False),
    sa.Column("taken_by", sa.String),
    sa.Column("taken_at", sa.DateTime(timezone=True)),
    sa.Column("qa_thread_id", sa.String(64)),
)


class SqlHandoffStore:
    """`qa_handoffs` (migración `0005`) con SQLAlchemy Core."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlHandoffStore":
        return cls(sa.create_engine(url, pool_pre_ping=True, hide_parameters=True))

    def create(self, handoff: Handoff) -> Handoff:
        values = handoff.model_dump(mode="json", exclude={"published"})
        values |= {
            "artifact_id": handoff.artifact_id,
            "created_at": handoff.created_at,
            "published": handoff.published,
        }
        same_version = (
            QA_HANDOFFS.c.artifact_id == handoff.artifact_id,
            QA_HANDOFFS.c.version == handoff.version,
        )
        statements: list[Any] = []
        if handoff.published:
            # La entrega sin clave que nadie ha recogido pasa a llevar la HU publicada (si no
            # existe ya una entrega publicada de esa versión).
            other = QA_HANDOFFS.alias("published_handoff")
            already_published = sa.exists().where(
                other.c.artifact_id == handoff.artifact_id,
                other.c.version == handoff.version,
                other.c.published.is_(True),
            )
            statements.append(
                sa.update(QA_HANDOFFS)
                .where(
                    *same_version,
                    QA_HANDOFFS.c.published.is_(False),
                    QA_HANDOFFS.c.status == "pending",
                    ~already_published,
                )
                .values(
                    published=True,
                    story_key=handoff.story_key,
                    story=values["story"],
                )
            )
        statements += [
            postgresql.insert(QA_HANDOFFS)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_qa_handoffs_artifact_version"),
            sa.select(QA_HANDOFFS).where(
                *same_version, QA_HANDOFFS.c.published.is_(handoff.published)
            ),
        ]
        rows = self._rows(statements, "guardar la entrega a QA")
        return _from_row(rows[0])

    def get(self, handoff_id: str) -> Handoff | None:
        query = sa.select(QA_HANDOFFS).where(QA_HANDOFFS.c.id == handoff_id)
        rows = self._rows([query], "leer la entrega a QA")
        return _from_row(rows[0]) if rows else None

    def list_pending(
        self, projects: Collection[str] | None = None, limit: int = DEFAULT_LIMIT
    ) -> list[Handoff]:
        query = (
            sa.select(QA_HANDOFFS)
            .where(QA_HANDOFFS.c.status == "pending")
            .order_by(QA_HANDOFFS.c.created_at.desc())
            .limit(limit)
        )
        if projects is not None:
            query = query.where(QA_HANDOFFS.c.project_key.in_(list(projects)))
        return [_from_row(row) for row in self._rows([query], "listar las entregas a QA")]

    def take(
        self, handoff_id: str, username: str, qa_thread_id: str, at: datetime
    ) -> Handoff | None:
        # Una sola sentencia condicionada: dos personas a la vez no pueden recoger la misma HU.
        update = (
            sa.update(QA_HANDOFFS)
            .where(QA_HANDOFFS.c.id == handoff_id, QA_HANDOFFS.c.status == "pending")
            .values(status="taken", taken_by=username, taken_at=at, qa_thread_id=qa_thread_id)
            .returning(*QA_HANDOFFS.c)
        )
        rows = self._rows([update], "recoger la entrega a QA")
        return _from_row(rows[0]) if rows else None

    def release(self, handoff_id: str, username: str, qa_thread_id: str) -> bool:
        update = (
            sa.update(QA_HANDOFFS)
            .where(
                QA_HANDOFFS.c.id == handoff_id,
                QA_HANDOFFS.c.status == "taken",
                QA_HANDOFFS.c.taken_by == username,
                QA_HANDOFFS.c.qa_thread_id == qa_thread_id,
            )
            .values(status="pending", taken_by=None, taken_at=None, qa_thread_id=None)
            .returning(QA_HANDOFFS.c.id)
        )
        return bool(self._rows([update], "devolver la entrega a QA"))

    def _rows(self, statements: list[Any], verb: str) -> list[Any]:
        """Ejecuta en una transacción; devuelve las filas de la última sentencia."""
        try:
            with self._engine.begin() as conn:
                for statement in statements:
                    result = conn.execute(statement)
                return list(result.mappings().all()) if result.returns_rows else []
        except sa.exc.SQLAlchemyError:
            raise ExternalServiceError(f"No se pudo {verb}.", service=SERVICE) from None


def _from_row(row: Any) -> Handoff:
    data = dict(row)
    data.pop("published", None)  # se deduce de la clave
    try:
        data["artifact_id"] = UUID(str(data["artifact_id"]))
        return Handoff.model_validate(data)
    except (ValueError, ValidationError):
        # Fila dañada: falla cerrado sin mostrar su contenido.
        raise ExternalServiceError(
            "La entrega a QA guardada no es válida.", service=SERVICE
        ) from None
