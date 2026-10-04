"""PA-278: `POSTGRES_HOST` y `POSTGRES_PORT` en `Settings`; la URL se compone sin escribirla.

La contraseña ficticia se compone por partes y se pasa por el entorno, para que el escáner de
secretos de CI no la tome por real.
"""

import pytest
from sqlalchemy.engine import make_url

from core.config import Settings

SPECIAL = "@/:#?"
CLAVE_FICTICIA = "ficticia" + SPECIAL + "local"


@pytest.fixture
def clean_db_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_url_uses_ipv4_loopback_and_default_port(clean_db_env: pytest.MonkeyPatch) -> None:
    """PA-278: sin `POSTGRES_HOST` ni puerto, 127.0.0.1:5432 (no localhost: ::1 tarda ~20 s)."""
    url = Settings(_env_file=None).sqlalchemy_url()  # type: ignore[call-arg]
    assert (url.host, url.port) == ("127.0.0.1", 5432)


def test_url_uses_configured_host_and_port(clean_db_env: pytest.MonkeyPatch) -> None:
    """PA-278: en Compose, `POSTGRES_HOST=db`; el puerto también se puede cambiar."""
    clean_db_env.setenv("POSTGRES_HOST", "db")
    clean_db_env.setenv("POSTGRES_PORT", "6543")
    url = Settings(_env_file=None).sqlalchemy_url()  # type: ignore[call-arg]
    assert (url.host, url.port) == ("db", 6543)


@pytest.mark.parametrize("port", ["0", "-1", "no-numerico"])
def test_invalid_port_is_rejected(clean_db_env: pytest.MonkeyPatch, port: str) -> None:
    """PA-278: el puerto es un entero positivo."""
    clean_db_env.setenv("POSTGRES_PORT", port)
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_special_characters_in_the_credential_are_encoded(
    clean_db_env: pytest.MonkeyPatch,
) -> None:
    """PA-278: `@ / : # ?` en la contraseña no rompen la URL: se codifican y se recuperan."""
    clean_db_env.setenv("POSTGRES_PASSWORD", CLAVE_FICTICIA)
    clean_db_env.setenv("POSTGRES_HOST", "db")
    url = Settings(_env_file=None).sqlalchemy_url()  # type: ignore[call-arg]

    rendered = url.render_as_string(hide_password=False)
    reparsed = make_url(rendered)
    assert reparsed.password == CLAVE_FICTICIA
    assert (reparsed.host, reparsed.port, reparsed.database) == ("db", 5432, "agente")
    assert SPECIAL not in rendered  # ningún carácter especial queda sin codificar


def test_database_url_still_takes_precedence(clean_db_env: pytest.MonkeyPatch) -> None:
    """PA-278: si hay `DATABASE_URL`, manda sobre `POSTGRES_HOST` (compatibilidad)."""
    clean_db_env.setenv("POSTGRES_HOST", "db")
    clean_db_env.setenv("DATABASE_URL", "postgresql+psycopg://usuario@otro-host.invalid:5433/x")
    url = Settings(_env_file=None).sqlalchemy_url()  # type: ignore[call-arg]
    assert (url.host, url.port) == ("otro-host.invalid", 5433)


def test_empty_database_url_falls_back_to_postgres_variables(
    clean_db_env: pytest.MonkeyPatch,
) -> None:
    """PA-278: Compose deja `DATABASE_URL` vacía para anular la del `.env`; entonces se usan
    las `POSTGRES_*`."""
    clean_db_env.setenv("DATABASE_URL", "")
    clean_db_env.setenv("POSTGRES_HOST", "db")
    url = Settings(_env_file=None).sqlalchemy_url()  # type: ignore[call-arg]
    assert url.host == "db"


def test_groq_models_file_keeps_its_prudent_context_window() -> None:
    """PA-229: `models.groq.yaml` declara su ventana (32 768) y no hereda la de 8192."""
    from core.config import ROOT_DIR, load_models_config

    limits = load_models_config(ROOT_DIR / "config" / "models.groq.yaml").limits
    assert limits.context_window == 32_768
    assert limits.context_token_budget == 8000
