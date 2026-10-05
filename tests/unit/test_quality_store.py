"""Revisiones de calidad guardadas (PA-272, PA-103): `InMemoryQualityReviewStore` y
`SqlQualityReviewStore`.

Las pruebas sin red usan motores de mentira (BD caída, filas dañadas, sentencias grabadas); las
de PostgreSQL llevan `@pytest.mark.integration`, usan una BD temporal (`tests/pg_temp.py`) y se
saltan sin servidor. Datos 100 % ficticios.
"""

from collections.abc import Iterator
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from adapters.errors import ExternalServiceError
from core.quality import (
    INTERRUPTED,
    MAX_REVIEWS_PER_PERSON,
    InMemoryQualityReviewStore,
    QualityReview,
    SqlQualityReviewStore,
    StoredQualityReview,
    evolve_feedback_of,
    new_review,
)
from schemas.quality import QualityReport
from tests.fakes import dataset
from tests.fakes.llm import renewal_quality_report
from tests.pg_temp import temporary_database

ANA = "ana-ficticia"
BEA = "bea-ficticia"
FAKE_PASSWORD = "clave-ficticia-no-real"
BASE = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def _result(report: QualityReport | None = None) -> QualityReview:
    return QualityReview(
        jira_key="DEMO-3",
        report=report or renewal_quality_report(),
        story=dataset.renewal_story(),
        provider="ollama",
        model="modelo-ficticio",
        prompt_version="9.9",
        input_tokens=120,
        output_tokens=45,
    )


def _review(username: str = ANA, key: str = "DEMO-3", minutes: int = 0) -> StoredQualityReview:
    at = BASE + timedelta(minutes=minutes)
    return StoredQualityReview(
        id=str(uuid4()), username=username, issue_key=key, created_at=at, updated_at=at
    )


# --- StoredQualityReview y new_review ---------------------------------------------------------


def test_new_review_starts_running_in_utc_with_same_timestamps() -> None:
    """Criterio 1: una revisión nueva está en marcha, sin informe ni error y con fechas UTC."""
    review = new_review("id-ficticio", ANA, "DEMO-3")

    assert review.state == "running"
    assert review.report is None and review.error_code is None and review.error_message is None
    assert review.created_at == review.updated_at
    assert review.created_at.tzinfo is not None
    assert (review.input_tokens, review.output_tokens) == (0, 0)


def test_stored_review_title_and_project_only_show_flow_and_key() -> None:
    """Criterio 1/4: el título es solo el flujo y la clave; el proyecto sale de la clave."""
    review = replace(_review(key="DEMO-3"), report=renewal_quality_report(), state="done")

    assert review.title == "Revisar la calidad de DEMO-3"
    assert review.project_key == "DEMO"
    assert renewal_quality_report().summary not in review.title


def test_stored_review_evolve_feedback_empty_without_report() -> None:
    """Criterio 1: sin informe no hay feedback; con informe, una línea por hallazgo."""
    assert _review().evolve_feedback() == []
    done = replace(_review(), state="done", report=renewal_quality_report())
    assert done.evolve_feedback() == evolve_feedback_of(renewal_quality_report())
    assert done.evolve_feedback()[0].startswith("CA-02: ")


# --- InMemoryQualityReviewStore ----------------------------------------------------------------


def test_in_memory_create_and_get_roundtrip() -> None:
    """Criterio 1: create guarda la revisión en marcha y get la devuelve; inexistente → None."""
    store = InMemoryQualityReviewStore()
    review = _review()

    store.create(review)

    assert store.get(review.id) == review
    assert store.get(str(uuid4())) is None
    assert store.get("no-es-un-uuid") is None


def test_in_memory_finish_stores_report_model_and_tokens() -> None:
    """Criterio 1: finish → done con informe, proveedor/modelo, versión y tokens."""
    store = InMemoryQualityReviewStore()
    review = _review()
    store.create(review)

    store.finish(review.id, _result())

    done = store.get(review.id)
    assert done is not None
    assert done.state == "done"
    assert done.report == renewal_quality_report()
    assert done.model == "ollama/modelo-ficticio"
    assert done.prompt_version == "9.9"
    assert (done.input_tokens, done.output_tokens) == (120, 45)
    assert done.error_code is None
    assert done.updated_at > review.updated_at
    assert done.created_at == review.created_at


