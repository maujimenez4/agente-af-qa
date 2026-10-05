"""CLI de los 3 usuarios sintéticos de demo (T-22) y su baja (PA-279).

Uso:
    uv run python -m core.seed_users                  # crea o reinicia los usuarios de demo
    uv run python -m core.seed_users --baja af-demo   # da de baja a un usuario de demo

Es un punto de composición (SPEC-00 §11): toma la configuración y el `LocalAuthProvider` de
`core/factories.py`. Las contraseñas se generan al azar y se muestran UNA sola vez por la consola:
no se guardan en el repositorio, en `.env` ni en los logs. No redirijas la salida a un archivo.

La baja (PA-279, RGPD) deja la cuenta con `active=False` y una contraseña aleatoria que no se
muestra, y borra sus revisiones de calidad guardadas. Solo admite los usuarios de demo del seed,
porque son los únicos cuyo rol conoce este comando (PA-284: baja de cualquier usuario).
"""

import argparse
import sys
from collections.abc import Callable

from adapters.auth.seed import DEMO_USERS, generate_password, seed_demo_users


def deactivate(
    username: str,
    save_user: Callable[..., object],
    delete_reviews: Callable[[str], int],
) -> int:
    """Da de baja a un usuario de demo y borra sus revisiones; devuelve cuántas se borraron."""
    roles = dict(DEMO_USERS)
    if username not in roles:
        raise ValueError(f"Solo se dan de baja los usuarios de demo: {', '.join(roles)}.")
    save_user(username, generate_password(), roles[username], active=False)
    return delete_reviews(username)


def main(argv: list[str] | None = None) -> int:
    from core.config import build_config
    from core.factories import build_auth
    from core.quality import SqlQualityReviewStore

    parser = argparse.ArgumentParser(
        prog="python -m core.seed_users",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--baja", metavar="USUARIO", help="da de baja a un usuario de demo")
    args = parser.parse_args(argv or [])  # sin argumentos: crea los usuarios
    config = build_config()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # consolas cp1252
    if args.baja:
        store = SqlQualityReviewStore.from_url(config.settings.sqlalchemy_url())
        try:
            deleted = deactivate(args.baja, build_auth(config).save_user, store.delete_for)
        except ValueError as exc:
            sys.stderr.write(f"{exc}\n")
            return 2
        print(f"Usuario {args.baja} dado de baja; revisiones de calidad borradas: {deleted}.")
        return 0
    created = seed_demo_users(build_auth(config))
    print("Usuarios de demo creados. Guarda estas contraseñas: no se volverán a mostrar.\n")
    for username, role, password in created:
        print(f"  {username:<12} rol={role:<11} contraseña={password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
