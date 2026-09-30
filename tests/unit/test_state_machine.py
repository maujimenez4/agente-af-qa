"""Pruebas de core/state_machine.py (T-05 · RF-34 · CA-00-07).

Datos sintéticos: HU de una biblioteca municipal ficticia con clave "DEMO-1".
"""

from itertools import product
from uuid import uuid4

import pytest

from adapters.errors import AgentError, InvalidTransitionError
from core.state_machine import TRANSITIONS, can_transition, ensure_transition, transition
from schemas import (
    AcceptanceCriterion,
    Artifact,
    ArtifactStatus,
    ArtifactType,
    Priority,
    UserStory,
)

S = ArtifactStatus

VALID = {
    (S.DRAFT, S.IN_REVIEW),
    (S.IN_REVIEW, S.APPROVED),
    (S.APPROVED, S.PUBLISHED),
    (S.IN_REVIEW, S.DRAFT),
    (S.DRAFT, S.DISCARDED),
    (S.IN_REVIEW, S.DISCARDED),
}
ALL_PAIRS = list(product(ArtifactStatus, repeat=2))
INVALID = [pair for pair in ALL_PAIRS if pair not in VALID]


def _pair_ids(pairs: list[tuple[ArtifactStatus, ArtifactStatus]]) -> list[str]:
    return [f"{src.value}->{dst.value}" for src, dst in pairs]


def make_artifact(status: ArtifactStatus = S.DRAFT) -> Artifact:
    story = UserStory(
        title="Reserva de salas en la Biblioteca Ficticia",
        role="socio",
        action="reservar una sala de estudio",
        benefit="asegurar un sitio para estudiar",
        description="Descripción ficticia.",
        business_goal="Mejorar el uso de las salas ficticias",
        scope_includes=[],
        scope_excludes=[],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="CA-1",
                title="Reserva correcta",
                given=["una sala libre"],
                when=["el socio la reserva"],
                then=["la sala queda reservada"],
            )
        ],
        business_rules=[],
        assumptions=[],
        constraints=[],
        dependencies=[],
        alternate_flows=[],
        exceptions=[],
        related_features=[],
        priority=Priority.COULD,
    )
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=status,
        version=1,
        origin_key="DEMO-1",
        content=story,
        created_by="usuario-ficticio",
    )


def test_pairs_cover_all_status_combinations_when_enumerated() -> None:
    """CA-00-07: 25 parejas = 6 válidas + 19 no válidas."""
    assert len(ALL_PAIRS) == 25
    assert len(VALID) == 6
    assert len(INVALID) == 19


def test_transitions_table_matches_spec_when_inspected() -> None:
    """CA-00-07: la tabla TRANSITIONS coincide exactamente con las transiciones de la SPEC."""
    table = {(src, dst) for src, targets in TRANSITIONS.items() for dst in targets}
    assert table == VALID
    assert set(TRANSITIONS) == set(ArtifactStatus)


@pytest.mark.parametrize(("current", "target"), sorted(VALID), ids=_pair_ids(sorted(VALID)))
def test_transition_succeeds_when_pair_valid(current: S, target: S) -> None:
    """CA-00-07: las transiciones válidas se permiten."""
    assert can_transition(current, target) is True
    ensure_transition(current, target)
    assert transition(make_artifact(current), target).status is target


@pytest.mark.parametrize(("current", "target"), INVALID, ids=_pair_ids(INVALID))
def test_transition_raises_when_pair_invalid(current: S, target: S) -> None:
    """CA-00-07: cualquier otra transición lanza InvalidTransitionError con mensaje en español."""
    assert can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError) as exc:
        ensure_transition(current, target)
    message = str(exc.value)
    assert message.startswith("No se puede pasar un artefacto de")
    assert f"'{current.value}'" in message
    assert f"'{target.value}'" in message
    assert exc.value.current == current.value
    assert exc.value.target == target.value


@pytest.mark.parametrize(("current", "target"), INVALID, ids=_pair_ids(INVALID))
def test_transition_does_not_mutate_when_pair_invalid(current: S, target: S) -> None:
    """CA-00-07: una transición rechazada no altera el artefacto."""
    artifact = make_artifact(current)
    with pytest.raises(InvalidTransitionError):
        transition(artifact, target)
    assert artifact.status is current


def test_invalid_transition_error_is_agent_error_when_raised() -> None:
    """CA-00-07: el error pertenece a la jerarquía del dominio."""
    with pytest.raises(AgentError):
        ensure_transition(S.PUBLISHED, S.DRAFT)


def test_transition_returns_copy_when_valid() -> None:
    """CA-00-07: transition() devuelve una copia sin mutar el original."""
    original = make_artifact(S.DRAFT)
    result = transition(original, S.IN_REVIEW)
    assert result is not original
    assert original.status is S.DRAFT
    assert result.status is S.IN_REVIEW
    assert result.id == original.id
    assert result.content == original.content
    assert result.model_dump(exclude={"status"}) == original.model_dump(exclude={"status"})


def test_transition_walks_happy_path_when_chained() -> None:
    """CA-00-07: draft → in_review → draft → in_review → approved → published."""
    artifact = make_artifact(S.DRAFT)
    for target in (S.IN_REVIEW, S.DRAFT, S.IN_REVIEW, S.APPROVED, S.PUBLISHED):
        artifact = transition(artifact, target)
    assert artifact.status is S.PUBLISHED


@pytest.mark.parametrize("final", [S.PUBLISHED, S.DISCARDED])
def test_final_status_has_no_exits_when_terminal(final: S) -> None:
    """CA-00-07: published y discarded son estados finales."""
    assert TRANSITIONS[final] == frozenset()
    for target in ArtifactStatus:
        assert can_transition(final, target) is False
        with pytest.raises(InvalidTransitionError):
            transition(make_artifact(final), target)


def test_approved_cannot_return_to_review_when_attempted() -> None:
    """CA-00-07 (negativa): un artefacto aprobado solo puede publicarse."""
    with pytest.raises(InvalidTransitionError, match="'approved' a 'in_review'"):
        transition(make_artifact(S.APPROVED), S.IN_REVIEW)


def test_draft_cannot_skip_review_when_publishing() -> None:
    """CA-00-07 (negativa): no se publica sin pasar por revisión y aprobación."""
    with pytest.raises(InvalidTransitionError):
        transition(make_artifact(S.DRAFT), S.PUBLISHED)
    with pytest.raises(InvalidTransitionError):
        transition(make_artifact(S.DRAFT), S.APPROVED)