def test_in_memory_fail_stores_error_in_common_shape() -> None:
    """Criterio 1: fail → error con código, mensaje y retry_after; sin informe."""
    store = InMemoryQualityReviewStore()
    review = _review()
    store.create(review)

    store.fail(review.id, "rate_limited", "Límite ficticio alcanzado.", 30.0)

    failed = store.get(review.id)
    assert failed is not None
    assert failed.state == "error"
    assert (failed.error_code, failed.error_message, failed.retry_after) == (
        "rate_limited",
        "Límite ficticio alcanzado.",
        30.0,
    )
    assert failed.report is None
    assert failed.updated_at > review.updated_at


def test_in_memory_finish_or_fail_of_unknown_id_is_ignored() -> None:
    """Criterio 1 (límite): terminar o fallar una revisión que ya no existe no crea filas."""
    store = InMemoryQualityReviewStore()

    store.finish(str(uuid4()), _result())
    store.fail(str(uuid4()), "operation_failed", "Error ficticio.")

    assert store.rows == {}


def test_in_memory_list_for_orders_by_updated_at_desc_and_filters_person() -> None:
    """Criterio 1: list_for solo da las de la persona, de la más reciente a la más antigua."""
    store = InMemoryQualityReviewStore()
    old, middle, new = _review(minutes=0), _review(minutes=5), _review(minutes=10)
    other = _review(BEA, minutes=20)
    for review in (middle, other, new, old):
        store.create(review)

    assert [r.id for r in store.list_for(ANA)] == [new.id, middle.id, old.id]
    assert [r.id for r in store.list_for(BEA)] == [other.id]
    assert store.list_for("nadie-ficticio") == []


def test_in_memory_list_for_uses_updated_at_not_created_at() -> None:
    """Criterio 1: la revisión terminada después sube al principio de la lista."""
    store = InMemoryQualityReviewStore()
    first, second = _review(minutes=0), _review(minutes=5)
    store.create(first)
    store.create(second)

    store.finish(first.id, _result())  # updated_at = ahora, posterior a BASE + 5 min

    assert [r.id for r in store.list_for(ANA)] == [first.id, second.id]


def test_in_memory_list_for_respects_limit() -> None:
    """Criterio 1 (límite): `limit` recorta la lista a las más recientes."""
    store = InMemoryQualityReviewStore()
    reviews = [_review(minutes=m) for m in range(5)]
    for review in reviews:
        store.create(review)

    assert [r.id for r in store.list_for(ANA, limit=2)] == [reviews[4].id, reviews[3].id]
    assert len(store.list_for(ANA)) == 5


def test_in_memory_caps_reviews_per_person_in_insertion_order() -> None:
    """Criterio 1: tope de MAX_REVIEWS_PER_PERSON por persona; salen las primeras insertadas,
    aunque tengan la misma marca de tiempo, y las de otra persona no se tocan."""
    assert MAX_REVIEWS_PER_PERSON == 20
    store = InMemoryQualityReviewStore()
    other = [_review(BEA) for _ in range(3)]
    for review in other[:2]:
        store.create(review)
    mine = [_review(ANA) for _ in range(MAX_REVIEWS_PER_PERSON + 4)]  # misma marca de tiempo
    for review in mine:
        store.create(review)
    store.create(other[2])

    kept = [rid for rid, r in store.rows.items() if r.username == ANA]
    assert kept == [r.id for r in mine[-MAX_REVIEWS_PER_PERSON:]]
    assert [rid for rid, r in store.rows.items() if r.username == BEA] == [r.id for r in other]
    assert store.get(mine[0].id) is None
    assert len(store.list_for(ANA)) == MAX_REVIEWS_PER_PERSON


def test_in_memory_cap_is_exact_at_the_limit() -> None:
    """Criterio 1 (límite): con exactamente MAX_REVIEWS_PER_PERSON no se borra ninguna."""
    store = InMemoryQualityReviewStore()
    mine = [_review() for _ in range(MAX_REVIEWS_PER_PERSON)]
    for review in mine:
        store.create(review)

    assert list(store.rows) == [r.id for r in mine]


def test_in_memory_interrupt_running_marks_only_running_as_error() -> None:
    """Criterio 1: interrupt_running pasa running → error con INTERRUPTED; done y error igual."""
    store = InMemoryQualityReviewStore()
    running_a, running_b, done, failed = _review(), _review(BEA), _review(), _review()
    for review in (running_a, running_b, done, failed):
        store.create(review)
    store.finish(done.id, _result())
    store.fail(failed.id, "rate_limited", "Límite ficticio.", 5.0)
    before_done, before_failed = store.get(done.id), store.get(failed.id)

    assert store.interrupt_running() == 2

    for rid in (running_a.id, running_b.id):
        row = store.get(rid)
        assert row is not None
        assert (row.state, row.error_code, row.error_message) == (
            "error",
            "operation_failed",
            INTERRUPTED,
        )
        assert row.retry_after is None
    assert store.get(done.id) == before_done
    assert store.get(failed.id) == before_failed
    assert store.interrupt_running() == 0


