"""Estado de trabajo de cada artefacto que debe sobrevivir a un reinicio (T-25).

Guarda, por artefacto, el registro de aprobaciones (PA-06) y la versión de partida de Jira
(PA-37). Es persistencia del núcleo en su propia tabla `artifact_state` (anexo §11).

PA-140: el registro de aprobaciones (`state["ledger"]`) lleva su propia `revision` y se escribe
con `replace_ledger`, una escritura condicional que solo toca esa clave y falla si otro proceso
escribió antes. Además, `save` (la escritura completa que usan otros nodos para la versión de
partida o el registro de la ejecución) nunca devuelve el registro a una revisión anterior: un
cambio de otro proceso, como `consumed=True`, no se pierde.

PA-432: también guarda la versión estructurada compartida de una HU de Jira, por clave y huella
de su contenido (`structure_cache_id`), para que todas las conversaciones sobre la misma HU sin
cambios partan de la misma estructura.
"""

import json
import threading
from typing import Any, Protocol
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError

SERVICE = "postgres"
LEDGER_KEY = "ledger"
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

    def save(self, artifact_id: str, state: dict[str, Any]) -> None:
        """Guarda el estado completo; nunca retrocede la revisión del registro (PA-140)."""
        ...

    def replace_ledger(
        self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
    ) -> bool:
        """Sustituye solo `state["ledger"]` si su revisión guardada es `expected_revision`.

        Devuelve False si otro proceso lo cambió antes (hay que releer y volver a decidir).
        `ApprovalLedger` acepta aún almacenes sin este método (lectura y `save`), solo por
        compatibilidad con dobles de prueba antiguos: no son seguros entre procesos.
        """
        ...


# PA-432: espacio de nombres de las entradas compartidas de estructura (no son artefactos).
_STRUCTURE_NS = UUID("0b8c4f3e-6d2a-4e71-9a5c-7f1e2d3c4b5a")


def structure_cache_id(issue_key: str, fingerprint: str) -> str:
    """Identificador de la versión estructurada compartida de una HU de Jira (PA-432).

    Depende de la clave y de la huella de lo que se estructura: otra clave, otro proyecto u otro
    contenido dan otra entrada.
    """
    return str(uuid5(_STRUCTURE_NS, f"estructura:{issue_key}:{fingerprint}"))


def ledger_revision(state: object) -> int:
    """Revisión del registro guardado en `state`; 0 si no hay registro o no la lleva."""
    if not isinstance(state, dict):
        return 0
    ledger = state.get(LEDGER_KEY)
    revision = ledger.get("revision", 0) if isinstance(ledger, dict) else 0
    return revision if type(revision) is int and revision >= 0 else 0


class InMemoryArtifactStateStore:
    def __init__(self) -> None:
        self.states: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def load(self, artifact_id: str) -> dict[str, Any] | None:
        state = self.states.get(artifact_id)
        return dict(state) if state is not None else None

    def save(self, artifact_id: str, state: dict[str, Any]) -> None:
        with self._lock:
            stored = self.states.get(artifact_id)
            state = dict(state)
            if stored is not None and ledger_revision(stored) > ledger_revision(state):
                state[LEDGER_KEY] = stored[LEDGER_KEY]  # el registro nunca retrocede
            self.states[artifact_id] = state

    def replace_ledger(
        self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
    ) -> bool:
        with self._lock:
            stored = self.states.get(artifact_id) or {}
            if ledger_revision(stored) != expected_revision:
                return False
            self.states[artifact_id] = {**stored, LEDGER_KEY: dict(ledger)}
            return True


# Revisión del registro dentro del JSONB, en SQL (0 si falta o no es un número). Texto fijo:
# ningún dato de entrada se concatena en el SQL; todo va como parámetro.
# Escritura completa: si el registro guardado es más nuevo que el que llega, se conserva.
_SAVE = sa.text(
    "INSERT INTO artifact_state (artifact_id, state, updated_at) "
    "VALUES (:artifact_id, CAST(:state AS jsonb), now()) "
    "ON CONFLICT (artifact_id) DO UPDATE SET state = CASE WHEN "
    "(CASE WHEN jsonb_typeof(artifact_state.state->'ledger'->'revision') = 'number' "
    "THEN (artifact_state.state->'ledger'->>'revision')::numeric ELSE 0 END) > "
    "(CASE WHEN jsonb_typeof(EXCLUDED.state->'ledger'->'revision') = 'number' "
    "THEN (EXCLUDED.state->'ledger'->>'revision')::numeric ELSE 0 END) "
    "THEN EXCLUDED.state || jsonb_build_object('ledger', artifact_state.state->'ledger') "
    "ELSE EXCLUDED.state END, updated_at = now()"
)
_ENSURE_ROW = sa.text(
    "INSERT INTO artifact_state (artifact_id, state, updated_at) "
    "VALUES (:artifact_id, '{}'::jsonb, now()) ON CONFLICT (artifact_id) DO NOTHING"
)
# Escritura condicional del registro: solo la clave `ledger` y solo si nadie la cambió antes.
_REPLACE_LEDGER = sa.text(
    "UPDATE artifact_state SET "
    "state = jsonb_set(state, '{ledger}', CAST(:ledger AS jsonb), true), updated_at = now() "
    "WHERE artifact_id = :artifact_id AND "
    "(CASE WHEN jsonb_typeof(state->'ledger'->'revision') = 'number' "
    "THEN (state->'ledger'->>'revision')::numeric ELSE 0 END) = :expected"
)


class SqlArtifactStateStore:
    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, url: sa.URL) -> "SqlArtifactStateStore":
        return cls(sa.create_engine(url, pool_pre_ping=True, hide_parameters=True))

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
        params = {"artifact_id": UUID(artifact_id), "state": json.dumps(state)}
        try:
            with self._engine.begin() as conn:
                conn.execute(_SAVE, params)
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo guardar el estado del artefacto.", service=SERVICE
            ) from None

    def replace_ledger(
        self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
    ) -> bool:
        key = UUID(artifact_id)
        try:
            with self._engine.begin() as conn:
                conn.execute(_ENSURE_ROW, {"artifact_id": key})
                result = conn.execute(
                    _REPLACE_LEDGER,
                    {
                        "artifact_id": key,
                        "ledger": json.dumps(ledger),
                        "expected": expected_revision,
                    },
                )
                return result.rowcount == 1
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo guardar el registro de aprobaciones.", service=SERVICE
            ) from None
