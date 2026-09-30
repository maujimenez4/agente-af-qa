"""AuthProvider con usuarios locales en PostgreSQL y contraseñas con argon2 (RF-45, D-05).

- Tiempo constante: si el usuario no existe se verifica igualmente contra un hash ficticio, para
  no revelar qué usuarios existen.
- Los usuarios inactivos no pueden entrar.
- Si los parámetros de argon2 cambian, el hash se recalcula en el siguiente acceso correcto.
"""

import re
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, cast, get_args

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.engine import Connection, Engine

from adapters.base import User
from adapters.errors import ExternalServiceError

SERVICE = "postgres"
Role = Literal["functional", "qa", "admin"]
ROLES: tuple[str, ...] = get_args(Role)
USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,49}$")
MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_CHARS = 256  # evita hashes costosos con entradas enormes

_SELECT_USER = sa.text(
    "SELECT username, password_hash, role, active FROM users WHERE username = :username"
)
_UPDATE_HASH = sa.text("UPDATE users SET password_hash = :hash WHERE username = :username")
_UPSERT_USER = sa.text(
    """
    INSERT INTO users (username, password_hash, role, active)
    VALUES (:username, :hash, :role, :active)
    ON CONFLICT (username) DO UPDATE SET
        password_hash = EXCLUDED.password_hash, role = EXCLUDED.role, active = EXCLUDED.active
    """
)


class LocalAuthProvider:
    """Implementa `AuthProvider`."""

    def __init__(self, engine: Engine, hasher: PasswordHasher | None = None) -> None:
        self._engine = engine
        self._hasher = hasher or PasswordHasher()
        # Hash de una contraseña aleatoria: iguala el tiempo cuando el usuario no existe.
        self._dummy_password = secrets.token_urlsafe(24)
        self._dummy_hash = self._hasher.hash(self._dummy_password)

    @classmethod
    def from_url(cls, url: sa.URL | str) -> "LocalAuthProvider":
        return cls(sa.create_engine(url, pool_pre_ping=True))

    def authenticate(self, username: str, password: str) -> User | None:
        password = password or ""  # la UI podría pasar None
        acceptable = 0 < len(password) <= MAX_PASSWORD_CHARS
        candidate = password if acceptable else self._dummy_password
        row = self._find(username) if USERNAME_RE.fullmatch(username or "") else None
        stored_hash = row["password_hash"] if row else self._dummy_hash
        verified = self._verify(stored_hash, candidate)
        if row is None or not verified or not acceptable or not row["active"]:
            return None
        if self._hasher.check_needs_rehash(stored_hash):
            try:
                with self._connection() as conn:
                    conn.execute(
                        _UPDATE_HASH,
                        {"hash": self._hasher.hash(password), "username": row["username"]},
                    )
            except ExternalServiceError:
                pass  # el acceso es válido; el hash se recalculará en el próximo login
        return User(username=row["username"], role=cast(Role, row["role"]))

    def save_user(self, username: str, password: str, role: str, active: bool = True) -> User:
        """Crea el usuario o, si ya existe, actualiza su contraseña, rol y estado."""
        if not USERNAME_RE.fullmatch(username):
            raise ValueError(
                "El nombre de usuario debe tener entre 3 y 50 caracteres: minúsculas, números, "
                "punto, guion o guion bajo."
            )
        if role not in ROLES:
            raise ValueError(f"Rol no válido: {role!r}. Roles: {', '.join(ROLES)}.")
        if not MIN_PASSWORD_CHARS <= len(password) <= MAX_PASSWORD_CHARS:
            raise ValueError(
                f"La contraseña debe tener entre {MIN_PASSWORD_CHARS} y {MAX_PASSWORD_CHARS} "
                "caracteres."
            )
        with self._connection() as conn:
            conn.execute(
                _UPSERT_USER,
                {
                    "username": username,
                    "hash": self._hasher.hash(password),
                    "role": role,
                    "active": active,
                },
            )
        return User(username=username, role=cast(Role, role))

    # --- internos ---------------------------------------------------------------------------

    def _verify(self, stored_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def _find(self, username: str) -> dict | None:
        with self._connection() as conn:
            row = conn.execute(_SELECT_USER, {"username": username}).mappings().first()
        return dict(row) if row else None

    @contextmanager
    def _connection(self) -> Iterator[Connection]:
        try:
            with self._engine.begin() as conn:
                yield conn
        except sa.exc.DBAPIError:
            raise ExternalServiceError(
                "No se pudo acceder a la base de datos de usuarios.", service=SERVICE
            ) from None
