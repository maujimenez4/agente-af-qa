"""Pruebas de `LocalAuthProvider` (T-22 · RF-45, RNF-05, D-05).

Las unitarias no abren conexión: el engine apunta a un puerto cerrado y `_find`/`_connection`
se sustituyen con monkeypatch cuando hace falta. Las de integración crean una BD temporal
`<db>_auth_test`, aplican `alembic upgrade head` y se saltan si PostgreSQL no está disponible.

Todas las contraseñas se generan en la prueba (`secrets`); nunca se muestran en los asserts.
"""

import io
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy.engine import URL, Engine

import adapters.auth.local as local_module
from adapters.auth.local import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS, LocalAuthProvider
from adapters.auth.seed import DEMO_USERS, seed_demo_users
from adapters.base import AuthProvider, User
from adapters.errors import ExternalServiceError
from core.config import ROOT_DIR, Settings

UNUSED_URL = "postgresql+psycopg://usuario_ficticio@localhost:1/bd_ficticia"


def _unused_engine(**connect_args: Any) -> Engine:
    return sa.create_engine(UNUSED_URL, poolclass=sa.pool.NullPool, connect_args=connect_args)


def _fast_hasher() -> PasswordHasher:
    """Parámetros bajos para que las unitarias sean rápidas."""
    return PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def _password(chars: int = 20) -> str:
    """Contraseña aleatoria de exactamente `chars` caracteres."""
    return secrets.token_urlsafe(chars)[:chars]


class SpyHasher(PasswordHasher):
    """PasswordHasher que registra las llamadas a `verify` y `hash`."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**{"time_cost": 1, "memory_cost": 8, "parallelism": 1, **kwargs})
        self.verify_calls: list[str] = []
        self.hash_calls = 0

    def verify(self, hash: str | bytes, password: str | bytes) -> bool:
        self.verify_calls.append(str(hash))
        return super().verify(hash, password)

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        self.hash_calls += 1
        return super().hash(password, salt=salt)


class RecordingConnection:
    def __init__(self) -> None:
        self.executed: list[dict[str, Any]] = []

    def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.executed.append(params)


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch, provider: LocalAuthProvider
) -> RecordingConnection:
    conn = RecordingConnection()

    @contextmanager
    def fake_connection() -> Iterator[RecordingConnection]:
        yield conn

    monkeypatch.setattr(provider, "_connection", fake_connection)
    return conn


def _provider(hasher: PasswordHasher | None = None) -> LocalAuthProvider:
    return LocalAuthProvider(_unused_engine(), hasher or _fast_hasher())


# --- Unitarias sin BD --------------------------------------------------------------------


def test_implements_auth_provider_protocol_when_built() -> None:
    """RF-45: cumple el protocolo AuthProvider."""
    assert isinstance(_provider(), AuthProvider)


def test_from_url_builds_provider_without_connecting() -> None:
    """RF-45: `from_url` construye el proveedor sin abrir conexión."""
    assert isinstance(LocalAuthProvider.from_url(UNUSED_URL), LocalAuthProvider)


@pytest.mark.parametrize(
    "username",
    [
        "Usuario-Ficticio",  # mayúsculas
        "usuario ficticio",  # espacio
        " usuario-ficticio",  # espacio inicial
        "ab",  # muy corto
        "a" * 51,  # muy largo
        "usuario@ficticio",  # carácter no permitido
        "usuario/ficticio",
        "usuário",  # no ASCII
        "-usuario",  # empieza por guion
        "",
    ],
)
def test_save_user_rejects_invalid_username_without_touching_db(username: str) -> None:
    """RF-45 (negativo): usuario con formato inválido → ValueError antes de conectar."""
    provider = _provider()
    with pytest.raises(ValueError, match="nombre de usuario"):
        provider.save_user(username, _password(), "qa")


@pytest.mark.parametrize("username", ["abc", "a" * 50, "qa-demo", "usuario.ficticio_01"])
def test_save_user_accepts_username_at_limits(
    monkeypatch: pytest.MonkeyPatch, username: str
) -> None:
    """RF-45 (límite): 3 y 50 caracteres, punto, guion y guion bajo son válidos."""
    provider = _provider()
    conn = _patch_connection(monkeypatch, provider)
    assert provider.save_user(username, _password(), "qa") == User(username=username, role="qa")
    assert conn.executed[0]["username"] == username


@pytest.mark.parametrize("role", ["superuser", "Admin", "", "tester"])
def test_save_user_rejects_invalid_role_without_touching_db(role: str) -> None:
    """RF-46 (negativo): rol fuera de functional/qa/admin → ValueError."""
    with pytest.raises(ValueError, match="Rol no válido"):
        _provider().save_user("usuario-ficticio", _password(), role)


@pytest.mark.parametrize("chars", [0, MIN_PASSWORD_CHARS - 1, MAX_PASSWORD_CHARS + 1])
def test_save_user_rejects_password_length_out_of_range(chars: int) -> None:
    """RNF-05 (límite): contraseñas de 11 y 257 caracteres → ValueError sin tocar la BD."""
    with pytest.raises(ValueError, match="contraseña"):
        _provider().save_user("usuario-ficticio", "x" * chars, "functional")


@pytest.mark.parametrize("chars", [MIN_PASSWORD_CHARS, MAX_PASSWORD_CHARS])
def test_save_user_accepts_password_length_limits_until_db(chars: int) -> None:
    """RNF-05 (límite): 12 y 256 caracteres pasan la validación y llegan a la BD (caída)."""
    provider = LocalAuthProvider(_unused_engine(connect_timeout=2), _fast_hasher())
    with pytest.raises(ExternalServiceError):
        provider.save_user("usuario-ficticio", _password(chars), "functional")


def test_save_user_stores_argon2_hash_not_plain_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-45 / RNF-05: se envía a la BD un hash argon2id, nunca la contraseña en claro."""
    provider = _provider()
    conn = _patch_connection(monkeypatch, provider)
    password = _password()
    provider.save_user("usuario-ficticio", password, "admin", active=False)
    params = conn.executed[0]
    assert params["hash"].startswith("$argon2id$")
    leaked = password in params["hash"] or password in params.values()
    assert not leaked, "la contraseña en claro llega a la BD"
    assert (params["role"], params["active"]) == ("admin", False)


