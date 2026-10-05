"""Arranca el servidor MCP de solo lectura por stdio: `uv run python -m mcp_server` (T-59).

stdout es el canal del protocolo: los logs y los avisos van siempre a stderr. Sin `MCP_USER`
configurado, no arranca. Las credenciales se quedan en el `.env` del servidor.
"""

import logging
import sys

from pydantic import ValidationError

from adapters.base import User
from adapters.errors import AgentError
from core.config import ConfigError, build_config
from core.factories import build_app_container
from core.logging import configure_logging
from mcp_server.server import build_server

NO_USER = (
    "Falta MCP_USER en el .env: el servidor MCP actúa como un usuario del agente y, sin él, "
    "no arranca."
)
NO_COMPOSE = "No se pudo arrancar el servidor MCP: revisa la configuración, Jira y PostgreSQL."


def main() -> int:
    try:
        config = build_config()
    except ConfigError as exc:
        print(f"Configuración no válida: {exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:  # solo los nombres de las variables: nunca sus valores
        names = sorted({str(e["loc"][0]).upper() for e in exc.errors() if e.get("loc")})
        print(f"Configuración no válida en el .env: {', '.join(names)}.", file=sys.stderr)
        return 2
    settings = config.settings
    configure_logging(settings.log_level, secrets=settings.secret_values(), stream=sys.stderr)
    # Las bibliotecas HTTP registran URLs completas (con query string): solo avisos. `openai` y
    # `mcp` usan `httpx2`/`httpcore2`; el SDK de MCP configura el logging raíz a INFO en stderr.
    for name in ("httpx", "httpcore", "httpx2", "httpcore2", "openai", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)
    username = (settings.mcp_user or "").strip()
    if not username:
        print(NO_USER, file=sys.stderr)
        return 2
    user = User(username=username, role=settings.mcp_role)
    try:
        container = build_app_container(config)
    except AgentError as exc:  # mensaje pensado para la persona, sin secretos
        print(f"{NO_COMPOSE} ({exc})", file=sys.stderr)
        return 1
    except Exception as exc:  # otros fallos pueden citar la conexión: solo el tipo
        print(f"{NO_COMPOSE} ({type(exc).__name__})", file=sys.stderr)
        return 1
    build_server(container, user).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
