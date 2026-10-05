"""PA-140 · Escritura condicional del registro de aprobaciones entre procesos.

Objeto de prueba: `core/artifact_state.py` (`ledger_revision`, `save` que no retrocede el
registro, `replace_ledger` condicional) y `core/approvals.py` (reintento con relectura,
`MAX_LEDGER_RETRIES`, revisión dañada). Varias instancias de `ApprovalLedger` sobre el mismo
almacén simulan varios procesos; un almacén con gancho intercala la escritura de «otro proceso»
entre la lectura y la escritura de una decisión.

Las unitarias usan `InMemoryArtifactStateStore` y motores espía (sin red). Las de integración
usan una BD temporal (`tests/pg_temp.py`) y procesos reales (contexto "spawn"); se saltan si
PostgreSQL no está disponible. Datos 100 % ficticios (proyecto DEMO, biblioteca de
Villaficticia).
"""

import multiprocessing
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, Engine

from adapters.errors import ExternalServiceError
from core.approvals import (
    MAX_LEDGER_RETRIES,
    Approval,
    ApprovalError,
    ApprovalLedger,
    PublishTarget,
)
from core.artifact_state import (
    LEDGER_KEY,
    InMemoryArtifactStateStore,
    SqlArtifactStateStore,
    ledger_revision,
)
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.pg_temp import temporary_database, truncate_t25_tables

USER = "af-villaficticia"
TARGET = PublishTarget(
    mode="functional",
    origin_kind="story",
    origin_key="DEMO-3",
    project_key="DEMO",
    user=USER,
    thread_id="hilo-ficticio-pa140",
)
BUSY = "Otro proceso está cambiando"
DAMAGED = "dañado"


# --- utilidades --------------------------------------------------------------------------


def _artifact(version: int = 1, *, artifact_id: UUID | None = None, title: str = "") -> Artifact:
    story = dataset.renewal_story()
    if title:
        story = story.model_copy(update={"title": title})
    return Artifact(
        id=artifact_id or uuid4(),
        type=ArtifactType.USER_STORY,
        status=ArtifactStatus.IN_REVIEW,
        version=version,
        origin_key="DEMO-3",
        content=story,
        created_by=USER,
    )


def _approved(ledger: ApprovalLedger, artifact: Artifact) -> Approval:
    ledger.offer(artifact, TARGET)
    return ledger.record(artifact, TARGET)


def _ledger_state(store: InMemoryArtifactStateStore, artifact: Artifact) -> dict[str, Any]:
    state = store.load(str(artifact.id))
    assert state is not None
    return state[LEDGER_KEY]


class HookedStore(InMemoryArtifactStateStore):
    """Almacén en memoria que ejecuta `before_replace` una vez, justo antes de la primera
    escritura condicional: simula otro proceso que escribe entre la lectura y la escritura."""

    def __init__(self) -> None:
        super().__init__()
        self.before_replace: Callable[[], None] | None = None
        self.attempts: list[tuple[int, bool]] = []

    def replace_ledger(
        self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
    ) -> bool:
        hook, self.before_replace = self.before_replace, None
        if hook is not None:
            hook()
        ok = super().replace_ledger(artifact_id, ledger, expected_revision)
        self.attempts.append((expected_revision, ok))
        return ok


class AlwaysBusyStore(InMemoryArtifactStateStore):
    """Almacén cuyo `replace_ledger` siempre pierde la carrera (otro proceso escribe siempre)."""

    def __init__(self) -> None:
        super().__init__()
        self.replace_calls = 0

    def replace_ledger(
        self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
    ) -> bool:
        self.replace_calls += 1
        return False


class _RowResult:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class RowcountEngine:
    """Engine espía: guarda sentencias y parámetros; la última sentencia afecta `rowcount`."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    @contextmanager
    def begin(self) -> Iterator["RowcountEngine"]:
        yield self

    def execute(self, statement: Any, parameters: dict[str, Any] | None = None) -> _RowResult:
        self.calls.append((str(statement), parameters))
        return _RowResult(self.rowcount)


class BrokenEngine:
    """Engine que falla al abrir la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise sa.exc.OperationalError("SELECT 1", {}, Exception("conexión rechazada (ficticia)"))


