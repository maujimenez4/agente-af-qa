"""Pruebas de `adapters/auth/seed.py` (T-22 · RF-45, RF-46, RNF-05).

Sin BD: se usa un proveedor espía. Las contraseñas generadas nunca aparecen en los asserts.
"""

import string
from pathlib import Path
from typing import Any

import pytest

import adapters.auth.seed as seed
from adapters.auth.local import MAX_PASSWORD_CHARS, MIN_PASSWORD_CHARS
from adapters.auth.seed import DEMO_USERS, PASSWORD_CHARS, generate_password, seed_demo_users

ALPHANUMERIC = set(string.ascii_letters + string.digits)


class SpyAuth:
    """Registra las llamadas a save_user sin tocar ninguna BD."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str]] = []

    def save_user(self, username: str, password: str, role: str, active: bool = True) -> Any:
        self.saved.append((username, password, role))


def test_generate_password_has_default_length() -> None:
    """RNF-05: la contraseña generada tiene 16 caracteres."""
    assert PASSWORD_CHARS == 16
    assert len(generate_password()) == 16


def test_generate_password_only_alphanumeric() -> None:
    """RNF-05: solo letras ASCII y dígitos."""
    assert set(generate_password()) <= ALPHANUMERIC


def test_generate_password_differs_between_calls() -> None:
    """RNF-05: dos llamadas producen contraseñas distintas."""
    different = generate_password() != generate_password()
    assert different, "dos llamadas devolvieron la misma contraseña"


def test_generate_password_respects_custom_length() -> None:
    """RNF-05 (límite): longitud personalizada."""
    assert len(generate_password(MIN_PASSWORD_CHARS)) == MIN_PASSWORD_CHARS


def test_seed_creates_exactly_three_demo_users_with_roles() -> None:
    """RF-45 / RF-46: af-demo, qa-demo y admin-demo con sus roles."""
    auth = SpyAuth()
    created = seed_demo_users(auth)  # type: ignore[arg-type]
    expected = [("af-demo", "functional"), ("qa-demo", "qa"), ("admin-demo", "admin")]
    assert list(DEMO_USERS) == expected
    assert [(u, r) for u, _, r in auth.saved] == expected
    assert [(u, r) for u, r, _ in created] == expected


def test_seed_passwords_are_distinct_and_valid() -> None:
    """RNF-05: contraseñas distintas y dentro de la longitud permitida; lo devuelto coincide
    con lo guardado."""
    auth = SpyAuth()
    created = seed_demo_users(auth)  # type: ignore[arg-type]
    passwords = [p for _, p, _ in auth.saved]
    distinct = len(set(passwords)) == 3
    valid = all(MIN_PASSWORD_CHARS <= len(p) <= MAX_PASSWORD_CHARS for p in passwords)
    returned = [p for _, _, p in created] == passwords
    assert distinct, "las contraseñas de demo se repiten"
    assert valid, "alguna contraseña de demo no cumple la longitud"
    assert returned, "lo devuelto no coincide con lo guardado"


def test_seed_generates_new_passwords_each_run() -> None:
    """RNF-05: volver a ejecutarlo genera contraseñas nuevas."""
    first, second = SpyAuth(), SpyAuth()
    seed_demo_users(first)  # type: ignore[arg-type]
    seed_demo_users(second)  # type: ignore[arg-type]
    fresh = {p for _, p, _ in first.saved}.isdisjoint({p for _, p, _ in second.saved})
    assert fresh, "se repiten contraseñas entre ejecuciones"


class FakeSettings:
    def sqlalchemy_url(self) -> str:
        return "postgresql+psycopg://usuario_ficticio@localhost:1/bd_ficticia"


def test_main_prints_warning_once_and_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """RNF-05: main avisa de que no se volverán a mostrar, lista los 3 usuarios y devuelve 0."""
    import core.factories
    from core import seed_users

    spy = SpyAuth()
    monkeypatch.setattr(core.config, "build_config", lambda: object())
    monkeypatch.setattr(core.factories, "build_auth", lambda _config: spy)
    assert seed_users.main() == 0
    out = capsys.readouterr().out
    assert out.count("no se volverán a mostrar") == 1
    for username, _, role in spy.saved:
        assert username in out and f"rol={role}" in out
    shown = all(password in out for _, password, _ in spy.saved)
    assert shown, "main no muestra las contraseñas generadas"
    assert "localhost" not in out


def test_seed_module_in_adapters_does_not_import_core() -> None:
    """SPEC-00 §2: `adapters/` nunca importa de `core/`."""
    source = (Path(seed.__file__)).read_text(encoding="utf-8")
    assert "from core" not in source and "import core" not in source
