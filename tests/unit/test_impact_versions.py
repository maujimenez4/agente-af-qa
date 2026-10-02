"""Pruebas de `StoryVersionStore` (T-19 · RF-05, RF-19, RNF-16).

Las unitarias no abren conexión real: el engine apunta a un puerto cerrado.
Las de integración crean una BD temporal `<db>_versions_test`, aplican `alembic upgrade head`
y se saltan si PostgreSQL no está disponible (docker compose up -d db).
Datos 100 % sintéticos (Villaficticia, DEMO-N).
"""

import io
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, Engine

from adapters.errors import ExternalServiceError, NotFoundError
from core.config import ROOT_DIR, Settings
from core.impact.diff import diff_stories
from core.impact.versions import StoryVersionStore, VersionConflictError
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, Priority
from schemas.test_case import TestSuite
from schemas.user_story import BusinessRule, UserStory
from tests.fakes.dataset import renewal_story
from tests.fakes.llm import renewal_test_suite

UNUSED_URL = "postgresql+psycopg://x@127.0.0.1:1/x"
AUTHOR = "qa-ficticio"


def _unused_store() -> StoryVersionStore:
    # connect_timeout: en algunos equipos el firewall descarta (no rechaza) el puerto cerrado.
    engine = sa.create_engine(
        UNUSED_URL, poolclass=sa.pool.NullPool, connect_args={"connect_timeout": 1}
    )
    return StoryVersionStore(engine)


def _story_artifact(
    artifact_id: UUID,
    version: int,
    content: UserStory,
    *,
    status: ArtifactStatus = ArtifactStatus.IN_REVIEW,
    prompt_version: str | None = "hu_nueva@1",
) -> Artifact:
    return Artifact(
        id=artifact_id,
        type=ArtifactType.USER_STORY,
        status=status,
        version=version,
        origin_key="DEMO-3",
        content=content,
        created_by=AUTHOR,
        model_used="modelo-ficticio",
        prompt_version=prompt_version,
    )


def _suite_artifact(artifact_id: UUID, version: int, content: TestSuite) -> Artifact:
    return Artifact(
        id=artifact_id,
        type=ArtifactType.TEST_SUITE,
        status=ArtifactStatus.DRAFT,
        version=version,
        origin_key="DEMO-3",
        content=content,
        created_by=AUTHOR,
    )


def _evolved_story() -> UserStory:
    base = renewal_story()
    return base.model_copy(
        update={
            "title": "Renovar un préstamo en Villaficticia",
            "priority": Priority.SHOULD,
            "business_rules": [
                BusinessRule(id="RN-01", description="Máximo 3 renovaciones por préstamo."),
                base.business_rules[1],
            ],
            "changes_from_previous": ["Se amplía el máximo de renovaciones (ficticio)."],
        },
        deep=True,
    )


# --- Unitarias sin BD ----------------------------------------------------------------


def test_version_conflict_error_is_external_service_error() -> None:
    """RF-05: VersionConflictError es un ExternalServiceError (la UI lo trata igual)."""
    assert issubclass(VersionConflictError, ExternalServiceError)
    error = VersionConflictError("Conflicto ficticio.", service="postgres")
    assert error.service == "postgres"


def test_save_raises_spanish_error_without_cause_when_db_unreachable() -> None:
    """RF-05 / CLAUDE.md: error de BD envuelto en ExternalServiceError en español, sin causa."""
    artifact = _story_artifact(uuid4(), 1, renewal_story())
    with pytest.raises(ExternalServiceError) as info:
        _unused_store().save(artifact)
    assert type(info.value) is ExternalServiceError
    assert "base de datos" in str(info.value)
    assert info.value.service == "postgres"
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True


def test_versions_raises_spanish_error_without_cause_when_db_unreachable() -> None:
    """RF-05: `versions` sin BD → ExternalServiceError en español, sin encadenar la causa."""
    with pytest.raises(ExternalServiceError) as info:
        _unused_store().versions(uuid4())
    assert "base de datos" in str(info.value)
    assert info.value.__cause__ is None


def test_get_raises_spanish_error_without_cause_when_db_unreachable() -> None:
    """RF-05: `get` sin BD → ExternalServiceError (no NotFoundError), sin causa."""
    with pytest.raises(ExternalServiceError) as info:
        _unused_store().get(uuid4(), 1)
    assert not isinstance(info.value, NotFoundError)
    assert "base de datos" in str(info.value)
    assert info.value.__cause__ is None


def test_error_message_does_not_leak_connection_url() -> None:
    """RNF (seguridad): el mensaje no incluye la URL, el host ni el usuario de conexión."""
    with pytest.raises(ExternalServiceError) as info:
        _unused_store().versions(uuid4())
    message = str(info.value)
    assert "127.0.0.1" not in message
    assert "postgresql" not in message


