"""Pruebas del registro de aprobaciones humanas (core/approvals.py)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from core.approvals import (
    Approval,
    ApprovalError,
    ApprovalLedger,
    PublishTarget,
    content_fingerprint,
    review_fingerprint,
)
from core.artifact_state import InMemoryArtifactStateStore
from core.audit import AuditEntry
from core.graph.nodes import spent_in_simulation
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


# --- PA-41: la publicación simulada gasta la aprobación -----------------------------------------


def _approved(ledger: ApprovalLedger, artifact: Artifact) -> Approval:
    ledger.offer(artifact, TARGET)
    return ledger.record(artifact, TARGET)


def test_simulated_consume_spends_approval_without_publication() -> None:
    """PA-41: tras simular, `find` no la devuelve, consta como simulada y no hay publicación."""
    ledger, artifact = ApprovalLedger(), _artifact()
    approval = _approved(ledger, artifact)

    ledger.consume(approval, artifact, simulated=True)

    assert ledger.find(artifact, TARGET) is None
    assert ledger.used_in_simulation(artifact, TARGET) is True
    spent = ledger.simulated_approval(artifact, TARGET)
    assert spent is not None and spent.simulated and spent.published_fingerprint is None
    assert ledger.was_published(artifact) is False


def test_simulated_approval_requires_same_target_and_content() -> None:
    """PA-41: la aprobación simulada solo acredita esa versión exacta y esa operación."""
    ledger, artifact = ApprovalLedger(), _artifact()
    ledger.consume(_approved(ledger, artifact), artifact, simulated=True)

    assert ledger.simulated_approval(artifact, replace(TARGET, project_key="OTRO")) is None
    assert ledger.simulated_approval(_retitled(artifact, "Otra HU ficticia"), TARGET) is None


def test_real_consume_is_not_simulated() -> None:
    ledger, artifact = ApprovalLedger(), _artifact()
    ledger.consume(_approved(ledger, artifact), artifact)

    assert ledger.used_in_simulation(artifact, TARGET) is False
    assert ledger.simulated_approval(artifact, TARGET) is None
    assert ledger.was_published(artifact) is True


def test_same_version_can_be_reapproved_after_simulation_with_later_instant() -> None:
    """PA-41: tras simular, una persona puede volver a aprobar la misma versión; la nueva
    aprobación tiene un instante posterior (aunque el reloj no haya avanzado) y sí publica."""
    ledger, artifact = ApprovalLedger(), _artifact()
    first = _approved(ledger, artifact)
    ledger.consume(first, artifact, simulated=True)

    second = _approved(ledger, artifact)

    assert second.at > first.at
    assert second.at.tzinfo is not None
    assert ledger.find(artifact, TARGET) == second


def test_really_published_version_still_cannot_be_reapproved() -> None:
    ledger, artifact = ApprovalLedger(), _artifact()
    ledger.consume(_approved(ledger, artifact), artifact)
    ledger.offer(artifact, TARGET)

    with pytest.raises(ApprovalError, match="ya se publicó"):
        ledger.record(artifact, TARGET)


def _stored(
    simulated: object = None, *, with_field: bool = True
) -> tuple[ApprovalLedger, Artifact, Approval]:
    """Registro persistido con la aprobación tocada a mano; devuelve un registro nuevo que lo
    relee (como otro proceso), el artefacto y la aprobación original."""
    store = InMemoryArtifactStateStore()
    writer, artifact = ApprovalLedger(store=store), _artifact()
    approval = _approved(writer, artifact)
    state = store.load(str(artifact.id))
    assert isinstance(state, dict)
    raw = state["ledger"]["approvals"][0]
    assert raw["simulated"] is False  # lo nuevo siempre lleva el campo
    if with_field:
        raw["simulated"] = simulated
    else:
        del raw["simulated"]
    store.save(str(artifact.id), state)
    return ApprovalLedger(store=store), artifact, approval


def test_stored_approval_without_simulated_field_is_read_as_not_simulated() -> None:
    """PA-41: los registros guardados antes del cambio (sin `simulated`) se leen sin error."""
    ledger, artifact, approval = _stored(with_field=False)

    found = ledger.find(artifact, TARGET)

    assert found is not None and found.simulated is False
    assert found.at == approval.at


@pytest.mark.parametrize("value", ["true", 1, None, []])
def test_stored_non_boolean_simulated_fails_closed(value: object) -> None:
    """PA-41 · PA-172: un `simulated` que no es booleano es un registro dañado."""
    ledger, artifact, _approval = _stored(value)

    with pytest.raises(ApprovalError, match="dañado"):
        ledger.find(artifact, TARGET)


# --- PA-41: regla de instantes frente a la auditoría --------------------------------------------

T0 = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)


def _approval_at(at: datetime, version: int = 1) -> Approval:
    return Approval(
        artifact_id=str(uuid4()), version=version, fingerprint="huella", target=TARGET, at=at
    )


def _simulation(version: int = 1, **detail: object) -> AuditEntry:
    return AuditEntry(
        artifact_id=None,
        action="publish",
        user=USER,
        detail={"version": version, "status": "approved", "simulated": True, **detail},
    )


def _dates(approval_at: datetime, simulated_at: datetime) -> dict[str, str]:
    return {"approval_at": approval_at.isoformat(), "simulated_at": simulated_at.isoformat()}


def test_approval_used_in_simulation_is_spent() -> None:
    used = _approval_at(T0)
    entry = _simulation(**_dates(T0, T0 + timedelta(seconds=2)))
    assert spent_in_simulation([entry], used) == "spent"


def test_approval_before_simulation_is_spent_even_if_not_the_used_one() -> None:
    older = _approval_at(T0 - timedelta(minutes=5))
    entry = _simulation(**_dates(T0, T0 + timedelta(seconds=2)))
    assert spent_in_simulation([entry], older)


def test_same_instant_as_used_approval_is_spent_even_if_equal_to_simulation() -> None:
    """Reloj de Windows: aprobar y simular en el mismo tic da instantes iguales."""
    used = _approval_at(T0)
    assert spent_in_simulation([_simulation(**_dates(T0, T0))], used)


def test_approval_after_simulation_is_not_spent() -> None:
    fresh = _approval_at(T0 + timedelta(minutes=1))
    assert not spent_in_simulation([_simulation(**_dates(T0, T0 + timedelta(seconds=2)))], fresh)


def test_later_approval_in_same_tick_as_simulation_is_not_spent() -> None:
    """Una aprobación nueva en el mismo tic que la simulación no es la usada (instante distinto)."""
    fresh = _approval_at(T0 + timedelta(microseconds=1))
    entry = _simulation(**_dates(T0, T0 + timedelta(microseconds=1)))
    assert not spent_in_simulation([entry], fresh)


def test_simulation_of_other_version_or_real_publish_does_not_count() -> None:
    old = _approval_at(T0 - timedelta(minutes=5))
    dates = _dates(T0, T0 + timedelta(seconds=2))
    real = AuditEntry(
        artifact_id=None, action="publish", user=USER, detail={"version": 1, "simulated": False}
    )
    assert not spent_in_simulation([_simulation(version=2, **dates), real], old)


def test_comparison_is_timezone_aware() -> None:
    """El mismo instante escrito en otra zona horaria cuenta igual."""
    madrid = timezone(timedelta(hours=2))
    used = _approval_at(T0)
    entry = _simulation(
        approval_at=T0.astimezone(madrid).isoformat(),
        simulated_at=(T0 + timedelta(seconds=1)).astimezone(madrid).isoformat(),
    )
    assert spent_in_simulation([entry], used)
    assert not spent_in_simulation([entry], _approval_at(T0 + timedelta(seconds=5)))


@pytest.mark.parametrize(
    "detail",
    [
        {},  # simulación anterior a PA-41: sin instantes
        {"simulated_at": "no-es-una-fecha"},
        {"simulated_at": "2026-10-06T09:00:00"},  # sin zona horaria
    ],
    ids=["sin-instantes", "no-fecha", "sin-zona"],
)
def test_simulation_without_valid_instant_fails_closed(detail: dict[str, str]) -> None:
    fresh = _approval_at(T0 + timedelta(days=1))
    assert spent_in_simulation([_simulation(**detail)], fresh) == "legacy"


def test_naive_approval_instant_fails_closed() -> None:
    naive = _approval_at(datetime(2026, 10, 7, 9, 0))
    assert spent_in_simulation([], naive)


def test_stored_approval_without_timezone_fails_closed() -> None:
    """PA-41: un instante guardado sin zona horaria es un registro dañado (mensaje en español)."""
    store = InMemoryArtifactStateStore()
    writer, artifact = ApprovalLedger(store=store), _artifact()
    _approved(writer, artifact)
    state = store.load(str(artifact.id))
    assert isinstance(state, dict)
    state["ledger"]["approvals"][0]["at"] = "2026-10-06T09:00:00"
    store.save(str(artifact.id), state)

    with pytest.raises(ApprovalError, match="dañado"):
        ApprovalLedger(store=store).find(artifact, TARGET)
