"""Arranca la API: `uv run python -m api [--host 127.0.0.1] [--port 8000]` (T-55).

Un solo proceso (las sesiones viven en memoria) y sin el access log de uvicorn, que registraría
la query string (p. ej. lo buscado); la API registra su propia línea por petición.

Sin `proxy_headers` (PA-469): uvicorn confía por defecto en `X-Forwarded-For` si la conexión
llega de 127.0.0.1, que es el proxy de Vite, y este la reenvía tal como la manda el navegador.
Así, cualquiera podría inventarse su IP en el límite de login. La IP la decide `login_ip`
(`api/security.py`) con `API_TRUSTED_PROXIES`. El contenedor (`Dockerfile`) arranca por aquí.
"""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="API del agente para el frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("api.app:app", **server_options(args.host, args.port))


def server_options(host: str, port: int) -> dict[str, object]:
    """Opciones de `uvicorn.run`; aparte para poder comprobarlas en las pruebas (PA-469)."""
    return {
        "host": host,
        "port": port,
        "workers": 1,
        "access_log": False,
        "proxy_headers": False,  # PA-469: nunca reescribir la IP del cliente desde cabeceras
    }


if __name__ == "__main__":
    main()