# --- Integración con BD temporal -------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    """BD temporal migrada; nunca toca la base de datos configurada."""
    server_url: URL = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_versions_test"
    admin = sa.create_engine(
        server_url,
        poolclass=sa.pool.NullPool,
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 3},
    )
    try:
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
            conn.execute(sa.text(f'CREATE DATABASE "{test_db}"'))
    except sa.exc.OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL no disponible (docker compose up -d db)")
    url = server_url.set(database=test_db)
    config = Config(str(ROOT_DIR / "alembic.ini"), stdout=io.StringIO())
    config.attributes["database_url"] = url
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool, connect_args={"connect_timeout": 3})
    try:
        command.upgrade(config, "head")
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{test_db}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def engine(pg_engine: Engine) -> Engine:
    with pg_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE artifacts CASCADE"))
    return pg_engine


@pytest.fixture
def store(engine: Engine) -> StoryVersionStore:
    return StoryVersionStore(engine)


def _artifact_row(engine: Engine, artifact_id: UUID) -> sa.Row:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(
                "SELECT type, status, version, origin_key, jira_key, created_by, prompt_version "
                "FROM artifacts WHERE id = :id"
            ),
            {"id": artifact_id},
        ).one()


def _count_versions(engine: Engine, artifact_id: UUID) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM artifact_versions WHERE artifact_id = :id"),
            {"id": artifact_id},
        ).scalar_one()


@pytest.mark.integration
def test_save_two_versions_lists_them_in_order(store: StoryVersionStore) -> None:
    """RF-05: guardar v1 y v2 de una HU → versions == [1, 2]."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    store.save(_story_artifact(artifact_id, 2, _evolved_story()))
    assert store.versions(artifact_id) == [1, 2]


@pytest.mark.integration
def test_get_returns_each_user_story_version(store: StoryVersionStore) -> None:
    """RF-05: `get` devuelve la UserStory exacta de cada versión."""
    artifact_id = uuid4()
    v1, v2 = renewal_story(), _evolved_story()
    store.save(_story_artifact(artifact_id, 1, v1))
    store.save(_story_artifact(artifact_id, 2, v2))
    got1, got2 = store.get(artifact_id, 1), store.get(artifact_id, 2)
    assert isinstance(got1, UserStory) and isinstance(got2, UserStory)
    assert got1 == v1
    assert got2 == v2


@pytest.mark.integration
def test_latest_returns_highest_version(store: StoryVersionStore) -> None:
    """RF-05: `latest` devuelve la última versión guardada."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    store.save(_story_artifact(artifact_id, 2, _evolved_story()))
    assert store.latest(artifact_id) == _evolved_story()


@pytest.mark.integration
def test_diff_between_versions_matches_diff_stories(store: StoryVersionStore) -> None:
    """RF-19: diff(id, 1, 2) es igual a diff_stories sobre las HU originales."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    store.save(_story_artifact(artifact_id, 2, _evolved_story()))
    expected = diff_stories(renewal_story(), _evolved_story())
    assert expected
    assert store.diff(artifact_id, 1, 2) == expected


@pytest.mark.integration
def test_artifact_row_reflects_latest_saved_version(
    engine: Engine, store: StoryVersionStore
) -> None:
    """RF-05: la fila de `artifacts` refleja la última versión, su estado y prompt_version."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story(), prompt_version="hu_nueva@1"))
    store.save(
        _story_artifact(
            artifact_id,
            2,
            _evolved_story(),
            status=ArtifactStatus.APPROVED,
            prompt_version="hu_evolucion@2",
        )
    )
    row = _artifact_row(engine, artifact_id)
    assert row.type == "user_story"
    assert row.version == 2
    assert row.status == "approved"
    assert row.prompt_version == "hu_evolucion@2"
    assert row.origin_key == "DEMO-3"
    assert row.jira_key == "DEMO-3"
    assert row.created_by == AUTHOR


@pytest.mark.integration
def test_save_is_idempotent_when_same_version_and_content(
    engine: Engine, store: StoryVersionStore
) -> None:
    """RF-05 / RNF-16: guardar dos veces la misma versión con igual contenido no falla."""
    artifact_id = uuid4()
    artifact = _story_artifact(artifact_id, 1, renewal_story())
    store.save(artifact)
    store.save(artifact)
    assert store.versions(artifact_id) == [1]
    assert _count_versions(engine, artifact_id) == 1
    assert store.get(artifact_id, 1) == renewal_story()


