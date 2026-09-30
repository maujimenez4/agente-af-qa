"""CLI para crear (o reiniciar) los 3 usuarios sintéticos de demo (T-22).

Uso: `uv run python -m core.seed_users`

Es un punto de composición (SPEC-00 §11): toma la configuración y el `LocalAuthProvider` de
`core/factories.py`. Las contraseñas se generan al azar y se muestran UNA sola vez por la consola:
no se guardan en el repositorio, en `.env` ni en los logs. No redirijas la salida a un archivo.
"""

import sys

from adapters.auth.seed import seed_demo_users


def main() -> int:
    from core.config import build_config
    from core.factories import build_auth

    created = seed_demo_users(build_auth(build_config()))
    sys.stdout.reconfigure(encoding="utf-8")  # consolas de Windows en cp1252
    print("Usuarios de demo creados. Guarda estas contraseñas: no se volverán a mostrar.\n")
    for username, role, password in created:
        print(f"  {username:<12} rol={role:<11} contraseña={password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
