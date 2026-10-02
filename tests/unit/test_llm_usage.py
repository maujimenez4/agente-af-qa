"""Pruebas de adapters/llm/usage.py (T-10 · RF-43, RNF-27).

Registro del consumo de tokens por llamada en memoria y en la tabla `llm_usage`.
Datos 100 % sintéticos; la base de datos es SQLite en memoria (sin servicios externos).
"""

import dataclasses
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from adapters.base import TaskType
from adapters.llm.usage import (
    LLM_USAGE_TABLE,
    InMemoryUsageRecorder,
    SqlUsageRecorder,
    UsageRecord,
    UsageRecorder,
    current_artifact_id,
    usage_scope,
)
from core.usage import SqlUsageQueries

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _record(
    input_tokens: int = 10,
    output_tokens: int = 5,
    *,
    at: datetime = NOW,
    task: TaskType = TaskType.GENERATE_STORY,
    **kwargs: object,
) -> UsageRecord:
    return UsageRecord(
        task=task,
        provider="proveedor-ficticio",
        model="modelo-ficticio",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=42,
        at=at,
        **kwargs,  # type: ignore[arg-type]
    )


@pytest.fixture
def engine() -> sa.Engine:
    engine = sa.create_engine("sqlite://")
    LLM_USAGE_TABLE.metadata.create_all(engine)
    return engine


def _rows(engine: sa.Engine) -> list[sa.RowMapping]:
    with engine.connect() as conn:
        return list(conn.execute(sa.select(LLM_USAGE_TABLE)).mappings().all())


# --- UsageRecord ---------------------------------------------------------------------------


def test_total_tokens_sums_input_and_output() -> None:
    """RF-43: el total de tokens de una llamada es entrada + salida."""
    assert _record(120, 30).total_tokens == 150


def test_usage_record_defaults_free_cost_and_utc_timestamp() -> None:
    """RF-43 · D-14: coste estimado 0 por defecto, sin artefacto y con marca de tiempo UTC."""
    before = datetime.now(UTC)
    record = UsageRecord(
        task=TaskType.CLASSIFY_SOURCE,
        provider="proveedor-ficticio",
        model="modelo-ficticio",
        input_tokens=1,
        output_tokens=1,
        latency_ms=0,
    )
    after = datetime.now(UTC)

    assert record.est_cost == Decimal("0")
    assert record.artifact_id is None
    assert record.at.tzinfo is not None
    assert before <= record.at <= after


def test_usage_record_is_immutable_when_assigning() -> None:
    """RF-43: un registro de uso no se puede alterar una vez creado (frozen)."""
    record = _record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.input_tokens = 999  # type: ignore[misc]


# --- InMemoryUsageRecorder ------------------------------------------------------------------


def test_in_memory_recorder_satisfies_protocol_when_instantiated() -> None:
    """RF-43: InMemoryUsageRecorder cumple el protocolo UsageRecorder."""
    assert isinstance(InMemoryUsageRecorder(), UsageRecorder)


def test_in_memory_recorder_keeps_records_in_order() -> None:
    """RF-43: cada llamada registrada queda en `records` en el orden de registro."""
    recorder = InMemoryUsageRecorder()
    first, second = _record(1, 1), _record(2, 2)

    recorder.record(first)
    recorder.record(second)

    assert recorder.records == [first, second]


def test_in_memory_tokens_since_excludes_older_records() -> None:
    """RNF-27: el consumo desde una fecha suma solo los registros posteriores o iguales."""
    recorder = InMemoryUsageRecorder()
    recorder.record(_record(100, 100, at=NOW - timedelta(days=1)))
    recorder.record(_record(10, 5, at=NOW))
    recorder.record(_record(3, 2, at=NOW + timedelta(minutes=5)))

    assert recorder.tokens_since(NOW) == 20


def test_in_memory_tokens_since_returns_zero_when_empty() -> None:
    """RNF-27: sin registros, el consumo es 0."""
    assert InMemoryUsageRecorder().tokens_since(NOW) == 0


