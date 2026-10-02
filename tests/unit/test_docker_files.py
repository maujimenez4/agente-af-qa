"""Imagen y Compose de la API (PA-273) y Ollama con keep-alive (PA-275): pruebas estáticas.

Solo leen `Dockerfile`, `.dockerignore` y `docker-compose.yml`; nunca ejecutan `docker`, no
abren el `.env` ni usan red.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
DOCKERIGNORE = ROOT / ".dockerignore"
COMPOSE = ROOT / "docker-compose.yml"


def _instructions() -> list[tuple[str, str]]:
    """Instrucciones del Dockerfile (sin comentarios, con las líneas continuadas unidas)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    joined = re.sub(r"\\\n", " ", "\n".join(lines))
    result = []
    for line in joined.splitlines():
        if line.strip():
            keyword, _, rest = line.strip().partition(" ")
            result.append((keyword.upper(), rest.strip()))
    return result


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _ignored() -> list[str]:
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [x.strip() for x in lines if x.strip() and not x.strip().startswith("#")]


# --- Dockerfile ---------------------------------------------------------------------------------


def test_dockerfile_installs_from_lockfile_without_dev_dependencies() -> None:
    """Criterio 8: `uv sync --frozen --no-dev` (lockfile y sin dependencias de desarrollo)."""
    runs = [rest for keyword, rest in _instructions() if keyword == "RUN"]
    syncs = [r for r in runs if "uv sync" in r]
    assert syncs
    for run in syncs:
        assert "--frozen" in run and "--no-dev" in run


def test_dockerfile_runs_as_non_root_user() -> None:
    """Criterio 8: la última instrucción USER no es root."""
    users = [rest for keyword, rest in _instructions() if keyword == "USER"]
    assert users
    assert users[-1] not in {"root", "0", "0:0"}
    instructions = _instructions()
    last_user = max(i for i, (keyword, _rest) in enumerate(instructions) if keyword == "USER")
    cmd = max(i for i, (keyword, _rest) in enumerate(instructions) if keyword == "CMD")
    assert last_user < cmd


def test_dockerfile_never_copies_env_explicitly() -> None:
    """Criterio 8: ningún COPY/ADD nombra `.env`."""
    for keyword, rest in _instructions():
        if keyword in {"COPY", "ADD"}:
            assert ".env" not in rest, rest


def test_dockerfile_has_no_secret_values() -> None:
    """Criterio 8: el Dockerfile no fija contraseñas, tokens ni claves en ENV/ARG."""
    for keyword, rest in _instructions():
        if keyword in {"ENV", "ARG"}:
            assert not re.search(r"(PASSWORD|TOKEN|SECRET|API_KEY)", rest, re.IGNORECASE), rest


def test_dockerfile_cmd_starts_api_on_all_interfaces() -> None:
    """Criterio 8: CMD con `python -m api --host 0.0.0.0` (en forma exec)."""
    (cmd,) = [rest for keyword, rest in _instructions() if keyword == "CMD"]
    args = yaml.safe_load(cmd)  # forma exec: lista JSON
    assert isinstance(args, list)
    assert args[:3] == ["python", "-m", "api"]
    assert args[args.index("--host") + 1] == "0.0.0.0"  # noqa: S104 (dentro del contenedor)


# --- .dockerignore -----------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", [".env", ".env.*"])
def test_dockerignore_excludes_env_files(pattern: str) -> None:
    """Criterio 8: `.env` y `.env.*` fuera del contexto de la imagen."""
    assert pattern in _ignored()


def test_dockerignore_does_not_reinclude_env() -> None:
    """Criterio 8 (negativa): ninguna excepción `!` vuelve a meter un `.env`."""
    assert not [x for x in _ignored() if x.startswith("!") and ".env" in x]


# --- docker-compose.yml ------------------------------------------------------------------------


def test_compose_app_is_published_only_on_localhost(compose: dict[str, Any]) -> None:
    """Criterio 8: la app se publica solo en `127.0.0.1:8000:8000`."""
    assert compose["services"]["app"]["ports"] == ["127.0.0.1:8000:8000"]


def test_compose_app_reads_env_file_at_runtime(compose: dict[str, Any]) -> None:
    """Criterio 8: `env_file: .env` en la app (los secretos llegan al arrancar)."""
    env_file = compose["services"]["app"]["env_file"]
    assert env_file == ".env" or env_file == [".env"]


def test_compose_app_database_url_uses_db_service_and_password_variable(
    compose: dict[str, Any],
) -> None:
    """Criterio 8: DATABASE_URL apunta a `@db:5432` y la contraseña es `${POSTGRES_PASSWORD}`."""
    url = compose["services"]["app"]["environment"]["DATABASE_URL"]
    assert "@db:5432/" in url
    assert ":${POSTGRES_PASSWORD}@" in url
    password = re.search(r"//[^:]+:([^@]+)@", url)
    assert password is not None and password.group(1) == "${POSTGRES_PASSWORD}"
    assert "localhost" not in url


def test_compose_has_no_literal_passwords(compose: dict[str, Any]) -> None:
    """Criterio 8: toda contraseña del Compose viene de una variable, nunca escrita."""
    for name, service in compose["services"].items():
        environment = service.get("environment") or {}
        for key, value in environment.items():
            if "PASSWORD" in key or "SECRET" in key or "TOKEN" in key:
                assert re.fullmatch(r"\$\{\w+(:-[^}]*)?\}", str(value)), (name, key)


def test_compose_app_ollama_base_url_uses_ollama_service(compose: dict[str, Any]) -> None:
    """Criterio 8: OLLAMA_BASE_URL es `http://ollama:11434/v1` (no localhost)."""
    environment = compose["services"]["app"]["environment"]
    assert environment["OLLAMA_BASE_URL"] == "http://ollama:11434/v1"


def test_compose_app_waits_for_healthy_db_and_is_optional(compose: dict[str, Any]) -> None:
    """Criterio 8: la app va en el perfil `full` y espera a la BD sana."""
    app = compose["services"]["app"]
    assert app["profiles"] == ["full"]
    assert app["depends_on"]["db"]["condition"] == "service_healthy"


def test_compose_ollama_has_keep_alive(compose: dict[str, Any]) -> None:
    """Criterio 8 (PA-275): el servicio ollama define OLLAMA_KEEP_ALIVE."""
    environment = compose["services"]["ollama"]["environment"]
    assert "OLLAMA_KEEP_ALIVE" in environment
    assert str(environment["OLLAMA_KEEP_ALIVE"]).strip()