@pytest.mark.integration
def test_save_raises_conflict_when_same_version_different_content(
    store: StoryVersionStore,
) -> None:
    """RF-05 (negativo): misma versión con otro contenido → VersionConflictError en español."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    with pytest.raises(VersionConflictError) as info:
        store.save(_story_artifact(artifact_id, 1, _evolved_story()))
    assert "versión 1" in str(info.value)
    assert info.value.service == "postgres"


@pytest.mark.integration
def test_conflict_leaves_original_version_and_row_untouched(
    engine: Engine, store: StoryVersionStore
) -> None:
    """RF-05: tras un conflicto, la versión y la fila de `artifacts` no cambian (rollback)."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story(), prompt_version="hu_nueva@1"))
    with pytest.raises(VersionConflictError):
        store.save(
            _story_artifact(
                artifact_id,
                1,
                _evolved_story(),
                status=ArtifactStatus.APPROVED,
                prompt_version="hu_evolucion@9",
            )
        )
    assert store.get(artifact_id, 1) == renewal_story()
    row = _artifact_row(engine, artifact_id)
    assert row.status == "in_review"
    assert row.prompt_version == "hu_nueva@1"


@pytest.mark.integration
def test_resaving_older_version_keeps_artifact_row_on_latest(
    engine: Engine, store: StoryVersionStore
) -> None:
    """RF-05 (límite): re-guardar idénticamente v1 tras v2 no hace retroceder la fila a v1."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    store.save(_story_artifact(artifact_id, 2, _evolved_story()))
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    assert store.versions(artifact_id) == [1, 2]
    assert _artifact_row(engine, artifact_id).version == 2


@pytest.mark.integration
def test_get_raises_not_found_when_version_missing(store: StoryVersionStore) -> None:
    """RF-05 (negativo): versión inexistente de un artefacto existente → NotFoundError."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    with pytest.raises(NotFoundError, match="versión 7"):
        store.get(artifact_id, 7)


@pytest.mark.integration
def test_get_raises_not_found_when_artifact_missing(store: StoryVersionStore) -> None:
    """RF-05 (negativo): artefacto inexistente → NotFoundError."""
    with pytest.raises(NotFoundError):
        store.get(uuid4(), 1)


@pytest.mark.integration
def test_versions_returns_empty_when_artifact_missing(store: StoryVersionStore) -> None:
    """RF-05 (límite): artefacto sin versiones → lista vacía."""
    assert store.versions(uuid4()) == []


@pytest.mark.integration
def test_latest_raises_not_found_when_artifact_missing(store: StoryVersionStore) -> None:
    """RF-05 (negativo): `latest` de un artefacto sin versiones → NotFoundError."""
    with pytest.raises(NotFoundError):
        store.latest(uuid4())


@pytest.mark.integration
def test_diff_raises_not_found_when_version_missing(store: StoryVersionStore) -> None:
    """RF-19 (negativo): diff con una versión inexistente → NotFoundError."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    with pytest.raises(NotFoundError):
        store.diff(artifact_id, 1, 2)


@pytest.mark.integration
def test_get_returns_test_suite_when_saved_suite(engine: Engine, store: StoryVersionStore) -> None:
    """RF-05: una TestSuite guardada se recupera como TestSuite."""
    artifact_id = uuid4()
    suite = renewal_test_suite("DEMO-3")
    store.save(_suite_artifact(artifact_id, 1, suite))
    got = store.get(artifact_id, 1)
    assert isinstance(got, TestSuite)
    assert got == suite
    assert _artifact_row(engine, artifact_id).type == "test_suite"


@pytest.mark.integration
def test_diff_raises_not_found_when_artifact_is_test_suite(store: StoryVersionStore) -> None:
    """RF-19 (negativo): el diff por campo solo existe para HU; con TestSuite → NotFoundError."""
    artifact_id = uuid4()
    store.save(_suite_artifact(artifact_id, 1, renewal_test_suite("DEMO-3")))
    store.save(_suite_artifact(artifact_id, 2, renewal_test_suite("DEMO-4")))
    with pytest.raises(NotFoundError, match="HU"):
        store.diff(artifact_id, 1, 2)


@pytest.mark.integration
def test_versions_are_isolated_per_artifact(store: StoryVersionStore) -> None:
    """RF-05: las versiones de un artefacto no se mezclan con las de otro."""
    first, second = uuid4(), uuid4()
    store.save(_story_artifact(first, 1, renewal_story()))
    store.save(_story_artifact(first, 2, _evolved_story()))
    store.save(_story_artifact(second, 1, renewal_story(jira_key="DEMO-4")))
    assert store.versions(first) == [1, 2]
    assert store.versions(second) == [1]


@pytest.mark.integration
def test_published_by_agent_only_for_published_user_stories(store: StoryVersionStore) -> None:
    """PA-104: «Publicada por el agente» solo si una HU con esa clave consta como publicada."""
    artifact_id = uuid4()
    store.save(_story_artifact(artifact_id, 1, renewal_story()))
    key = f"PAQ{artifact_id.hex[:6].upper()}-1"  # clave ficticia y única por ejecución
    assert store.published_by_agent(key) is False
    store.update_status(artifact_id, "approved", key)
    assert store.published_by_agent(key) is False
    store.update_status(artifact_id, "published", key)
    assert store.published_by_agent(key) is True