def test_in_memory_tokens_since_returns_zero_when_all_older() -> None:
    """RNF-27 (límite): si todos los registros son anteriores, el consumo es 0."""
    recorder = InMemoryUsageRecorder()
    recorder.record(_record(50, 50, at=NOW - timedelta(seconds=1)))

    assert recorder.tokens_since(NOW) == 0


# --- Tabla llm_usage y SqlUsageRecorder -----------------------------------------------------


def test_llm_usage_table_has_spec_columns_without_id() -> None:
    """RF-43 · SPEC-00 §6: `llm_usage` tiene las columnas del contrato (el id lo pone la BD)."""
    assert LLM_USAGE_TABLE.name == "llm_usage"
    assert set(LLM_USAGE_TABLE.columns.keys()) == {
        "task",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "est_cost",
        "latency_ms",
        "artifact_id",
        "at",
    }


def test_llm_usage_table_column_types_match_contract() -> None:
    """RF-43: est_cost es Numeric, artifact_id es Uuid y at es DateTime con zona horaria."""
    columns = LLM_USAGE_TABLE.columns
    assert isinstance(columns["est_cost"].type, sa.Numeric)
    assert isinstance(columns["artifact_id"].type, sa.Uuid)
    assert isinstance(columns["at"].type, sa.DateTime)
    assert columns["at"].type.timezone is True


def test_sql_recorder_satisfies_protocol_when_instantiated(engine: sa.Engine) -> None:
    """RF-43: SqlUsageRecorder cumple el protocolo UsageRecorder."""
    assert isinstance(SqlUsageRecorder(engine), UsageRecorder)


def test_sql_recorder_inserts_row_with_task_value(engine: sa.Engine) -> None:
    """RF-43: cada llamada se guarda como una fila; la tarea se guarda como su valor de texto."""
    recorder = SqlUsageRecorder(engine)

    recorder.record(_record(10, 5))

    rows = _rows(engine)
    assert len(rows) == 1
    row = rows[0]
    assert row["task"] == "generate_story"
    assert row["provider"] == "proveedor-ficticio"
    assert row["model"] == "modelo-ficticio"
    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 5
    assert row["latency_ms"] == 42
    assert row["at"] is not None


def test_sql_recorder_persists_cost_and_artifact_id(engine: sa.Engine) -> None:
    """RF-43: el coste estimado y el artefacto de origen quedan registrados."""
    artifact_id = uuid4()
    recorder = SqlUsageRecorder(engine)

    recorder.record(_record(est_cost=Decimal("0.0015"), artifact_id=artifact_id))

    row = _rows(engine)[0]
    assert Decimal(str(row["est_cost"])) == Decimal("0.0015")
    assert row["artifact_id"] == artifact_id


def test_sql_recorder_persists_null_artifact_id_when_missing(engine: sa.Engine) -> None:
    """RF-43 (límite): una llamada sin artefacto guarda artifact_id nulo y coste 0."""
    SqlUsageRecorder(engine).record(_record())

    row = _rows(engine)[0]
    assert row["artifact_id"] is None
    assert Decimal(str(row["est_cost"])) == Decimal("0")


def test_sql_recorder_tokens_since_excludes_older_records(engine: sa.Engine) -> None:
    """RNF-27: el consumo desde una fecha excluye los registros anteriores a `since`."""
    recorder = SqlUsageRecorder(engine)
    recorder.record(_record(100, 100, at=NOW - timedelta(days=1)))
    recorder.record(_record(10, 5, at=NOW + timedelta(minutes=1)))
    recorder.record(_record(3, 2, at=NOW + timedelta(hours=1), task=TaskType.NL_TO_JQL))

    assert recorder.tokens_since(NOW) == 20


def test_sql_recorder_tokens_since_returns_zero_when_empty(engine: sa.Engine) -> None:
    """RNF-27: sin filas, el consumo es 0 (no None)."""
    assert SqlUsageRecorder(engine).tokens_since(NOW) == 0


# --- T-32 · usage_scope y current_artifact_id (RF-43) --------------------------------------


def test_current_artifact_id_is_none_when_outside_scope() -> None:
    """CA-5: sin bloque, no hay artefacto asociado."""
    assert current_artifact_id() is None


