"""Prueba cruzada T-35 (RNF-19): el área B prueba `adapters/auth/` del área A (T-22).

Cubre RF-45 (usuarios locales con contraseña argon2id), RF-46/RNF-05 (el rol que sale del login
alimenta `core/permissions.py`), RNF-01 (la contraseña y el hash no aparecen en logs, excepciones
ni `repr`) y lo declarado en el registro de T-22: tiempo constante con un hash ficticio aleatorio
para usuarios inexistentes, inactivos rechazados, rehash tolerante a fallos y `save_user` upsert.

Se centra en lo que no fijan `test_auth_local.py` ni `test_auth_seed.py`: la misma cantidad de
trabajo argon2 para cada causa de fallo (se cuentan verificaciones, no se miden tiempos), nombres
con mayúsculas, espacios, saltos de línea o Unicode parecido, contraseñas Unicode y en el límite
de 256 caracteres multibyte, hashes corruptos o de otros algoritmos en la BD, el rehash de otra
variante de argon2 y su fallo con errores de pool, roles desconocidos en la BD y el upsert real.

BD: SQLite en memoria con una tabla `users` equivalente (el SQL del proveedor, incluido
`ON CONFLICT … DO UPDATE`, es compatible). Así se pueden sembrar filas que PostgreSQL impediría
(rol fuera de la CHECK) para comprobar que el proveedor falla cerrado. Argon2 con parámetros
mínimos. Usuarios y contraseñas 100 % ficticios y generados en la prueba. Los defectos
confirmados van como `xfail(strict=True)` con su PA; el resto fija el comportamiento actual.
"""

import secrets
import unicodedata
from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Any

import pytest
import sqlalchemy as sa
from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import HashingError
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.pool import StaticPool
from structlog.testing import capture_logs

from adapters.auth.local import MAX_PASSWORD_CHARS, LocalAuthProvider
from adapters.base import User
from adapters.errors import AgentError, AuthenticationError, ExternalServiceError
from core.permissions import ROLE_PERMISSIONS, Permission, permissions_of, require

FAST = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}
NEWER = {"time_cost": 2, "memory_cost": 16, "parallelism": 1}
USERNAME = "qa-ficticio"

_CREATE_USERS = sa.text(
    """
    CREATE TABLE users (
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        active BOOLEAN NOT NULL DEFAULT 1
    )
    """
)
_INSERT = sa.text(
    "INSERT INTO users (username, password_hash, role, active) "
    "VALUES (:username, :hash, :role, :active)"
)


def _password(chars: int = 20) -> str:
    return secrets.token_urlsafe(chars)[:chars]


class SpyHasher(PasswordHasher):
    """PasswordHasher barato que cuenta `verify` y `hash` (medida de trabajo, no de tiempo)."""

    def __init__(self, **params: Any) -> None:
        super().__init__(**{**FAST, **params})
        self.verify_calls = 0
        self.hash_calls = 0

    def verify(self, hash: str | bytes, password: str | bytes) -> bool:
        self.verify_calls += 1
        return super().verify(hash, password)

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        self.hash_calls += 1
        return super().hash(password, salt=salt)

    def reset(self) -> None:
        self.verify_calls = self.hash_calls = 0


class ProxyEngine:
    """Envuelve el engine real: cuenta `begin()` y puede fallar en llamadas concretas."""

    def __init__(self, engine: Engine, failures: dict[int, Exception] | None = None) -> None:
        self.engine = engine
        self.failures = failures or {}
        self.begins = 0

    def begin(self) -> AbstractContextManager[Connection]:
        self.begins += 1
        if self.begins in self.failures:
            raise self.failures[self.begins]
        return self.engine.begin()


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = sa.create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with eng.begin() as conn:
        conn.execute(_CREATE_USERS)
    yield eng
    eng.dispose()


def _insert(engine: Engine, password_hash: str, role: str = "qa", active: bool = True) -> None:
    with engine.begin() as conn:
        conn.execute(
            _INSERT, {"username": USERNAME, "hash": password_hash, "role": role, "active": active}
        )