def test_interrupted_message_is_spanish_and_actionable() -> None:
    """Criterio 1: el mensaje de la interrupción está en español y dice qué hacer."""
    assert "reiniciar el servidor" in INTERRUPTED
    assert "vuelve a lanzarla" in INTERRUPTED


# --- SqlQualityReviewStore sin red -------------------------------------------------------------


def _db_error() -> sa.exc.OperationalError:
    return sa.exc.OperationalError(
        "SELECT * FROM quality_reviews", {}, Exception(f"conexión rechazada {FAKE_PASSWORD}")
    )


class BrokenEngine:
    """Engine que falla al abrir la conexión o la transacción, como una BD caída (sin red)."""

    def begin(self) -> Any:
        raise _db_error()

    def connect(self) -> Any:
        raise _db_error()


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda s: s.create(_review()), "No se pudo guardar la revisión de calidad."),
        (lambda s: s.finish(str(uuid4()), _result()), "No se pudo guardar la revisión de calidad."),
        (
            lambda s: s.fail(str(uuid4()), "operation_failed", "Error ficticio."),
            "No se pudo guardar la revisión de calidad.",
        ),
        (lambda s: s.get(str(uuid4())), "No se pudieron leer las revisiones de calidad."),
        (lambda s: s.list_for(ANA), "No se pudieron leer las revisiones de calidad."),
        (
            lambda s: s.interrupt_running(),
            "No se pudieron revisar las revisiones de calidad en marcha.",
        ),
    ],
    ids=["create", "finish", "fail", "get", "list_for", "interrupt_running"],
)
def test_sql_store_wraps_database_errors_without_details(call: Any, message: str) -> None:
    """Criterio 2 (error): BD caída → ExternalServiceError en español, sin SQL ni secretos."""
    store = SqlQualityReviewStore(BrokenEngine())  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        call(store)

    assert str(exc_info.value) == message
    assert exc_info.value.service == "postgres"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True
    assert FAKE_PASSWORD not in str(exc_info.value)
    assert "quality_reviews" not in str(exc_info.value)


def test_sql_store_with_unreachable_url_wraps_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterio 2 (error): `from_url` con un motor que no conecta → ExternalServiceError."""

    def broken_create_engine(*_a: Any, **_k: Any) -> BrokenEngine:
        return BrokenEngine()

    monkeypatch.setattr(sa, "create_engine", broken_create_engine)
    url = sa.URL.create("postgresql+psycopg", username="ficticio", host="db-ficticia", database="x")
    store = SqlQualityReviewStore.from_url(url)

    with pytest.raises(ExternalServiceError) as exc_info:
        store.list_for(ANA)

    assert "ficticio" not in str(exc_info.value)
    assert "db-ficticia" not in str(exc_info.value)


def test_sql_store_get_of_non_uuid_id_is_none_without_query() -> None:
    """Criterio 2: get de un id que no es UUID → None sin tocar la BD."""
    store = SqlQualityReviewStore(BrokenEngine())  # type: ignore[arg-type]

    assert store.get("no-es-un-uuid") is None
    assert store.get("") is None
    assert store.get("0123456789abcdef" * 2 + "zz") is None


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> "_Rows":
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _RowsConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def execute(self, _statement: Any) -> _Rows:
        return _Rows(self._rows)


class RowsEngine:
    """Engine de lectura que devuelve las filas dadas (para filas dañadas o de SQLite)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def connect(self) -> Any:
        return nullcontext(_RowsConnection(self._rows))


def _row(**update: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": uuid4(),
        "username": ANA,
        "issue_key": "DEMO-3",
        "project_key": "DEMO",
        "state": "done",
        "report": renewal_quality_report().model_dump(mode="json"),
        "model": "ollama/modelo-ficticio",
        "prompt_version": "9.9",
        "input_tokens": 1,
        "output_tokens": 2,
        "error_code": None,
        "error_message": None,
        "retry_after": None,
        "created_at": BASE,
        "updated_at": BASE,
    }
    return row | update