# --- ledger_revision ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"baseline": {"title": "Partida ficticia"}},
        {LEDGER_KEY: None},
        {LEDGER_KEY: "texto-ficticio"},
        {LEDGER_KEY: {"offer": None}},
        {LEDGER_KEY: {"revision": "x"}},
        {LEDGER_KEY: {"revision": "3"}},
        {LEDGER_KEY: {"revision": 2.0}},
        {LEDGER_KEY: {"revision": -1}},
        {LEDGER_KEY: {"revision": True}},
        {LEDGER_KEY: {"revision": None}},
        ["no", "es", "un", "dict"],
    ],
)
def test_ledger_revision_is_zero_when_state_or_revision_is_missing_or_invalid(state: Any) -> None:
    """PA-140 (límite): sin estado, sin registro o con revisión no entera, negativa o bool → 0."""
    assert ledger_revision(state) == 0


@pytest.mark.parametrize("revision", [0, 1, 7, 10_000])
def test_ledger_revision_returns_stored_value_when_valid(revision: int) -> None:
    """PA-140: con una revisión entera ≥ 0 se devuelve tal cual."""
    assert ledger_revision({LEDGER_KEY: {"revision": revision}}) == revision


# --- InMemoryArtifactStateStore.save y replace_ledger --------------------------------------


def test_in_memory_save_keeps_newer_ledger_when_incoming_revision_is_older() -> None:
    """PA-140: `save` nunca retrocede el registro; el resto del estado sí se sustituye."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    newer = {"revision": 3, "offer": None, "approvals": [{"consumed": True}]}
    store.save(artifact_id, {LEDGER_KEY: newer, "baseline": {"title": "Partida ficticia"}})

    store.save(artifact_id, {LEDGER_KEY: {"revision": 1, "offer": "huella-vieja"}, "run": 2})

    assert store.load(artifact_id) == {LEDGER_KEY: newer, "run": 2}


def test_in_memory_save_keeps_ledger_when_incoming_state_has_no_ledger() -> None:
    """PA-140 (límite): un `save` sin la clave del registro no lo borra si tenía revisión."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    store.save(artifact_id, {LEDGER_KEY: {"revision": 1, "offer": None}})

    store.save(artifact_id, {"baseline": {"title": "Partida ficticia"}})

    assert store.load(artifact_id) == {
        LEDGER_KEY: {"revision": 1, "offer": None},
        "baseline": {"title": "Partida ficticia"},
    }


@pytest.mark.parametrize("incoming", [2, 5])
def test_in_memory_save_replaces_ledger_when_incoming_revision_is_equal_or_newer(
    incoming: int,
) -> None:
    """PA-140: con la misma revisión o una mayor, el registro que llega se guarda."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    store.save(artifact_id, {LEDGER_KEY: {"revision": 2, "offer": "a"}})

    store.save(artifact_id, {LEDGER_KEY: {"revision": incoming, "offer": "b"}})

    assert store.load(artifact_id) == {LEDGER_KEY: {"revision": incoming, "offer": "b"}}


def test_in_memory_replace_ledger_fails_without_changes_when_revision_differs() -> None:
    """PA-140 (negativo): revisión esperada distinta → False y nada cambia."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    before = {LEDGER_KEY: {"revision": 2, "offer": "a"}, "baseline": {"title": "Partida"}}
    store.save(artifact_id, before)

    assert store.replace_ledger(artifact_id, {"revision": 2, "offer": "b"}, 1) is False
    assert store.replace_ledger(artifact_id, {"revision": 4, "offer": "b"}, 3) is False
    assert store.load(artifact_id) == before


def test_in_memory_replace_ledger_changes_only_ledger_when_revision_matches() -> None:
    """PA-140: revisión esperada correcta → True y solo cambia la clave `ledger`."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    store.save(artifact_id, {LEDGER_KEY: {"revision": 2}, "baseline": {"title": "Partida"}})

    assert store.replace_ledger(artifact_id, {"revision": 3, "offer": "b"}, 2) is True
    assert store.load(artifact_id) == {
        LEDGER_KEY: {"revision": 3, "offer": "b"},
        "baseline": {"title": "Partida"},
    }


def test_in_memory_replace_ledger_creates_state_when_artifact_unknown_and_expected_zero() -> None:
    """PA-140 (límite): sin estado previo la revisión es 0; esperar 0 escribe, esperar 1 no."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())

    assert store.replace_ledger(artifact_id, {"revision": 2}, 1) is False
    assert store.load(artifact_id) is None
    assert store.replace_ledger(artifact_id, {"revision": 1}, 0) is True
    assert store.load(artifact_id) == {LEDGER_KEY: {"revision": 1}}


