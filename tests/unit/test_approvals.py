"""Pruebas del registro de aprobaciones humanas (core/approvals.py)."""

from dataclasses import replace
from uuid import uuid4

import pytest

from core.approvals import (
    ApprovalError,
    ApprovalLedger,
    PublishTarget,
    content_fingerprint,
    review_fingerprint,
)
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset

USER = "af-demo"
ORIGIN = "DEMO-3"
TARGET = PublishTarget(
    mode="functional",
    origin_kind="story",
    origin_key=ORIGIN,
    project_key="DEMO",
    user=USER,
    thread_id="hilo-1",
)


def _artifact(version: int = 1, origin_key: str | None = ORIGIN) -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.APPROVED,
        version=version,
        origin_key=origin_key,
        content=dataset.renewal_story(),
        created_by=USER,
    )


def _retitled(artifact: Artifact, title: str) -> Artifact:
    return artifact.model_copy(
        update={"content": artifact.content.model_copy(update={"title": title})}
    )


def test_fingerprint_is_stable_and_ignores_status() -> None:
    artifact = _artifact()
    in_review = artifact.model_copy(update={"status": ArtifactStatus.IN_REVIEW})
    assert content_fingerprint(artifact) == content_fingerprint(in_review)
    assert len(content_fingerprint(artifact)) == 64


@pytest.mark.parametrize(
    "change",
    [
        lambda a: _retitled(a, "Otro título"),
        lambda a: a.model_copy(update={"version": 2}),
        lambda a: a.model_copy(update={"origin_key": "DEMO-4"}),
    ],
)
def test_fingerprint_changes_with_content_version_or_target(change) -> None:
    artifact = _artifact()
    assert content_fingerprint(change(artifact)) != content_fingerprint(artifact)


def test_only_the_offered_version_and_operation_can_be_recorded() -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    with pytest.raises(ApprovalError):
        ledger.record(artifact, TARGET)
    ledger.offer(artifact, TARGET)
    with pytest.raises(ApprovalError):
        ledger.record(_retitled(artifact, "Manipulado"), TARGET)
    with pytest.raises(ApprovalError):
        ledger.record(artifact, replace(TARGET, origin_kind="epic"))
    with pytest.raises(ApprovalError):
        ledger.record(artifact, replace(TARGET, user="otro-usuario-ficticio"))
    assert ledger.record(artifact, TARGET).target == TARGET


def test_offer_rejects_target_key_different_from_artifact_origin() -> None:
    ledger = ApprovalLedger()
    artifact = _artifact(origin_key="DEMO-4")
    with pytest.raises(ApprovalError):
        ledger.offer(artifact, TARGET)


@pytest.mark.parametrize(
    "other",
    [
        replace(TARGET, origin_kind="epic"),
        replace(TARGET, mode="qa"),
        replace(TARGET, user="otro-usuario-ficticio"),
        replace(TARGET, thread_id="hilo-2"),
    ],
)
def test_target_is_fixed_across_iterations(other: PublishTarget) -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    iterated = _retitled(artifact.model_copy(update={"version": 2}), "Iterada")
    with pytest.raises(ApprovalError, match="destino"):
        ledger.offer(iterated, other)


def test_offer_is_consumed_by_record_and_published_version_cannot_be_reapproved() -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    approval = ledger.record(artifact, TARGET)
    with pytest.raises(ApprovalError):
        ledger.record(artifact, TARGET)  # la oferta ya se usó
    ledger.consume(approval, artifact)
    ledger.offer(artifact, TARGET)
    with pytest.raises(ApprovalError, match="ya se publicó"):
        ledger.record(artifact, TARGET)


def test_review_fingerprint_covers_operation() -> None:
    artifact = _artifact()
    epic = replace(TARGET, origin_kind="epic")
    assert review_fingerprint(artifact, TARGET) != review_fingerprint(artifact, epic)
    assert TARGET.describe() == {
        "operation": "actualizar HU",
        "project": "DEMO",
        "jira_key": ORIGIN,
        "epic_key": None,
    }


def test_new_offer_replaces_previous_one() -> None:
    ledger = ApprovalLedger()
    first = _artifact()
    ledger.offer(first, TARGET)
    second = _retitled(first, "Versión iterada")
    ledger.offer(second, TARGET)
    assert not ledger.is_offered(first, TARGET)
    assert ledger.is_offered(second, TARGET)


@pytest.mark.parametrize(
    "other",
    [
        replace(TARGET, user="otro-usuario-ficticio"),
        replace(TARGET, origin_key="DEMO-4"),
        replace(TARGET, origin_kind="epic"),
        replace(TARGET, mode="qa"),
        replace(TARGET, thread_id="hilo-2"),
    ],
)
def test_find_requires_same_operation(other: PublishTarget) -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    approval = ledger.record(artifact, TARGET)
    assert ledger.find(artifact, TARGET) == approval
    assert ledger.find(artifact, other) is None


def test_find_requires_same_version_and_content() -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    ledger.record(artifact, TARGET)
    assert ledger.find(_retitled(artifact, "Manipulado"), TARGET) is None
    assert ledger.find(artifact.model_copy(update={"version": 2}), TARGET) is None


def test_approval_is_single_use_and_tracks_published_version() -> None:
    ledger = ApprovalLedger()
    artifact = _artifact()
    ledger.offer(artifact, TARGET)
    approval = ledger.record(artifact, TARGET)
    published = artifact.model_copy(
        update={
            "status": ArtifactStatus.PUBLISHED,
            "content": artifact.content.model_copy(update={"jira_key": ORIGIN}),
        }
    )
    assert not ledger.was_published(published)
    ledger.consume(approval, published)
    assert ledger.find(artifact, TARGET) is None
    assert ledger.was_published(published)
    assert not ledger.was_published(_retitled(published, "Manipulado"))


def test_new_offer_invalidates_pending_approvals_of_older_versions() -> None:
    """PoC S1/S2: una aprobación sin usar de la v1 no sirve cuando ya se ofrece la v2."""
    ledger = ApprovalLedger()
    v1 = _artifact()
    ledger.offer(v1, TARGET)
    ledger.record(v1, TARGET)
    assert ledger.find(v1, TARGET) is not None
    v2 = _retitled(v1.model_copy(update={"version": 2}), "Versión 2")
    ledger.offer(v2, TARGET)
    assert ledger.find(v1, TARGET) is None