def test_sql_store_reads_row_and_validates_report() -> None:
    """Criterio 2: la fila se convierte en StoredQualityReview con el informe validado."""
    row = _row()
    store = SqlQualityReviewStore(RowsEngine([row]))  # type: ignore[arg-type]

    (review,) = store.list_for(ANA)

    assert review.id == str(row["id"])
    assert review.report == renewal_quality_report()
    assert review.state == "done"
    assert review.project_key == "DEMO"


def test_sql_store_naive_timestamps_are_read_as_utc() -> None:
    """Criterio 2: fechas sin zona (SQLite) se leen en UTC."""
    naive = datetime(2026, 10, 1, 9, 0)
    store = SqlQualityReviewStore(RowsEngine([_row(created_at=naive, updated_at=naive)]))  # type: ignore[arg-type]

    (review,) = store.list_for(ANA)

    assert review.created_at == naive.replace(tzinfo=UTC)
    assert review.updated_at.tzinfo is UTC


@pytest.mark.parametrize(
    "damage",
    [
        {"report": {"summary": "Informe ficticio sin INVEST"}},
        {"report": {"texto": "basura-ficticia"}},
        {"report": ["basura-ficticia"]},
    ],
    ids=["report-incomplete", "report-garbage", "report-not-object"],
)
def test_sql_store_damaged_row_fails_closed(damage: dict[str, Any]) -> None:
    """Criterio 2 (error): fila dañada → ExternalServiceError sin mostrar su contenido."""
    store = SqlQualityReviewStore(RowsEngine([_row(**damage)]))  # type: ignore[arg-type]

    with pytest.raises(ExternalServiceError) as exc_info:
        store.get(str(uuid4()))

    assert str(exc_info.value) == "Una revisión de calidad guardada no es válida."
    assert "basura-ficticia" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


class _Result:
    returns_rows = False
    rowcount = 0


class _RecordingConnection:
    def __init__(self, statements: list[Any]) -> None:
        self._statements = statements

    def execute(self, statement: Any) -> _Result:
        self._statements.append(statement)
        return _Result()


class RecordingEngine:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def begin(self) -> Any:
        return nullcontext(_RecordingConnection(self.statements))


def _sql(statement: Any) -> str:
    return " ".join(str(statement.compile(dialect=postgresql.dialect())).split())


def test_sql_store_create_inserts_and_trims_per_person_in_one_transaction() -> None:
    """Criterio 2: create inserta y borra las antiguas de esa persona (las 20 más recientes)."""
    engine = RecordingEngine()

    SqlQualityReviewStore(engine).create(_review())  # type: ignore[arg-type]

    insert, delete = engine.statements
    assert _sql(insert).startswith("INSERT INTO quality_reviews")
    sql = _sql(delete)
    assert sql.startswith("DELETE FROM quality_reviews WHERE quality_reviews.username =")
    assert "NOT IN (SELECT quality_reviews.id" in sql
    assert "ORDER BY quality_reviews.created_at DESC" in sql
    params = delete.compile().params
    assert MAX_REVIEWS_PER_PERSON in params.values()
    assert list(params.values()).count(ANA) == 2  # el borrado y la subconsulta, de la persona


def test_sql_store_interrupt_running_updates_only_running() -> None:
    """Criterio 2: interrupt_running es un UPDATE condicionado a state='running'."""
    engine = RecordingEngine()

    assert SqlQualityReviewStore(engine).interrupt_running() == 0  # type: ignore[arg-type]

    (statement,) = engine.statements
    sql = _sql(statement)
    assert sql.startswith("UPDATE quality_reviews SET")
    assert "WHERE quality_reviews.state = " in sql
    params = statement.compile().params
    assert params["state_1"] == "running"
    assert params["state"] == "error"
    assert params["error_message"] == INTERRUPTED


def test_sql_store_finish_writes_report_as_json() -> None:
    """Criterio 2: finish guarda el informe como JSON (no el objeto) y estado done."""
    engine = RecordingEngine()

    SqlQualityReviewStore(engine).finish(str(uuid4()), _result())  # type: ignore[arg-type]

    (statement,) = engine.statements
    params = statement.compile().params
    assert params["state"] == "done"
    assert params["report"] == renewal_quality_report().model_dump(mode="json")
    assert params["model"] == "ollama/modelo-ficticio"


# --- SqlQualityReviewStore contra PostgreSQL ---------------------------------------------------


@pytest.fixture
def sql_store() -> Iterator[tuple[SqlQualityReviewStore, sa.Engine]]:
    with temporary_database("quality_reviews_test") as (_url, engine):
        yield SqlQualityReviewStore(engine), engine