def test_in_memory_replace_ledger_is_not_changed_when_caller_mutates_ledger_later() -> None:
    """PA-140 (límite): mutar el dict pasado no cambia lo guardado."""
    store = InMemoryArtifactStateStore()
    artifact_id = str(uuid4())
    ledger: dict[str, Any] = {"revision": 1, "offer": None}
    store.replace_ledger(artifact_id, ledger, 0)
    ledger["offer"] = "manipulada"

    assert store.load(artifact_id) == {LEDGER_KEY: {"revision": 1, "offer": None}}


# --- SqlArtifactStateStore.replace_ledger (motor espía) ------------------------------------


@pytest.mark.parametrize(("rowcount", "expected"), [(1, True), (0, False)])
def test_sql_replace_ledger_returns_whether_row_was_updated(rowcount: int, expected: bool) -> None:
    """PA-140: la escritura condicional devuelve True solo si actualizó la fila; la revisión
    esperada y el registro van como parámetros, nunca concatenados en el SQL."""
    engine = RowcountEngine(rowcount)
    artifact_id = str(uuid4())
    store = SqlArtifactStateStore(engine)  # type: ignore[arg-type]

    result = store.replace_ledger(artifact_id, {"revision": 8, "offer": "marca-ficticia"}, 7)

    assert result is expected
    sql_text = " ".join(sql for sql, _params in engine.calls)
    assert "marca-ficticia" not in sql_text
    (update_sql, update_params) = engine.calls[-1]
    assert update_sql.startswith("UPDATE artifact_state")
    assert ":expected" in update_sql
    assert update_params is not None
    assert update_params["expected"] == 7
    assert update_params["artifact_id"] == UUID(artifact_id)
    assert "marca-ficticia" in update_params["ledger"]


def test_sql_replace_ledger_wraps_database_errors_when_unreachable() -> None:
    """PA-140 (error): BD caída → ExternalServiceError en español, sin causa encadenada."""
    store = SqlArtifactStateStore(BrokenEngine())  # type: ignore[arg-type]
    with pytest.raises(ExternalServiceError, match="registro de aprobaciones") as info:
        store.replace_ledger(str(uuid4()), {"revision": 1}, 0)
    assert info.value.__cause__ is None


def test_sql_save_sends_state_as_parameter_when_saving() -> None:
    """PA-140: `save` conserva el registro más nuevo en SQL y el estado va como parámetro."""
    engine = RowcountEngine(1)
    SqlArtifactStateStore(engine).save(  # type: ignore[arg-type]
        str(uuid4()), {"baseline": {"title": "marca-ficticia"}}
    )
    ((sql, params),) = engine.calls
    assert "ON CONFLICT (artifact_id) DO UPDATE" in sql
    assert "artifact_state.state->'ledger'" in sql
    assert "marca-ficticia" not in sql
    assert params is not None and "marca-ficticia" in params["state"]


# --- ApprovalLedger: revisión y conflicto -------------------------------------------------


def test_ledger_writes_increasing_revisions_when_deciding() -> None:
    """PA-140: cada decisión guardada incrementa la revisión del registro en uno."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()

    ledger.offer(artifact, TARGET)
    assert _ledger_state(store, artifact)["revision"] == 1
    approval = ledger.record(artifact, TARGET)
    assert _ledger_state(store, artifact)["revision"] == 2
    ledger.consume(approval, artifact)
    assert _ledger_state(store, artifact)["revision"] == 3


def test_stale_consume_rereads_and_fails_closed_when_other_process_consumed_first() -> None:
    """PA-140 · PA-173: la segunda instancia decide con datos viejos, su `replace_ledger`
    falla, relee y vuelve a decidir: la aprobación ya está consumida → `ApprovalError`."""
    store = HookedStore()
    first = ApprovalLedger(store=store)
    artifact = _artifact()
    approval = _approved(first, artifact)
    second = ApprovalLedger(store=store)
    store.attempts.clear()
    store.before_replace = lambda: ApprovalLedger(store=store).consume(approval, artifact)

    with pytest.raises(ApprovalError, match="ya no está vigente"):
        second.consume(approval, artifact)

    # 2 → escribe el «otro proceso» (3); la segunda falla con esperada 2 y no vuelve a escribir.
    assert store.attempts == [(2, True), (2, False)]
    ledger = _ledger_state(store, artifact)
    assert ledger["revision"] == 3
    (saved,) = ledger["approvals"]
    assert saved["consumed"] is True


def test_stale_offer_rereads_and_keeps_consumed_mark_when_other_process_wrote_first() -> None:
    """PA-140: una oferta decidida con datos viejos se rehace con los frescos; la publicación
    que registró otro proceso entre medias (`consumed=True`) no se pierde."""
    store = HookedStore()
    first = ApprovalLedger(store=store)
    v1 = _artifact()
    approval = _approved(first, v1)
    v2 = _artifact(2, artifact_id=v1.id, title="Iterada desde otra pestaña (ficticia)")
    store.before_replace = lambda: ApprovalLedger(store=store).consume(approval, v1)

    ApprovalLedger(store=store).offer(v2, TARGET)

    ledger = _ledger_state(store, v1)
    assert ledger["revision"] == 4
    assert [a["consumed"] for a in ledger["approvals"]] == [True]
    fresh = ApprovalLedger(store=store)
    assert fresh.was_published(v1)
    assert fresh.is_offered(v2, TARGET)


def test_double_consume_fails_closed_when_two_instances_share_store() -> None:
    """PA-140 · PA-173: dos «procesos» consumen la misma aprobación; el segundo falla cerrado."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    approval = _approved(ApprovalLedger(store=store), artifact)
    first, second = ApprovalLedger(store=store), ApprovalLedger(store=store)
    assert first.find(artifact, TARGET) is not None
    assert second.find(artifact, TARGET) is not None  # ambos la ven vigente

    first.consume(approval, artifact)
    with pytest.raises(ApprovalError):
        second.consume(approval, artifact)

    assert _ledger_state(store, artifact)["revision"] == 3


