"""Registro de aprobaciones humanas, fuera del estado del grafo (principio de aprobación).

El estado del checkpointer puede modificarse con `update_state` o al reanudar, así que no basta
con que el artefacto diga `APPROVED`. El ciclo es:

1. `generate` ofrece una versión (`offer`) con su operación de publicación (`PublishTarget`,
   con el proyecto de Jira desde T-50). La operación queda fijada en la primera oferta y no
   cambia entre iteraciones.
2. `human_review` muestra versión y operación; la persona aprueba la huella de ambas
   (`review_fingerprint`) y se registra la aprobación (`record`).
3. `publish` exige una aprobación vigente para esa versión y esa operación, toma la operación
   del registro (nunca del estado) y la consume al publicar (un solo uso).
4. `memorize` solo actúa sobre lo que `publish` registró como publicado.

Desde T-25 persiste por artefacto en `artifact_state` (y cada acción se audita en `audit_log`).
"""

import functools
import hashlib
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from core.artifact_state import ArtifactStateStore
from schemas.artifact import Artifact

_FINGERPRINT_FIELDS = {"id", "version", "type", "origin_key", "content", "impact"}
_MISMATCH = "La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto."
_DAMAGED = "El registro de aprobaciones de este artefacto está dañado; revísalo antes de continuar."
_NOT_CURRENT = "Esta aprobación ya no está vigente; vuelve a revisar el artefacto."
_BUSY = (
    "Otro proceso está cambiando el registro de aprobaciones de este artefacto; "
    "vuelve a intentarlo."
)
MAX_LEDGER_RETRIES = 5