@pytest.mark.integration
def test_sql_store_roundtrips_report_and_error(
    sql_store: tuple[SqlQualityReviewStore, sa.Engine],
) -> None:
    """Criterio 2 (PostgreSQL): ida y vuelta del QualityReport y del error en la forma común."""
    store, _engine = sql_store
    done, failed = new_review(str(uuid4()), ANA, "DEMO-3"), new_review(str(uuid4()), ANA, "DEMO-2")
    store.create(done)
    store.create(failed)
    running = store.get(done.id)
    assert running is not None and running.state == "running" and running.report is None

    store.finish(done.id, _result())
    store.fail(failed.id, "rate_limited", "Límite ficticio.", 12.5)

    finished = store.get(done.id)
    assert finished is not None
    assert finished.state == "done"
    assert finished.report == renewal_quality_report()
    assert finished.model == "ollama/modelo-ficticio"
    assert (finished.input_tokens, finished.output_tokens) == (120, 45)
    assert finished.updated_at >= finished.created_at
    err = store.get(failed.id)
    assert err is not None
    assert (err.state, err.error_code, err.error_message, err.retry_after) == (
        "error",
        "rate_limited",
        "Límite ficticio.",
        12.5,
    )
    assert store.list_for(ANA)[0].id == failed.id
    assert store.get(str(uuid4())) is None
    assert store.get("no-es-un-uuid") is None


@pytest.mark.integration
def test_sql_store_caps_reviews_per_person(
    sql_store: tuple[SqlQualityReviewStore, sa.Engine],
) -> None:
    """Criterio 2 (PostgreSQL): cada persona conserva sus 20 más recientes; la otra, intacta."""
    store, _engine = sql_store
    other = _review(BEA, minutes=0)
    store.create(other)
    mine = [_review(ANA, minutes=m) for m in range(MAX_REVIEWS_PER_PERSON + 3)]
    for review in mine:
        store.create(review)

    kept = {r.id for r in store.list_for(ANA, limit=MAX_REVIEWS_PER_PERSON)}
    assert kept == {r.id for r in mine[-MAX_REVIEWS_PER_PERSON:]}
    assert store.get(mine[0].id) is None
    assert [r.id for r in store.list_for(BEA)] == [other.id]
    assert [r.id for r in store.list_for(ANA, limit=2)] == [mine[-1].id, mine[-2].id]


@pytest.mark.integration
def test_sql_store_interrupt_running_against_postgres(
    sql_store: tuple[SqlQualityReviewStore, sa.Engine],
) -> None:
    """Criterio 2 (PostgreSQL): solo las que estaban en marcha pasan a error."""
    store, _engine = sql_store
    running, done = _review(), _review(BEA)
    store.create(running)
    store.create(done)
    store.finish(done.id, _result())

    assert store.interrupt_running() == 1

    row = store.get(running.id)
    assert row is not None
    assert (row.state, row.error_code, row.error_message) == (
        "error",
        "operation_failed",
        INTERRUPTED,
    )
    assert store.get(done.id).state == "done"  # type: ignore[union-attr]
    assert store.interrupt_running() == 0


@pytest.mark.integration
def test_sql_store_damaged_report_in_postgres_fails_closed(
    sql_store: tuple[SqlQualityReviewStore, sa.Engine],
) -> None:
    """Criterio 2 (PostgreSQL, error): informe guardado que no valida → ExternalServiceError."""
    store, engine = sql_store
    review = _review()
    store.create(review)
    store.finish(review.id, _result())
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE quality_reviews SET report = CAST(:r AS JSONB)"),
            {"r": '{"texto": "basura-ficticia"}'},
        )

    with pytest.raises(ExternalServiceError) as exc_info:
        store.get(review.id)

    assert "basura-ficticia" not in str(exc_info.value)


@pytest.mark.parametrize("method", ["finish", "fail"])
def test_sql_store_update_with_non_uuid_id_raises_spanish_error(method: str) -> None:
    """Un id que no es uuid no existe: error en español, no un ValueError suelto."""
    from types import SimpleNamespace

    store = SqlQualityReviewStore(BrokenEngine())  # type: ignore[arg-type]
    result = SimpleNamespace(
        report=renewal_quality_report(),
        provider="fake",
        model="fake-model",
        prompt_version="1",
        input_tokens=1,
        output_tokens=1,
    )

    with pytest.raises(ExternalServiceError, match="No se pudo guardar"):
        if method == "finish":
            store.finish("no-es-un-uuid", result)  # type: ignore[arg-type]
        else:
            store.fail("no-es-un-uuid", "unexpected", "Fallo ficticio.")