def test_usage_scope_sets_and_restores_artifact_id() -> None:
    """CA-5: dentro del bloque se ve el artifact_id; al salir, el anterior (anidado)."""
    outer, inner = uuid4(), uuid4()

    with usage_scope(artifact_id=outer):
        assert current_artifact_id() == outer
        with usage_scope(artifact_id=inner):
            assert current_artifact_id() == inner
        assert current_artifact_id() == outer
        with usage_scope(artifact_id=None):
            assert current_artifact_id() is None
        assert current_artifact_id() == outer
    assert current_artifact_id() is None


def test_usage_scope_restores_artifact_id_when_block_raises() -> None:
    """CA-5: una excepción dentro del bloque no deja el artifact_id puesto."""
    with pytest.raises(RuntimeError), usage_scope(artifact_id=uuid4()):
        raise RuntimeError("fallo ficticio")

    assert current_artifact_id() is None


def test_usage_scope_is_not_visible_from_other_thread() -> None:
    """CA-5: cada hilo (sesión) ve solo su artefacto."""
    seen: list[UUID | None] = []

    with usage_scope(artifact_id=uuid4()):
        thread = threading.Thread(target=lambda: seen.append(current_artifact_id()))
        thread.start()
        thread.join(timeout=10)

    assert seen == [None]


# --- T-32 · SqlUsageRecorder.from_url y SqlUsageQueries (RF-43) ----------------------------


def test_sql_recorder_from_url_writes_and_reads_sqlite_file(tmp_path: Path) -> None:
    """CA-6: `from_url` con una URL de SQLite crea un recorder operativo."""
    url = sa.make_url(f"sqlite:///{(tmp_path / 'uso-ficticio.db').as_posix()}")
    recorder = SqlUsageRecorder.from_url(url)
    engine = recorder._engine
    try:
        assert engine.url.drivername == "sqlite"
        LLM_USAGE_TABLE.metadata.create_all(engine)

        recorder.record(_record(7, 3, at=NOW))

        assert recorder.tokens_since(NOW - timedelta(minutes=1)) == 10
        assert len(_rows(engine)) == 1
    finally:
        engine.dispose()


def test_sql_recorder_round_trips_with_sql_usage_queries(engine: sa.Engine) -> None:
    """CA-6: lo que escribe SqlUsageRecorder lo lee SqlUsageQueries con los mismos valores."""
    artifact_id = uuid4()
    SqlUsageRecorder(engine).record(
        _record(
            11,
            4,
            at=NOW,
            task=TaskType.NL_TO_JQL,
            est_cost=Decimal("0.000250"),
            artifact_id=artifact_id,
        )
    )

    calls = SqlUsageQueries(engine).calls()

    assert len(calls) == 1
    call = calls[0]
    assert call.task == "nl_to_jql"
    assert (call.provider, call.model) == ("proveedor-ficticio", "modelo-ficticio")
    assert (call.input_tokens, call.output_tokens, call.total_tokens) == (11, 4, 15)
    assert call.est_cost == Decimal("0.000250")
    assert isinstance(call.est_cost, Decimal)
    assert call.latency_ms == 42
    assert call.artifact_id == artifact_id
    # SQLite no guarda la zona: la hora vuelve sin tzinfo pero con el mismo valor UTC.
    assert call.at.replace(tzinfo=UTC) == NOW


def test_sql_queries_from_url_reads_sqlite_file(tmp_path: Path) -> None:
    """CA-6: `SqlUsageQueries.from_url` lee lo que escribe `SqlUsageRecorder.from_url`."""
    url = sa.make_url(f"sqlite:///{(tmp_path / 'uso-ficticio.db').as_posix()}")
    recorder = SqlUsageRecorder.from_url(url)
    queries = SqlUsageQueries.from_url(url)
    try:
        LLM_USAGE_TABLE.metadata.create_all(recorder._engine)
        recorder.record(_record(1, 2, at=NOW))
        recorder.record(_record(3, 4, at=NOW + timedelta(hours=1)))

        calls = queries.calls()

        assert [c.total_tokens for c in calls] == [7, 3]  # de la más reciente a la más antigua
    finally:
        recorder._engine.dispose()
        queries._engine.dispose()
