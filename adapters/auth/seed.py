"""Usuarios sintéticos de demo, uno por rol (T-22): generación y alta.

La CLI está en `core/seed_users.py` (`uv run python -m core.seed_users`).

Las contraseñas se generan al azar y se muestran UNA sola vez en la consola: no se guardan en el
repositorio, en `.env` ni en los logs. Volver a ejecutarlo genera contraseñas nuevas.
"""

import secrets
import string

from adapters.auth.local import LocalAuthProvider

DEMO_USERS: tuple[tuple[str, str], ...] = (
    ("af-demo", "functional"),
    ("qa-demo", "qa"),
    ("admin-demo", "admin"),
)
PASSWORD_CHARS = 16
_ALPHABET = string.ascii_letters + string.digits


def generate_password(length: int = PASSWORD_CHARS) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def seed_demo_users(auth: LocalAuthProvider) -> list[tuple[str, str, str]]:
    """Guarda los usuarios de demo y devuelve (usuario, rol, contraseña en claro)."""
    created = []
    for username, role in DEMO_USERS:
        password = generate_password()
        auth.save_user(username, password, role)
        created.append((username, role, password))
    return created
