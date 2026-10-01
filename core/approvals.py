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

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from core.artifact_state import ArtifactStateStore
from schemas.artifact import Artifact

_FINGERPRINT_FIELDS = {"id", "version", "type", "origin_key", "content", "impact"}
_MISMATCH = "La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto."


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


@dataclass
class ApprovalLedger:
    """Registro de aprobaciones; con `store`, persistente por artefacto (T-25, PA-06)."""

    store: ArtifactStateStore | None = None
    _targets: dict[str, PublishTarget] = field(default_factory=dict)
    _offers: dict[str, str] = field(default_factory=dict)
    _approvals: dict[tuple[str, int], Approval] = field(default_factory=dict)
    _loaded: set[str] = field(default_factory=set)

    def offer(self, artifact: Artifact, target: PublishTarget) -> str:
        """Registra la versión que se muestra; la operación no puede cambiar entre iteraciones."""
        artifact_id = str(artifact.id)
        self._ensure(artifact_id)
        fixed = self._targets.setdefault(artifact_id, target)
        if fixed != target or artifact.origin_key != target.origin_key:
            raise ApprovalError("El destino de publicación no puede cambiar entre iteraciones.")
        self._offers[artifact_id] = content_fingerprint(artifact)
        # Solo vale la aprobación de la última versión: se descartan las pendientes anteriores.
        for key, approval in list(self._approvals.items()):
            if key[0] == artifact_id and key[1] != artifact.version and not approval.consumed:
                del self._approvals[key]
        self._persist(artifact_id)
        return review_fingerprint(artifact, target)

    def is_offered(self, artifact: Artifact, target: PublishTarget) -> bool:
        artifact_id = str(artifact.id)
        self._ensure(artifact_id)
        return self._targets.get(artifact_id) == target and self._offers.get(
            artifact_id
        ) == content_fingerprint(artifact)

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

    def find(self, artifact: Artifact, target: PublishTarget) -> Approval | None:
        """Aprobación vigente (no consumida) de esta versión exacta y esta misma operación."""
        self._ensure(str(artifact.id))
        approval = self._approvals.get((str(artifact.id), artifact.version))
        if (
            approval is None
            or approval.consumed
            or approval.fingerprint != content_fingerprint(artifact)
            or approval.target != target
        ):
            return None
        return approval

    def consume(self, approval: Approval, published: Artifact) -> None:
        """Marca la aprobación como usada y guarda la huella de lo publicado."""
        key = (approval.artifact_id, approval.version)
        self._approvals[key] = replace(
            approval, consumed=True, published_fingerprint=content_fingerprint(published)
        )
        self._persist(approval.artifact_id)

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
        """Carga del almacén el estado del artefacto la primera vez que se usa en este proceso."""
        if self.store is None or artifact_id in self._loaded:
            return
        ledger = (self.store.load(artifact_id) or {}).get("ledger")
        if ledger:
            try:
                target = PublishTarget(**ledger["target"]) if ledger.get("target") else None
                approvals = [_approval_from(data) for data in ledger.get("approvals", [])]
            except (KeyError, TypeError, ValueError):
                # Falla cerrado: sin el registro íntegro no se aprueba ni se publica nada, y no
                # se sobrescribe el estado guardado.
                raise ApprovalError(
                    "El registro de aprobaciones de este artefacto está dañado; "
                    "revísalo antes de continuar."
                ) from None
            if target is not None:
                self._targets[artifact_id] = target
            if offer := ledger.get("offer"):
                self._offers[artifact_id] = str(offer)
            for approval in approvals:
                if approval.artifact_id == artifact_id:
                    self._approvals[(approval.artifact_id, approval.version)] = approval
        self._loaded.add(artifact_id)

    def _persist(self, artifact_id: str) -> None:
        if self.store is None:
            return
        target = self._targets.get(artifact_id)
        ledger = {
            "target": asdict(target) if target else None,
            "offer": self._offers.get(artifact_id),
            "approvals": [
                _approval_to(a) for (aid, _v), a in self._approvals.items() if aid == artifact_id
            ],
        }
        state = self.store.load(artifact_id) or {}
        state["ledger"] = ledger
        self.store.save(artifact_id, state)


def _approval_to(approval: Approval) -> dict[str, Any]:
    data = asdict(approval)
    data["at"] = approval.at.isoformat()
    return data


def _approval_from(data: dict[str, Any]) -> Approval:
    return Approval(
        artifact_id=data["artifact_id"],
        version=int(data["version"]),
        fingerprint=data["fingerprint"],
        target=PublishTarget(**data["target"]),
        at=datetime.fromisoformat(data["at"]),
        consumed=bool(data.get("consumed", False)),
        published_fingerprint=data.get("published_fingerprint"),
    )