def _rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        result = conn.execute(sa.text("SELECT * FROM users ORDER BY username"))
        return [dict(row) for row in result.mappings()]


def _stored_hash(engine: Engine) -> str:
    (row,) = _rows(engine)
    return str(row["password_hash"])


def _provider(engine: Any, hasher: PasswordHasher | None = None) -> LocalAuthProvider:
    return LocalAuthProvider(engine, hasher or PasswordHasher(**FAST))


def _pool_timeout() -> sa.exc.TimeoutError:
    return sa.exc.TimeoutError("QueuePool limit reached (ficticio)")


def _db_down() -> sa.exc.OperationalError:
    return sa.exc.OperationalError("UPDATE users", {}, Exception("fallo ficticio"))


# --- Mismo resultado y mismo trabajo para cada causa de fallo ------------------------------


FAILURE_CASES = [
    "inexistente",
    "contrasena_mala",
    "inactivo_con_contrasena_buena",
    "contrasena_vacia",
    "contrasena_enorme",
    "usuario_con_formato_invalido",
]


@pytest.mark.parametrize("case", FAILURE_CASES)
def test_failed_login_returns_none_with_one_argon2_verification_for_every_cause(
    engine: Engine, case: str
) -> None:
    """RF-45 / registro T-22 (tiempo constante): inexistente, contraseña mala, inactivo, vacía,
    enorme o nombre inválido → `None` y exactamente una verificación argon2, sin `hash` extra
    ni escrituras: el atacante no distingue la causa por el trabajo realizado."""
    hasher = SpyHasher()
    password = _password()
    _insert(engine, hasher.hash(password), active=case != "inactivo_con_contrasena_buena")
    before = _stored_hash(engine)
    provider = _provider(engine, hasher)
    hasher.reset()
    username, attempt = {
        "inexistente": ("otro-ficticio", password),
        "contrasena_mala": (USERNAME, _password()),
        "inactivo_con_contrasena_buena": (USERNAME, password),
        "contrasena_vacia": (USERNAME, ""),
        "contrasena_enorme": (USERNAME, "x" * (MAX_PASSWORD_CHARS * 40)),
        "usuario_con_formato_invalido": ("QA-Ficticio", password),
    }[case]
    assert provider.authenticate(username, attempt) is None
    assert (hasher.verify_calls, hasher.hash_calls) == (1, 0)
    assert _stored_hash(engine) == before


def test_dummy_hash_has_same_argon2_parameters_as_real_hashes(engine: Engine) -> None:
    """Registro T-22 (tiempo constante): el hash ficticio usa los mismos parámetros (tipo,
    memoria, iteraciones) que el hasher, así que su verificación cuesta lo mismo."""
    hasher = PasswordHasher(**NEWER)
    provider = _provider(engine, hasher)
    assert extract_parameters(provider._dummy_hash) == extract_parameters(hasher.hash(_password()))


def test_missing_user_and_wrong_password_give_identical_result(engine: Engine) -> None:
    """RF-45 (negativo): usuario inexistente y contraseña mala devuelven el mismo valor (`None`),
    sin excepción que permita distinguirlos."""
    hasher = PasswordHasher(**FAST)
    _insert(engine, hasher.hash(_password()))
    provider = _provider(engine, hasher)
    results = {provider.authenticate(u, _password()) for u in (USERNAME, "nadie-ficticio")}
    assert results == {None}


# --- Nombres de usuario ------------------------------------------------------------------