def test_ledger_raises_busy_error_after_max_retries_when_every_write_conflicts() -> None:
    """PA-140 (error): tras `MAX_LEDGER_RETRIES` conflictos seguidos → `ApprovalError`
    «Otro proceso está cambiando…» y nunca se escribe a ciegas."""
    store = AlwaysBusyStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()

    with pytest.raises(ApprovalError, match=BUSY):
        ledger.offer(artifact, TARGET)

    assert store.replace_calls == MAX_LEDGER_RETRIES
    assert store.load(str(artifact.id)) is None


@pytest.mark.parametrize("method", ["record", "consume"])
def test_record_and_consume_raise_busy_error_when_every_write_conflicts(method: str) -> None:
    """PA-140 (error): `record` y `consume` también agotan los reintentos y fallan cerrado."""
    artifact = _artifact()
    seeded = InMemoryArtifactStateStore()
    seed_ledger = ApprovalLedger(store=seeded)
    if method == "record":
        seed_ledger.offer(artifact, TARGET)
    else:
        approval = _approved(seed_ledger, artifact)
    store = AlwaysBusyStore()
    store.states = dict(seeded.states)
    ledger = ApprovalLedger(store=store)

    with pytest.raises(ApprovalError, match=BUSY):
        if method == "record":
            ledger.record(artifact, TARGET)
        else:
            ledger.consume(approval, artifact)

    assert store.replace_calls == MAX_LEDGER_RETRIES
    assert store.states == seeded.states  # nada cambió


def test_ledger_succeeds_when_conflicts_are_fewer_than_max_retries() -> None:
    """PA-140 (límite): con `MAX_LEDGER_RETRIES - 1` conflictos la decisión acaba guardándose."""

    class FlakyStore(InMemoryArtifactStateStore):
        def __init__(self) -> None:
            super().__init__()
            self.failures_left = MAX_LEDGER_RETRIES - 1

        def replace_ledger(
            self, artifact_id: str, ledger: dict[str, Any], expected_revision: int
        ) -> bool:
            if self.failures_left:
                self.failures_left -= 1
                return False
            return super().replace_ledger(artifact_id, ledger, expected_revision)

    store = FlakyStore()
    artifact = _artifact()

    ApprovalLedger(store=store).offer(artifact, TARGET)

    assert _ledger_state(store, artifact)["revision"] == 1