def _sha256(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def content_fingerprint(artifact: Artifact) -> str:
    """SHA-256 del artefacto revisado: identidad, versión, tipo, destino, contenido e impacto."""
    return _sha256(artifact.model_dump(mode="json", include=_FINGERPRINT_FIELDS))


class ApprovalError(ValueError):
    """La aprobación no corresponde a la versión u operación ofrecidas para revisión."""


@dataclass(frozen=True)
class PublishTarget:
    """Operación que se aprueba: `publish` la toma de aquí, nunca del estado del grafo."""

    mode: str  # "functional" | "qa"
    origin_kind: str  # "epic" | "story" | "need"
    origin_key: str | None
    project_key: str  # T-50: lo aprobado es lo publicado, también el proyecto
    user: str
    thread_id: str

    def describe(self) -> dict[str, str | None]:
        """Operación en términos que la UI muestra a la persona antes de aprobar."""
        if self.mode == "qa":
            operation = "publicar casos de prueba"
        elif self.origin_kind == "story":
            operation = "actualizar HU"
        else:
            operation = "crear HU"
        return {
            "operation": operation,
            "project": self.project_key,
            "jira_key": self.origin_key if self.origin_kind == "story" else None,
            "epic_key": self.origin_key if self.origin_kind == "epic" else None,
        }


def review_fingerprint(artifact: Artifact, target: PublishTarget) -> str:
    """Huella que aprueba la persona: la versión exacta y la operación que se ejecutará."""
    return _sha256({"artifact": content_fingerprint(artifact), "target": asdict(target)})


@dataclass(frozen=True)
class Approval:
    artifact_id: str
    version: int
    fingerprint: str
    target: PublishTarget
    at: datetime
    consumed: bool = False
    published_fingerprint: str | None = None


def _locked[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Cada decisión del registro (releer, decidir y guardar) va entera bajo el cerrojo de la
    instancia: el `Container` comparte el registro entre hilos (revisión de seguridad)."""

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        ledger = args[0]
        with ledger._lock:  # type: ignore[attr-defined]
            return method(*args, **kwargs)

    return wrapper


class _LedgerConflictError(Exception):
    """Otro proceso escribió el registro entre la lectura y la escritura (PA-140)."""


def _retried[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """PA-140: si otro proceso cambió el registro mientras se decidía, se relee y se vuelve a
    decidir con los datos frescos (un segundo consumo falla entonces cerrado, PA-173). Tras
    `MAX_LEDGER_RETRIES` conflictos seguidos, `ApprovalError`: nunca se escribe a ciegas."""

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        for _ in range(MAX_LEDGER_RETRIES):
            try:
                return method(*args, **kwargs)
            except _LedgerConflictError:
                continue
        raise ApprovalError(_BUSY)

    return wrapper


@dataclass
class ApprovalLedger:
    """Registro de aprobaciones; con `store`, persistente por artefacto (T-25, PA-06).

    Con almacén, el estado del artefacto se relee antes de cada decisión (PA-174): otra
    instancia sobre el mismo `artifact_state` (otro proceso o pestaña) no ve vigente lo que ya
    se consumió ni borra al guardar lo que otra registró. Todo registro con forma inesperada
    falla cerrado (`ApprovalError`, PA-171/PA-172).
    """

    store: ArtifactStateStore | None = None
    _targets: dict[str, PublishTarget] = field(default_factory=dict)
    _offers: dict[str, str] = field(default_factory=dict)
    _approvals: dict[tuple[str, int], Approval] = field(default_factory=dict)
    # PA-140: revisión del registro leída del almacén (la escritura condicional la exige).
    _revisions: dict[str, int] = field(default_factory=dict, repr=False, compare=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)
    # PA-141: artefactos con una publicación en curso en este proceso.
    _publishing: set[str] = field(default_factory=set, repr=False, compare=False)
    # PA-141: aprobaciones con escrituras en Jira ya empezadas (artefacto, versión). `find`
    # no las devuelve aunque el consumo o su guardado fallen: nada se escribe dos veces.
    _spent: set[tuple[str, int]] = field(default_factory=set, repr=False, compare=False)

    @_retried
    @_locked
    def offer(self, artifact: Artifact, target: PublishTarget) -> str:
        """Registra la versión que se muestra; la operación no puede cambiar entre iteraciones."""
        artifact_id = str(artifact.id)
        self._ensure(artifact_id)
        fixed = self._targets.get(artifact_id)
        # PA-175: se valida antes de fijar; una oferta rechazada no deja el destino fijado.
        if (fixed is not None and fixed != target) or artifact.origin_key != target.origin_key:
            raise ApprovalError("El destino de publicación no puede cambiar entre iteraciones.")
        self._targets[artifact_id] = target
        self._offers[artifact_id] = content_fingerprint(artifact)
        # Solo vale la aprobación de la última versión: se descartan las pendientes anteriores.
        for key, approval in list(self._approvals.items()):
            if key[0] == artifact_id and key[1] != artifact.version and not approval.consumed:
                del self._approvals[key]
        self._persist(artifact_id)
        return review_fingerprint(artifact, target)

    @_locked
    def is_offered(self, artifact: Artifact, target: PublishTarget) -> bool:
        artifact_id = str(artifact.id)
        self._ensure(artifact_id)
        return self._targets.get(artifact_id) == target and self._offers.get(
            artifact_id
        ) == content_fingerprint(artifact)

    @_retried
    @_locked
    def record(self, artifact: Artifact, target: PublishTarget) -> Approval:
        """Aprueba la versión ofrecida; la oferta se consume y no se reaprueba lo publicado."""
        self._ensure(str(artifact.id))
        if not self.is_offered(artifact, target):
            raise ApprovalError(_MISMATCH)
        previous = self._approvals.get((str(artifact.id), artifact.version))
        if previous is not None and previous.consumed:
            raise ApprovalError("Esta versión ya se publicó; genera una versión nueva.")
        approval = Approval(
            artifact_id=str(artifact.id),
            version=artifact.version,
            fingerprint=content_fingerprint(artifact),
            target=target,
            at=datetime.now(UTC),
        )
        self._approvals[(approval.artifact_id, approval.version)] = approval
        del self._offers[approval.artifact_id]
        self._persist(approval.artifact_id)
        return approval

    @_locked
    def find(self, artifact: Artifact, target: PublishTarget) -> Approval | None:
        """Aprobación vigente (no consumida) de esta versión exacta y esta misma operación."""
        self._ensure(str(artifact.id))
        approval = self._approvals.get((str(artifact.id), artifact.version))
        if (
            approval is None
            or approval.consumed
            or (approval.artifact_id, approval.version) in self._spent
            or approval.fingerprint != content_fingerprint(artifact)
            or approval.target != target
        ):
            return None
        return approval

    @_retried
    @_locked
    def consume(self, approval: Approval, published: Artifact) -> None:
        """Marca la aprobación como usada y guarda la huella de lo publicado.

        PA-173: solo se consume la aprobación vigente guardada (la misma, sin consumir); un
        segundo consumo o una aprobación descartada por una oferta posterior fallan cerrado.
        """
        key = (approval.artifact_id, approval.version)
        self._ensure(approval.artifact_id)
        current = self._approvals.get(key)
        if current is None or current.consumed or current != approval:
            raise ApprovalError(_NOT_CURRENT)
        self._approvals[key] = replace(
            approval, consumed=True, published_fingerprint=content_fingerprint(published)
        )
        self._persist(approval.artifact_id)

    @_locked
    def spend(self, approval: Approval) -> None:
        """Marca la aprobación como usada en este proceso antes de escribir en Jira (PA-141)."""
        self._spent.add((approval.artifact_id, approval.version))

    @_locked
    def unspend(self, approval: Approval) -> None:
        """Publicación parcial sin consumo: la aprobación vuelve a servir para reintentar los
        fallidos (la publicación de la suite es idempotente, PA-05)."""
        self._spent.discard((approval.artifact_id, approval.version))

    @contextmanager
    def publishing(self, artifact: Artifact, target: PublishTarget) -> Iterator[Approval | None]:
        """Una sola publicación a la vez por artefacto (PA-141).

        Dentro, la aprobación vigente se relee (`find`); si ya hay otra publicación en curso del
        mismo artefacto, `ApprovalError` antes de escribir nada. Entre procesos: PA-140.
        """
        artifact_id = str(artifact.id)
        with self._lock:
            if artifact_id in self._publishing:
                raise ApprovalError(
                    "Ya hay una publicación en curso de este artefacto; espera a que termine."
                )
            self._publishing.add(artifact_id)
        try:
            yield self.find(artifact, target)
        finally:
            with self._lock:
                self._publishing.discard(artifact_id)

    @_locked
    def was_published(self, artifact: Artifact) -> bool:
        self._ensure(str(artifact.id))
        approval = self._approvals.get((str(artifact.id), artifact.version))
        return bool(
            approval
            and approval.consumed
            and approval.published_fingerprint == content_fingerprint(artifact)
        )

    # --- persistencia -------------------------------------------------------------------------

    def _ensure(self, artifact_id: str) -> None:
        """Relee del almacén el estado del artefacto antes de cada decisión (PA-174).

        Sin almacén (pruebas), el registro vive solo en memoria. Con almacén, la caché del
        artefacto se sustituye por lo guardado; un registro con forma inesperada falla cerrado
        sin tocar lo guardado.
        """
        if self.store is None:
            return
        state = self.store.load(artifact_id)
        target, offer, approvals = _parse_ledger(artifact_id, state)
        self._revisions[artifact_id] = _stored_revision(state)
        self._targets.pop(artifact_id, None)
        self._offers.pop(artifact_id, None)
        for key in [key for key in self._approvals if key[0] == artifact_id]:
            del self._approvals[key]
        if target is not None:
            self._targets[artifact_id] = target
        if offer is not None:
            self._offers[artifact_id] = offer
        for approval in approvals:
            self._approvals[(artifact_id, approval.version)] = approval

    def _persist(self, artifact_id: str) -> None:
        if self.store is None:
            return
        target = self._targets.get(artifact_id)
        expected = self._revisions.get(artifact_id, 0)
        ledger = {
            "revision": expected + 1,
            "target": asdict(target) if target else None,
            "offer": self._offers.get(artifact_id),
            "approvals": [
                _approval_to(a) for (aid, _v), a in self._approvals.items() if aid == artifact_id
            ],
        }
        replace_ledger = getattr(self.store, "replace_ledger", None)
        if replace_ledger is not None:
            # PA-140: escritura condicional; si otro proceso escribió antes, se relee y decide.
            if not replace_ledger(artifact_id, ledger, expected):
                raise _LedgerConflictError()
            self._revisions[artifact_id] = expected + 1
            return
        # Almacén sin escritura condicional (compatibilidad): lectura, cambio y escritura.
        state = self.store.load(artifact_id)
        if state is None:
            state = {}
        if not isinstance(state, dict):  # PA-171: no se sobrescribe un estado dañado
            raise ApprovalError(_DAMAGED)
        self.store.save(artifact_id, {**state, "ledger": ledger})


def _approval_to(approval: Approval) -> dict[str, Any]:
    data = asdict(approval)
    data["at"] = approval.at.isoformat()
    return data


def _stored_revision(state: object) -> int:
    """Revisión del registro guardado (0 si no hay); `ApprovalError` si no es un entero ≥ 0."""
    ledger = state.get("ledger") if isinstance(state, dict) else None
    if not isinstance(ledger, dict) or "revision" not in ledger:
        return 0
    revision = ledger["revision"]
    if type(revision) is not int or revision < 0:
        raise ApprovalError(_DAMAGED)
    return revision


def _parse_ledger(
    artifact_id: str, state: object
) -> tuple[PublishTarget | None, str | None, list[Approval]]:
    """Registro guardado → (destino, oferta, aprobaciones); `ApprovalError` si está dañado.

    Falla cerrado (PA-171, PA-172): sin el registro íntegro no se aprueba ni se publica nada.
    """
    if state is None:
        return None, None, []
    if not isinstance(state, dict):
        raise ApprovalError(_DAMAGED)
    if "ledger" not in state or state["ledger"] is None:
        return None, None, []
    ledger = state["ledger"]
    if not isinstance(ledger, dict):
        raise ApprovalError(_DAMAGED)
    try:
        raw_target = ledger.get("target")
        target = _target_from(raw_target) if raw_target is not None else None
        offer = ledger.get("offer")
        if offer is not None and not isinstance(offer, str):
            raise TypeError("oferta")
        raw_approvals = ledger.get("approvals", [])
        if not isinstance(raw_approvals, list):
            raise TypeError("aprobaciones")
        approvals = [_approval_from(data) for data in raw_approvals]
    except (KeyError, TypeError, ValueError):
        raise ApprovalError(_DAMAGED) from None
    versions = [a.version for a in approvals]
    if len(versions) != len(set(versions)) or any(a.artifact_id != artifact_id for a in approvals):
        raise ApprovalError(_DAMAGED)  # PA-172: una versión duplicada o ajena no se elige
    return target, offer, approvals


_TARGET_FIELDS = ("mode", "origin_kind", "origin_key", "project_key", "user", "thread_id")


def _target_from(raw: object) -> PublishTarget:
    """Destino guardado; un objeto vacío, con campos de más o de otro tipo es un registro dañado."""
    if not isinstance(raw, dict) or set(raw) != set(_TARGET_FIELDS):
        raise TypeError("destino")
    for name in _TARGET_FIELDS:
        value = raw[name]
        if not (isinstance(value, str) or (name == "origin_key" and value is None)):
            raise TypeError(name)
    return PublishTarget(**raw)


def _approval_from(data: dict[str, Any]) -> Approval:
    if not isinstance(data, dict):
        raise TypeError("aprobación")
    version = data["version"]
    if type(version) is not int:  # ni `True`, ni `1.9`, ni `"1"`
        raise TypeError("version")
    consumed = data["consumed"]  # PA-172: obligatorio; si falta, el registro está dañado
    if not isinstance(consumed, bool):
        raise TypeError("consumed")
    published = data.get("published_fingerprint")
    if published is not None and not isinstance(published, str):
        raise TypeError("published_fingerprint")
    return Approval(
        artifact_id=str(data["artifact_id"]),
        version=version,
        fingerprint=str(data["fingerprint"]),
        target=_target_from(data["target"]),
        at=datetime.fromisoformat(data["at"]),
        consumed=consumed,
        published_fingerprint=published,
    )