@pytest.mark.parametrize(
    "username",
    [
        "QA-FICTICIO",  # mayúsculas: no se normaliza
        " qa-ficticio",  # espacio inicial
        "qa-ficticio ",  # espacio final
        "qa-ficticio\n",  # salto de línea final ($ en la regex)
        "qa-ficticio\x00",  # NUL
        "qа-ficticio",  # «а» cirílica parecida
        "ｑａ-ficticio",  # «ｑａ» de ancho completo
        "qa-fictício",  # acento
        None,  # la UI podría pasar None
    ],
)
def test_authenticate_rejects_lookalike_usernames_without_querying_db(
    engine: Engine, username: Any
) -> None:
    """RF-45 (negativo): variantes del nombre (mayúsculas, espacios, saltos de línea, Unicode
    parecido, None) con la contraseña CORRECTA → `None`, sin consultar la BD y con la misma
    verificación argon2 que cualquier otro fallo."""
    hasher = SpyHasher()
    password = _password()
    _insert(engine, hasher.hash(password))
    proxy = ProxyEngine(engine)
    provider = _provider(proxy, hasher)
    hasher.reset()
    assert provider.authenticate(username, password) is None
    assert proxy.begins == 0
    assert hasher.verify_calls == 1


@pytest.mark.parametrize(
    "username", ["qa-ficticio\n", "qa-ficticio\x00", "qа-ficticio", "ｑａ-ficticio"]
)
def test_save_user_rejects_lookalike_usernames_without_creating_rows(
    engine: Engine, username: str
) -> None:
    """RF-45 (negativo): `save_user` no crea usuarios con salto de línea, NUL u homoglifos."""
    with pytest.raises(ValueError, match="nombre de usuario"):
        _provider(engine).save_user(username, _password(), "qa")
    assert _rows(engine) == []


# --- Contraseñas -------------------------------------------------------------------------


def test_unicode_password_round_trips_through_save_and_login(engine: Engine) -> None:
    """RF-45: una contraseña con ñ, tildes y emoji se guarda y permite entrar."""
    provider = _provider(engine)
    password = "Contraseña-ficticia-ñandú-🔐"
    provider.save_user(USERNAME, password, "functional")
    assert provider.authenticate(USERNAME, password) == User(username=USERNAME, role="functional")


def test_password_is_not_unicode_normalized_nor_trimmed(engine: Engine) -> None:
    """RF-45 (comportamiento actual): la contraseña se compara tal cual; su forma NFD o la
    versión sin espacios exteriores no dan acceso."""
    provider = _provider(engine)
    password = unicodedata.normalize("NFC", " Clave-ficticia-ñandú ")
    provider.save_user(USERNAME, password, "qa")
    assert provider.authenticate(USERNAME, unicodedata.normalize("NFD", password)) is None
    assert provider.authenticate(USERNAME, password.strip()) is None
    assert provider.authenticate(USERNAME, password) is not None


