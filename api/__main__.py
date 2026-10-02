"""Arranca la API: `uv run python -m api [--host 127.0.0.1] [--port 8000]` (T-55).

Un solo proceso (las sesiones viven en memoria) y sin el access log de uvicorn, que registraría
la query string (p. ej. lo buscado); la API registra su propia línea por petición.
"""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="API del agente para el frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("api.app:app", host=args.host, port=args.port, workers=1, access_log=False)


if __name__ == "__main__":
    main()
