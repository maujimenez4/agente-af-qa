"""PA-41 · El registro de aprobaciones guarda `simulated` en PostgreSQL y lee lo anterior.

Pruebas de integración sobre una BD temporal (`tests/pg_temp.py`); se saltan si PostgreSQL no
está disponible. Varias instancias de `ApprovalLedger` sobre el mismo almacén simulan otro
proceso que relee lo guardado. Datos 100 % ficticios (proyecto DEMO).
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.engine import URL, Engine

from core.approvals import Approval, ApprovalError, ApprovalLedger, PublishTarget
from core.artifact_state import LEDGER_KEY, InMemoryArtifactStateStore, SqlArtifactStateStore
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.pg_temp import temporary_database, truncate_t25_tables

USER = "af-demo"
TARGET = PublishTarget(
    mode="functional",
    origin_kind="story",
    origin_key="DEMO-3",
    project_key="DEMO",
    user=USER,
    thread_id="hilo-ficticio-pa41",
)

pytestmark = pytest.mark.integration


def _artifact() -> Artifact:
    return Artifact(
        id=uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=1,
        origin_key="DEMO-3",
        content=dataset.renewal_story(),
        created_by=USER,
    )


def _approved(ledger: ApprovalLedger, artifact: Artifact) -> Approval:
    ledger.offer(artifact, TARGET)
    return ledger.record(artifact, TARGET)


@pytest.fixture(scope="module")
def pg_database() -> Iterator[tuple[URL, Engine]]:
    with temporary_database("ledger_simulated_test") as (url, engine):
        yield url, engine


@pytest.fixture
def store(pg_database: tuple[URL, Engine]) -> SqlArtifactStateStore:
    truncate_t25_tables(pg_database[1])
    return SqlArtifactStateStore(pg_database[1])


def test_simulated_consume_is_persisted_and_reread(store: SqlArtifactStateStore) -> None:
    """La aprobación gastada en simulación se guarda como tal y otro proceso la relee igual."""
    artifact = _artifact()
    writer = ApprovalLedger(store=store)
    approval = _approved(writer, artifact)
    writer.consume(approval, artifact, simulated=True)

    reader = ApprovalLedger(store=store)  # otro proceso
    assert reader.find(artifact, TARGET) is None
    spent = reader.simulated_approval(artifact, TARGET)
    assert spent is not None and spent.simulated and spent.consumed
    assert spent.at == approval.at  # mismo instante, con su zona horaria
    assert reader.used_in_simulation(artifact, TARGET) is True
    assert reader.was_published(artifact) is False
    raw = store.load(str(artifact.id))[LEDGER_KEY]["approvals"][0]  # type: ignore[index]
    assert raw["simulated"] is True and raw["published_fingerprint"] is None


def test_new_approval_after_simulation_is_persisted(store: SqlArtifactStateStore) -> None:
    artifact = _artifact()
    ledger = ApprovalLedger(store=store)
    first = _approved(ledger, artifact)
    ledger.consume(first, artifact, simulated=True)

    second = _approved(ApprovalLedger(store=store), artifact)

    reread = ApprovalLedger(store=store).find(artifact, TARGET)
    assert reread == second and second.at > first.at and not second.simulated


def test_ledger_saved_before_pa41_is_read(store: SqlArtifactStateStore) -> None:
    """Un registro guardado antes del cambio (aprobaciones sin `simulated`) se lee sin error."""
    artifact = _artifact()
    memory = InMemoryArtifactStateStore()
    approval = _approved(ApprovalLedger(store=memory), artifact)
    state = memory.load(str(artifact.id))
    assert isinstance(state, dict)
    for raw in state[LEDGER_KEY]["approvals"]:
        del raw["simulated"]
    store.save(str(artifact.id), state)

    found = ApprovalLedger(store=store).find(artifact, TARGET)

    assert found is not None and found.simulated is False and found.at == approval.at


def test_non_boolean_simulated_in_database_fails_closed(store: SqlArtifactStateStore) -> None:
    artifact = _artifact()
    memory = InMemoryArtifactStateStore()
    _approved(ApprovalLedger(store=memory), artifact)
    state = memory.load(str(artifact.id))
    assert isinstance(state, dict)
    state[LEDGER_KEY]["approvals"][0]["simulated"] = "true"
    store.save(str(artifact.id), state)

    with pytest.raises(ApprovalError, match="dañado"):
        ApprovalLedger(store=store).find(artifact, TARGET)