def test_password_limit_counts_characters_not_bytes(engine: Engine) -> None:
    """RF-45 (límite): 256 caracteres multibyte (≈1 KB en UTF-8) se aceptan en el alta y el
    login; uno más se rechaza en ambos sin dar acceso."""
    provider = _provider(engine)
    password = "ñ🔐" * (MAX_PASSWORD_CHARS // 2)
    assert len(password) == MAX_PASSWORD_CHARS
    provider.save_user(USERNAME, password, "qa")
    assert provider.authenticate(USERNAME, password) is not None
    assert provider.authenticate(USERNAME, password + "ñ") is None
    with pytest.raises(ValueError, match="contraseña"):
        provider.save_user(USERNAME, password + "ñ", "qa")


def test_authenticate_returns_none_when_password_none(engine: Engine) -> None:
    """RF-45 (error): contraseña `None` (la UI podría pasarla) → `None`, sin excepción."""
    hasher = PasswordHasher(**FAST)
    _insert(engine, hasher.hash(_password()))
    assert _provider(engine, hasher).authenticate(USERNAME, None) is None  # type: ignore[arg-type]


# --- Hash corrupto o de otro algoritmo en la BD ------------------------------------------


def _corrupt_hashes(password: str) -> dict[str, str]:
    valid = PasswordHasher(**FAST).hash(password)
    return {
        "bcrypt": "$2b$12$" + "ficticio" * 7,
        "pbkdf2": "pbkdf2_sha256$1$salficticia$hashficticio",
        "vacio": "",
        "solo_prefijo": "$argon2id$",
        "argon2_truncado": valid[:-10],
        "variante_inexistente": valid.replace("$argon2id$", "$argon2xx$", 1),
        "contrasena_en_claro": password,
    }


@pytest.mark.parametrize("kind", list(_corrupt_hashes("x")))
def test_authenticate_fails_closed_when_stored_hash_corrupt_or_foreign(
    engine: Engine, kind: str
) -> None:
    """RF-45 (error) / RNF-01: hash de otro algoritmo, truncado, vacío o la contraseña en claro
    guardada en la columna → `None` sin excepción ni reescritura del hash, incluso con la
    contraseña «correcta»."""
    password = _password()
    stored = _corrupt_hashes(password)[kind]
    _insert(engine, stored)
    assert _provider(engine).authenticate(USERNAME, password) is None
    assert _stored_hash(engine) == stored


def test_argon2i_hash_logs_in_and_is_rehashed_to_argon2id(engine: Engine) -> None:
    """RF-45 / registro T-22 (rehash): un hash de otra variante (argon2i) verifica y, tras el
    acceso correcto, se sustituye en la BD por uno argon2id con los parámetros actuales."""
    password = _password()
    _insert(engine, PasswordHasher(**FAST, type=Type.I).hash(password))
    hasher = PasswordHasher(**FAST)
    assert _provider(engine, hasher).authenticate(USERNAME, password) is not None
    stored = _stored_hash(engine)
    assert stored.startswith("$argon2id$")
    assert not hasher.check_needs_rehash(stored)


# --- Rehash ------------------------------------------------------------------------------


@pytest.mark.parametrize("active", [True, False])
def test_rehash_not_performed_when_login_fails(engine: Engine, active: bool) -> None:
    """Registro T-22 (rehash): con un hash antiguo, una contraseña mala (activo) o la correcta
    de un inactivo no recalculan ni escriben el hash."""
    password = _password()
    old = PasswordHasher(**FAST).hash(password)
    _insert(engine, old, active=active)
    hasher = SpyHasher(**NEWER)
    provider = _provider(engine, hasher)
    hasher.reset()
    attempt = _password() if active else password
    assert provider.authenticate(USERNAME, attempt) is None
    assert hasher.hash_calls == 0
    assert _stored_hash(engine) == old


def test_login_succeeds_when_rehash_update_hits_database_error(engine: Engine) -> None:
    """Registro T-22 (rehash tolerante a fallos): si el UPDATE del nuevo hash falla con un error
    de la BD (DBAPIError, recorrido real por `_connection`), el login correcto sigue valiendo y
    el hash antiguo queda intacto."""
    password = _password()
    old = PasswordHasher(**FAST).hash(password)
    _insert(engine, old, role="admin")
    proxy = ProxyEngine(engine, failures={2: _db_down()})
    user = _provider(proxy, PasswordHasher(**NEWER)).authenticate(USERNAME, password)
    assert user == User(username=USERNAME, role="admin")
    assert _stored_hash(engine) == old


def test_login_succeeds_when_rehash_update_hits_pool_timeout(engine: Engine) -> None:
    """Registro T-22 (rehash tolerante a fallos): el pool agotado al guardar el nuevo hash no
    debe impedir el acceso válido."""
    password = _password()
    _insert(engine, PasswordHasher(**FAST).hash(password))
    proxy = ProxyEngine(engine, failures={2: _pool_timeout()})
    assert _provider(proxy, PasswordHasher(**NEWER)).authenticate(USERNAME, password) is not None


@pytest.mark.parametrize("operation", ["authenticate", "save_user"])
def test_pool_timeout_is_wrapped_in_external_service_error(engine: Engine, operation: str) -> None:
    """CLAUDE.md (errores externos envueltos) / RF-45: con el pool agotado, el proveedor lanza
    `ExternalServiceError` con mensaje para la UI, no la excepción de SQLAlchemy."""
    provider = _provider(ProxyEngine(engine, failures={1: _pool_timeout()}))
    with pytest.raises(ExternalServiceError, match="base de datos de usuarios"):
        if operation == "authenticate":
            provider.authenticate(USERNAME, _password())
        else:
            provider.save_user(USERNAME, _password(), "qa")


# --- Roles y permisos --------------------------------------------------------------------


@pytest.mark.parametrize("role", ["functional", "qa", "admin"])
def test_authenticated_role_drives_permissions(engine: Engine, role: str) -> None:
    """RF-46 / RNF-05: el rol devuelto por el login da exactamente los permisos de su fila de la
    matriz; un login fallido no da ninguno y `require` lo rechaza."""
    provider = _provider(engine)
    password = _password()
    provider.save_user(USERNAME, password, role)
    user = provider.authenticate(USERNAME, password)
    assert permissions_of(user) == ROLE_PERMISSIONS[role]
    failed = provider.authenticate(USERNAME, _password())
    assert permissions_of(failed) == frozenset()
    with pytest.raises(AuthenticationError):
        require(failed, Permission.VIEW_CONTEXT)


@pytest.mark.parametrize("role", ["superuser", "Admin", ""])
def test_authenticate_fails_closed_when_stored_role_unknown(engine: Engine, role: str) -> None:
    """RF-46 / RNF-05 (error): con un rol fuera de functional/qa/admin y la contraseña correcta,
    el proveedor no autentica (devuelve `None` o un error del agente), nunca una excepción
    cruda de validación."""
    hasher = PasswordHasher(**FAST)
    password = _password()
    _insert(engine, hasher.hash(password), role=role)
    try:
        result = _provider(engine, hasher).authenticate(USERNAME, password)
    except AgentError:
        return
    assert result is None


# --- save_user (upsert) ------------------------------------------------------------------


def test_save_user_upsert_updates_hash_role_and_active_in_single_row(engine: Engine) -> None:
    """Registro T-22 (`save_user` upsert): volver a guardar desactiva, cambia rol y contraseña
    sobre la misma fila; el inactivo ya no entra ni con la contraseña nueva."""
    provider = _provider(engine)
    old, new = _password(), _password()
    provider.save_user(USERNAME, old, "functional")
    assert provider.save_user(USERNAME, new, "admin", active=False) == User(
        username=USERNAME, role="admin"
    )
    (row,) = _rows(engine)
    assert (row["role"], bool(row["active"])) == ("admin", False)
    assert provider.authenticate(USERNAME, new) is None
    assert provider.authenticate(USERNAME, old) is None


def test_save_user_uses_fresh_salt_on_every_save(engine: Engine) -> None:
    """RF-45: guardar dos veces la misma contraseña produce hashes distintos (sal nueva)."""
    provider = _provider(engine)
    password = _password()
    provider.save_user(USERNAME, password, "qa")
    first = _stored_hash(engine)
    provider.save_user(USERNAME, password, "qa")
    assert _stored_hash(engine) != first
    assert provider.authenticate(USERNAME, password) is not None


@pytest.mark.parametrize(
    ("password", "role"), [("corta", "qa"), (_password(), "superuser"), (_password(), "Admin")]
)
def test_save_user_validation_error_leaves_existing_user_intact(
    engine: Engine, password: str, role: str
) -> None:
    """RF-45 (negativo): un `save_user` inválido sobre un usuario existente no toca su fila."""
    provider = _provider(engine)
    original = _password()
    provider.save_user(USERNAME, original, "functional")
    before = _rows(engine)
    with pytest.raises(ValueError):
        provider.save_user(USERNAME, password, role)
    assert _rows(engine) == before
    assert provider.authenticate(USERNAME, original) == User(username=USERNAME, role="functional")


# --- Ni la contraseña ni el hash se filtran ----------------------------------------------


def test_password_and_hash_never_appear_in_logs(engine: Engine) -> None:
    """RNF-01 / CLAUDE.md (logs): alta, login correcto con rehash, login fallido y BD caída no
    registran la contraseña, el hash guardado ni la contraseña ficticia."""
    password = "MARCADOR-CLAVE-FICTICIA-" + _password(8)
    with capture_logs() as logs:
        old_provider = _provider(engine)
        old_provider.save_user(USERNAME, password, "qa")
        old_hash = _stored_hash(engine)
        provider = _provider(engine, PasswordHasher(**NEWER))
        provider.authenticate(USERNAME, password)
        provider.authenticate(USERNAME, password + "x")
        down = _provider(ProxyEngine(engine, failures={1: _db_down()}))
        with pytest.raises(ExternalServiceError):
            down.authenticate(USERNAME, password)
    dump = repr(logs)
    for secret in (password, old_hash, _stored_hash(engine), provider._dummy_password):
        assert secret not in dump


def test_password_and_hash_never_appear_in_errors_or_repr(engine: Engine) -> None:
    """RNF-01: los errores de `save_user` y de BD, el `User` devuelto y el `repr` del proveedor
    no contienen la contraseña, el hash ni la contraseña/hash ficticios."""
    hasher = PasswordHasher(**FAST)
    password = "MARCADOR-" + _password(14)
    provider = _provider(engine, hasher)
    texts: list[str] = []
    for bad_call in (
        lambda: provider.save_user(USERNAME, "MARCADOR-11", "qa"),
        lambda: provider.save_user(USERNAME, password, "superuser"),
        lambda: provider.save_user("Usuario Malo", password, "qa"),
        lambda: _provider(ProxyEngine(engine, {1: _db_down()})).save_user(USERNAME, password, "qa"),
    ):
        with pytest.raises((ValueError, ExternalServiceError)) as info:
            bad_call()
        texts += [str(info.value), repr(info.value), repr(info.value.__context__)]
    user = provider.save_user(USERNAME, password, "qa")
    texts += [
        repr(user),
        str(user),
        repr(provider),
        repr(provider.authenticate(USERNAME, password)),
    ]
    dump = "\n".join(texts)
    for secret in (password, "MARCADOR-11", _stored_hash(engine), provider._dummy_hash):
        assert secret not in dump
    assert provider._dummy_password not in dump


# --- Integración (PostgreSQL real) -------------------------------------------------------
# Lo que necesita PostgreSQL (CHECK de roles, upsert real) ya está en `test_auth_local.py`
# marcado como `integration`; aquí no se duplica.


class _FailingRehashHasher(PasswordHasher):
    """Hasher que falla al recalcular el hash (después de crear el proveedor)."""

    fail = False

    def hash(self, password: str | bytes, *, salt: bytes | None = None) -> str:
        if self.fail:
            raise HashingError("fallo ficticio de argon2")
        return super().hash(password, salt=salt)


def test_login_succeeds_when_rehash_raises_hashing_error(engine: Engine) -> None:
    """PA-164 (rehash tolerante a fallos): un `HashingError` de argon2 al recalcular el hash no
    impide un acceso válido."""
    password = _password()
    _insert(engine, PasswordHasher(**FAST).hash(password))
    hasher = _FailingRehashHasher(**NEWER)
    provider = _provider(engine, hasher)
    hasher.fail = True
    assert provider.authenticate(USERNAME, password) is not None


def test_unknown_role_warning_has_no_username_nor_role(engine: Engine) -> None:
    """PA-196 · RNF-02: el aviso del rol desconocido no lleva el usuario ni el rol."""
    hasher = PasswordHasher(**FAST)
    password = _password()
    _insert(engine, hasher.hash(password), role="rol-ficticio-raro")
    with capture_logs() as logs:
        assert _provider(engine, hasher).authenticate(USERNAME, password) is None
    dumped = repr(logs)
    assert any(entry.get("event") == "auth_unknown_role" for entry in logs)
    assert USERNAME not in dumped and "rol-ficticio-raro" not in dumped