@pytest.mark.parametrize("revision", ["x", -1, True, 1.5, None])
def test_ledger_fails_closed_when_stored_revision_is_invalid(revision: Any) -> None:
    """PA-140 (error): una revisión guardada no entera o negativa → registro dañado."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    damaged = {"revision": revision, "target": None, "offer": None, "approvals": []}
    store.states[str(artifact.id)] = {LEDGER_KEY: damaged}
    ledger = ApprovalLedger(store=store)

    with pytest.raises(ApprovalError, match=DAMAGED):
        ledger.find(artifact, TARGET)
    with pytest.raises(ApprovalError, match=DAMAGED):
        ledger.offer(artifact, TARGET)
    assert store.states[str(artifact.id)] == {LEDGER_KEY: damaged}  # sin tocar


def test_full_save_with_old_ledger_does_not_lose_consumed_mark_when_interleaved() -> None:
    """PA-140: otro nodo lee el estado, el registro se consume y el nodo guarda su estado
    completo (con el registro antiguo): `consumed=True` se conserva y el resto se guarda."""
    store = InMemoryArtifactStateStore()
    ledger = ApprovalLedger(store=store)
    artifact = _artifact()
    artifact_id = str(artifact.id)
    store.save(artifact_id, {"baseline": {"title": "Partida ficticia"}})
    approval = _approved(ledger, artifact)
    snapshot = store.load(artifact_id)  # el otro nodo lee (revisión 2)
    assert snapshot is not None

    ApprovalLedger(store=store).consume(approval, artifact)  # revisión 3
    snapshot.pop("baseline")  # el otro nodo borra la versión de partida y guarda todo
    store.save(artifact_id, snapshot)

    state = store.load(artifact_id)
    assert state is not None and "baseline" not in state
    assert state[LEDGER_KEY]["revision"] == 3
    assert ApprovalLedger(store=store).was_published(artifact)
    assert ApprovalLedger(store=store).find(artifact, TARGET) is None


def test_concurrent_consume_from_many_ledger_instances_publishes_once() -> None:
    """PA-140 · PA-173: varios hilos, cada uno con su propia instancia (como procesos) sobre el
    mismo almacén, consumen la misma aprobación: exactamente uno gana."""
    store = InMemoryArtifactStateStore()
    artifact = _artifact()
    approval = _approved(ApprovalLedger(store=store), artifact)
    workers = 8
    barrier = threading.Barrier(workers)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker() -> None:
        ledger = ApprovalLedger(store=store)
        ledger.find(artifact, TARGET)  # cada «proceso» carga su caché
        barrier.wait(timeout=10)
        try:
            ledger.consume(approval, artifact)
            outcome = "consumido"
        except ApprovalError:
            outcome = "rechazado"
        with results_lock:
            results.append(outcome)

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert sorted(results) == ["consumido"] + ["rechazado"] * (workers - 1)
    assert _ledger_state(store, artifact)["revision"] == 3
    assert ApprovalLedger(store=store).was_published(artifact)


def test_ledger_without_conditional_write_still_works_when_store_is_legacy() -> None:
    """PA-140 (compatibilidad): un almacén sin `replace_ledger` usa lectura-cambio-escritura."""

    class LegacyStore:
        def __init__(self) -> None:
            self.states: dict[str, dict[str, Any]] = {}

        def load(self, artifact_id: str) -> dict[str, Any] | None:
            state = self.states.get(artifact_id)
            return dict(state) if state is not None else None

        def save(self, artifact_id: str, state: dict[str, Any]) -> None:
            self.states[artifact_id] = dict(state)

    store = LegacyStore()
    artifact = _artifact()
    ledger = ApprovalLedger(store=store)  # type: ignore[arg-type]
    ledger.consume(_approved(ledger, artifact), artifact)

    assert ApprovalLedger(store=store).was_published(artifact)  # type: ignore[arg-type]


# --- Integración con PostgreSQL ------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_database() -> Iterator[tuple[URL, Engine]]:
    with temporary_database("ledger_concurrency_test") as (url, engine):
        yield url, engine


@pytest.fixture
def pg(pg_database: tuple[URL, Engine]) -> tuple[URL, Engine]:
    truncate_t25_tables(pg_database[1])
    return pg_database


def _consume_in_process(
    url: URL,
    artifact_json: str,
    approval: Approval,
    barrier: Any,
    results: Any,
) -> None:
    """Proceso hijo (nivel de módulo, para "spawn"): consume la aprobación con su propio
    motor y su propio registro, a la vez que los demás."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool, connect_args={"connect_timeout": 5})
    try:
        ledger = ApprovalLedger(store=SqlArtifactStateStore(engine))
        artifact = Artifact.model_validate_json(artifact_json)
        ledger.find(artifact, approval.target)  # carga su caché antes de competir
        barrier.wait(timeout=60)
        try:
            ledger.consume(approval, artifact)
            results.put("consumido")
        except ApprovalError:
            results.put("rechazado")
    except Exception as exc:  # cualquier otro fallo se informa al padre
        results.put(f"error:{type(exc).__name__}")
    finally:
        engine.dispose()


