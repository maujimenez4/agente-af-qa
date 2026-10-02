"""Máquina de estados de los artefactos (RF-34, CA-00-07).

draft → in_review → approved → published · in_review → draft (iterar) ·
draft | in_review → discarded. Cualquier otra transición lanza `InvalidTransitionError`.
"""

from adapters.errors import InvalidTransitionError
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus

S = ArtifactStatus

TRANSITIONS: dict[ArtifactStatus, frozenset[ArtifactStatus]] = {
    S.DRAFT: frozenset({S.IN_REVIEW, S.DISCARDED}),
    S.IN_REVIEW: frozenset({S.APPROVED, S.DRAFT, S.DISCARDED}),
    S.APPROVED: frozenset({S.PUBLISHED}),
    S.PUBLISHED: frozenset(),
    S.DISCARDED: frozenset(),
}

__all__ = [
    "TRANSITIONS",
    "InvalidTransitionError",
    "can_transition",
    "ensure_transition",
    "transition",
]


def _status(value: object) -> ArtifactStatus | None:
    """`ArtifactStatus` de un valor (también su cadena); None si no es un estado válido."""
    try:
        return ArtifactStatus(value)
    except (ValueError, TypeError):
        return None


def can_transition(current: ArtifactStatus, target: ArtifactStatus) -> bool:
    origin, destination = _status(current), _status(target)
    return origin is not None and destination is not None and destination in TRANSITIONS[origin]


def ensure_transition(current: ArtifactStatus, target: ArtifactStatus) -> ArtifactStatus:
    """Devuelve el destino como `ArtifactStatus`; `InvalidTransitionError` si no se permite.

    PA-176: un estado de tipo o valor inesperado también es una transición no permitida.
    """
    if not can_transition(current, target):
        raise InvalidTransitionError(_label(current), _label(target))
    return ArtifactStatus(target)


def transition(artifact: Artifact, target: ArtifactStatus) -> Artifact:
    """Devuelve una copia del artefacto en el estado `target`; no modifica el original."""
    status = ensure_transition(artifact.status, target)
    return artifact.model_copy(update={"status": status})


def _label(value: object) -> str:
    status = _status(value)
    return status.value if status is not None else str(value)[:40]