def _forbid_find(monkeypatch: pytest.MonkeyPatch, provider: LocalAuthProvider) -> None:
    def fail(username: str) -> None:
        raise AssertionError("no debería consultar la BD")

    monkeypatch.setattr(provider, "_find", fail)


@pytest.mark.parametrize(
    "username", ["Usuario", "usuario ficticio", "ab", "a" * 51, "usuario@x", ""]
)
def test_authenticate_returns_none_when_username_format_invalid(
    monkeypatch: pytest.MonkeyPatch, username: str
) -> None:
    """RF-45 (negativo): usuario con formato inválido → None sin consultar la BD,
    pero con una verificación argon2 (tiempo constante)."""
    hasher = SpyHasher()
    provider = _provider(hasher)
    _forbid_find(monkeypatch, provider)
    assert provider.authenticate(username, _password()) is None
    assert len(hasher.verify_calls) == 1


@pytest.mark.parametrize("password", ["", "x" * (MAX_PASSWORD_CHARS + 1)])
def test_authenticate_returns_none_when_password_empty_or_too_long(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    """RNF-05 (límite): contraseña vacía o > 256 → None aunque el usuario exista."""
    hasher = SpyHasher()
    provider = _provider(hasher)
    stored = {
        "username": "usuario-ficticio",
        "password_hash": hasher.hash(password or "x"),
        "role": "qa",
        "active": True,
    }
    monkeypatch.setattr(provider, "_find", lambda username: stored)
    assert provider.authenticate("usuario-ficticio", password) is None
    assert len(hasher.verify_calls) == 1


def test_authenticate_verifies_dummy_hash_when_user_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RF-45 / RNF-05: usuario inexistente → se verifica igualmente contra el hash ficticio."""
    hasher = SpyHasher()
    provider = _provider(hasher)
    monkeypatch.setattr(provider, "_find", lambda username: None)
    assert provider.authenticate("usuario-inexistente", _password()) is None
    assert hasher.verify_calls == [provider._dummy_hash]


def test_authenticate_does_not_accept_dummy_password_when_user_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RF-45 (negativo): ni siquiera la contraseña ficticia da acceso a un usuario inexistente."""
    provider = _provider()
    monkeypatch.setattr(provider, "_find", lambda username: None)
    assert provider.authenticate("usuario-inexistente", provider._dummy_password) is None


def test_dummy_hash_is_random_per_instance_and_not_in_source() -> None:
    """RNF-05: el hash ficticio es distinto en cada instancia y no es un valor del código."""
    first, second = _provider(), _provider()
    assert first._dummy_hash != second._dummy_hash
    assert first._dummy_password != second._dummy_password
    assert first._dummy_hash.startswith("$argon2id$")
    assert first._hasher.verify(first._dummy_hash, first._dummy_password)
    source = Path(local_module.__file__).read_text(encoding="utf-8")
    in_source = first._dummy_password in source
    assert not in_source, "la contraseña ficticia aparece en el código"
    assert "$argon2" not in source


def _stored_row(hasher: PasswordHasher, password: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "username": "usuario-ficticio",
        "password_hash": hasher.hash(password),
        "role": "functional",
        "active": True,
    }
    row.update(overrides)
    return row


def test_authenticate_returns_user_when_password_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-45: contraseña correcta → User con su rol; sin rehash si los parámetros no cambian."""
    hasher = _fast_hasher()
    provider = _provider(hasher)
    password = _password()
    monkeypatch.setattr(provider, "_find", lambda username: _stored_row(hasher, password))
    conn = _patch_connection(monkeypatch, provider)
    assert provider.authenticate("usuario-ficticio", password) == User(
        username="usuario-ficticio", role="functional"
    )
    assert conn.executed == []


def test_authenticate_returns_none_when_password_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-45 (negativo): contraseña incorrecta → None."""
    hasher = _fast_hasher()
    provider = _provider(hasher)
    monkeypatch.setattr(provider, "_find", lambda username: _stored_row(hasher, _password()))
    assert provider.authenticate("usuario-ficticio", _password()) is None


def test_authenticate_returns_none_when_user_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    """RF-45 (negativo): usuario inactivo con contraseña correcta → None."""
    hasher = _fast_hasher()
    provider = _provider(hasher)
    password = _password()
    row = _stored_row(hasher, password, active=False)
    monkeypatch.setattr(provider, "_find", lambda username: row)
    assert provider.authenticate("usuario-ficticio", password) is None


def test_authenticate_returns_none_when_stored_hash_corrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RF-45 (error): hash almacenado no válido → None, sin excepción."""
    provider = _provider()
    row = {"username": "usuario-ficticio", "password_hash": "no-es-un-hash", "role": "qa"}
    monkeypatch.setattr(provider, "_find", lambda username: {**row, "active": True})
    assert provider.authenticate("usuario-ficticio", _password()) is None


def test_authenticate_rehashes_when_parameters_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """RNF-05: hash con parámetros antiguos → se recalcula y se guarda tras un acceso correcto."""
    old_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    new_hasher = PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)
    provider = _provider(new_hasher)
    password = _password()
    monkeypatch.setattr(provider, "_find", lambda username: _stored_row(old_hasher, password))
    conn = _patch_connection(monkeypatch, provider)
    assert provider.authenticate("usuario-ficticio", password) is not None
    (params,) = conn.executed
    assert params["username"] == "usuario-ficticio"
    assert not new_hasher.check_needs_rehash(params["hash"])
    assert new_hasher.verify(params["hash"], password)


def test_raises_external_error_without_url_when_database_down() -> None:
    """CA-00-03 / RF-45: BD inaccesible → ExternalServiceError sin URL ni credenciales
    en el mensaje y sin excepción encadenada."""
    provider = LocalAuthProvider(_unused_engine(connect_timeout=2), _fast_hasher())
    for operation in (
        lambda: provider.authenticate("usuario-ficticio", _password()),
        lambda: provider.save_user("usuario-ficticio", _password(), "qa"),
    ):
        with pytest.raises(ExternalServiceError) as info:
            operation()
        message = str(info.value)
        for leaked in ("localhost", "postgresql", "psycopg", "usuario_ficticio", "bd_ficticia"):
            assert leaked not in message
        assert info.value.service == "postgres"
        assert info.value.__cause__ is None
        assert info.value.__suppress_context__ is True


# --- Integración ---------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine() -> Iterator[Engine]:
    """BD temporal migrada; nunca toca la base de datos configurada."""
    server_url: URL = Settings().sqlalchemy_url()
    test_db = f"{server_url.database}_auth_test"
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
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
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
        conn.execute(sa.text("TRUNCATE users CASCADE"))
    return pg_engine


@pytest.fixture
def auth(engine: Engine) -> LocalAuthProvider:
    return LocalAuthProvider(engine, _fast_hasher())


_SELECT_HASH = sa.text("SELECT password_hash FROM users WHERE username = :username")


def _stored_hash(engine: Engine, username: str) -> str:
    with engine.connect() as conn:
        return str(conn.execute(_SELECT_HASH, {"username": username}).scalar_one())


@pytest.mark.integration
def test_save_and_authenticate_returns_user_with_role(auth: LocalAuthProvider) -> None:
    """RF-45 / RF-46: alta + login correcto → User con su rol."""
    password = _password()
    assert auth.save_user("qa-ficticio", password, "qa") == User(username="qa-ficticio", role="qa")
    assert auth.authenticate("qa-ficticio", password) == User(username="qa-ficticio", role="qa")


@pytest.mark.integration
def test_authenticate_returns_none_when_password_wrong_in_db(auth: LocalAuthProvider) -> None:
    """RF-45 (negativo): contraseña incorrecta → None."""
    auth.save_user("af-ficticio", _password(), "functional")
    assert auth.authenticate("af-ficticio", _password()) is None


@pytest.mark.integration
def test_authenticate_returns_none_when_user_missing_in_db(auth: LocalAuthProvider) -> None:
    """RF-45 (negativo): usuario inexistente → None."""
    assert auth.authenticate("usuario-inexistente", _password()) is None


@pytest.mark.integration
def test_authenticate_returns_none_when_user_inactive_in_db(auth: LocalAuthProvider) -> None:
    """RF-45 (negativo): usuario inactivo → None aunque la contraseña sea correcta."""
    password = _password()
    auth.save_user("inactivo-ficticio", password, "qa", active=False)
    assert auth.authenticate("inactivo-ficticio", password) is None


@pytest.mark.integration
def test_stored_hash_is_argon2id_without_plain_password(
    engine: Engine, auth: LocalAuthProvider
) -> None:
    """RNF-05: el hash guardado empieza por $argon2id$ y no contiene la contraseña."""
    password = _password()
    auth.save_user("admin-ficticio", password, "admin")
    stored = _stored_hash(engine, "admin-ficticio")
    assert stored.startswith("$argon2id$")
    leaked = password in stored
    assert not leaked, "el hash contiene la contraseña en claro"


@pytest.mark.integration
def test_save_user_updates_existing_password_and_role(
    engine: Engine, auth: LocalAuthProvider
) -> None:
    """RF-45: save_user sobre un usuario existente actualiza contraseña y rol (upsert)."""
    old, new = _password(), _password()
    auth.save_user("cambio-ficticio", old, "functional")
    auth.save_user("cambio-ficticio", new, "qa")
    assert auth.authenticate("cambio-ficticio", old) is None
    assert auth.authenticate("cambio-ficticio", new) == User(username="cambio-ficticio", role="qa")
    with engine.connect() as conn:
        count = conn.execute(sa.text("SELECT count(*) FROM users")).scalar_one()
    assert count == 1


@pytest.mark.integration
def test_save_user_reactivates_user_when_active_true(auth: LocalAuthProvider) -> None:
    """RF-45: el upsert también actualiza el estado activo."""
    password = _password()
    auth.save_user("reactivo-ficticio", password, "qa", active=False)
    auth.save_user("reactivo-ficticio", password, "qa", active=True)
    assert auth.authenticate("reactivo-ficticio", password) is not None


@pytest.mark.integration
def test_authenticate_rehashes_in_db_when_parameters_changed(engine: Engine) -> None:
    """RNF-05: guardado con parámetros bajos → el login con parámetros por defecto
    actualiza el hash en BD."""
    password = _password()
    LocalAuthProvider(engine, _fast_hasher()).save_user("rehash-ficticio", password, "admin")
    before = _stored_hash(engine, "rehash-ficticio")
    default = LocalAuthProvider(engine)
    assert default.authenticate("rehash-ficticio", password) is not None
    after = _stored_hash(engine, "rehash-ficticio")
    assert after != before
    assert PasswordHasher().check_needs_rehash(before)
    assert not PasswordHasher().check_needs_rehash(after)
    assert default.authenticate("rehash-ficticio", password) is not None


@pytest.mark.integration
def test_database_role_check_constraint_still_enforced(engine: Engine) -> None:
    """RF-46: la CHECK ck_users_role rechaza roles fuera de la lista aunque se salte la app."""
    with pytest.raises(sa.exc.IntegrityError, match="ck_users_role"), engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (username, password_hash, role) "
                "VALUES ('rol-ficticio', 'hash-ficticio', 'superuser')"
            )
        )


@pytest.mark.integration
def test_seed_demo_users_creates_three_users_that_authenticate(auth: LocalAuthProvider) -> None:
    """RF-45 / RF-46: el seed crea af-demo, qa-demo y admin-demo; cada uno entra con su clave."""
    created = seed_demo_users(auth)
    assert [(u, r) for u, r, _ in created] == list(DEMO_USERS)
    for username, role, password in created:
        assert auth.authenticate(username, password) == User(username=username, role=role)


def test_authenticate_returns_user_when_rehash_update_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revisión de seguridad de T-22: si falla guardar el nuevo hash, el acceso válido no se cae."""
    import secrets
    from contextlib import contextmanager

    from argon2 import PasswordHasher

    from adapters.auth.local import LocalAuthProvider
    from adapters.errors import ExternalServiceError

    password = secrets.token_urlsafe(16)
    weak_hash = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(password)
    provider = LocalAuthProvider(sa.create_engine("postgresql+psycopg://x@localhost:1/x"))
    row = {"username": "af-demo", "password_hash": weak_hash, "role": "functional", "active": True}
    monkeypatch.setattr(provider, "_find", lambda _username: row)

    @contextmanager
    def failing_connection():  # type: ignore[no-untyped-def]
        raise ExternalServiceError("fallo ficticio")
        yield

    monkeypatch.setattr(provider, "_connection", failing_connection)
    user = provider.authenticate("af-demo", password)
    assert user is not None and user.role == "functional"