@pytest.mark.integration
def test_sql_save_keeps_newer_ledger_when_incoming_revision_is_older(
    pg: tuple[URL, Engine],
) -> None:
    """PA-140 (BD real): `save` no retrocede el registro y sustituye el resto del estado."""
    store = SqlArtifactStateStore(pg[1])
    artifact_id = str(uuid4())
    newer = {"revision": 3, "offer": None, "approvals": []}
    store.save(artifact_id, {LEDGER_KEY: newer, "baseline": {"title": "Partida ficticia"}})

    store.save(artifact_id, {LEDGER_KEY: {"revision": 1, "offer": "vieja"}, "run": 2})
    assert store.load(artifact_id) == {LEDGER_KEY: newer, "run": 2}

    store.save(artifact_id, {"run": 3})  # sin registro: tampoco se pierde
    assert store.load(artifact_id) == {LEDGER_KEY: newer, "run": 3}

    store.save(artifact_id, {LEDGER_KEY: {"revision": 4, "offer": "nueva"}})
    assert store.load(artifact_id) == {LEDGER_KEY: {"revision": 4, "offer": "nueva"}}


@pytest.mark.integration
def test_sql_replace_ledger_is_conditional_on_stored_revision(pg: tuple[URL, Engine]) -> None:
    """PA-140 (BD real): `replace_ledger` solo escribe con la revisión esperada y solo toca
    la clave `ledger`."""
    store = SqlArtifactStateStore(pg[1])
    artifact_id = str(uuid4())
    assert store.replace_ledger(artifact_id, {"revision": 1, "offer": "a"}, 0) is True
    store.save(artifact_id, {LEDGER_KEY: {"revision": 1, "offer": "a"}, "baseline": {"t": 1}})

    assert store.replace_ledger(artifact_id, {"revision": 2, "offer": "b"}, 0) is False
    assert store.replace_ledger(artifact_id, {"revision": 3, "offer": "b"}, 2) is False
    assert store.load(artifact_id) == {
        LEDGER_KEY: {"revision": 1, "offer": "a"},
        "baseline": {"t": 1},
    }

    assert store.replace_ledger(artifact_id, {"revision": 2, "offer": "b"}, 1) is True
    assert store.load(artifact_id) == {
        LEDGER_KEY: {"revision": 2, "offer": "b"},
        "baseline": {"t": 1},
    }


@pytest.mark.integration
def test_sql_ledger_stale_consume_fails_closed_when_other_instance_consumed(
    pg: tuple[URL, Engine],
) -> None:
    """PA-140 · PA-173 (BD real): doble consumo desde dos instancias → el segundo falla."""
    engine = pg[1]
    artifact = _artifact()
    approval = _approved(ApprovalLedger(store=SqlArtifactStateStore(engine)), artifact)
    first = ApprovalLedger(store=SqlArtifactStateStore(engine))
    second = ApprovalLedger(store=SqlArtifactStateStore(engine))
    second.find(artifact, TARGET)

    first.consume(approval, artifact)
    with pytest.raises(ApprovalError):
        second.consume(approval, artifact)

    assert ApprovalLedger(store=SqlArtifactStateStore(engine)).was_published(artifact)


@pytest.mark.integration
def test_sql_ledger_consumed_once_when_many_processes_compete(pg: tuple[URL, Engine]) -> None:
    """PA-140 · PA-173 (BD real, procesos "spawn"): varios procesos consumen la misma
    aprobación a la vez y exactamente uno gana; los demás fallan cerrado."""
    url, engine = pg
    artifact = _artifact()
    approval = _approved(ApprovalLedger(store=SqlArtifactStateStore(engine)), artifact)
    ctx = multiprocessing.get_context("spawn")
    workers = 4
    barrier = ctx.Barrier(workers)
    results = ctx.Queue()
    processes = [
        ctx.Process(
            target=_consume_in_process,
            args=(url, artifact.model_dump_json(), approval, barrier, results),
        )
        for _ in range(workers)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=120) for _ in range(workers)]
    for process in processes:
        process.join(timeout=60)

    assert sorted(outcomes) == ["consumido"] + ["rechazado"] * (workers - 1)
    assert all(process.exitcode == 0 for process in processes)
    stored = SqlArtifactStateStore(engine).load(str(artifact.id))
    assert stored is not None and stored[LEDGER_KEY]["revision"] == 3
    assert ApprovalLedger(store=SqlArtifactStateStore(engine)).was_published(artifact)
