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


def can_transition(current: ArtifactStatus, target: ArtifactStatus) -> bool:
    return target in TRANSITIONS[current]


def ensure_transition(current: ArtifactStatus, target: ArtifactStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current.value, target.value)


def transition(artifact: Artifact, target: ArtifactStatus) -> Artifact:
    """Devuelve una copia del artefacto en el estado `target`; no modifica el original."""
    ensure_transition(artifact.status, target)
    return artifact.model_copy(update={"status": target})
