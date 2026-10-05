"""Dos memorias de ejemplo, ficticias, para ver la pestaña Memoria sin publicar en Jira (T-33).

Uso (solo con `APP_ENV=development`):
    uv run python -m core.memory.seed_demo                   # proyecto DEMO
    uv run python -m core.memory.seed_demo --proyecto ABC    # claves ABC-9001 y ABC-9002
    uv run python -m core.memory.seed_demo --forzar          # sobrescribe las que ya existan

Escribe `<PROYECTO>-9001.md` y `<PROYECTO>-9002.md` en `data/memory/` con el formato de
`Memory.to_markdown()`. No toca Jira, ni el LLM, ni el RAG: aparecen como «no indexadas». Para
quitarlas basta con borrar esos dos `.md`.
"""

import argparse
import sys
from pathlib import Path

from core.projects import normalize_project_key
from schemas.common import ArtifactType
from schemas.memory import Memory

DEMO_NUMBERS = (9001, 9002)
FICTITIOUS = (
    "Memoria de ejemplo FICTICIA (Biblioteca Municipal de Villaficticia): no es una HU real."
)


def demo_memories(project: str) -> list[Memory]:
    """Las dos memorias de ejemplo del proyecto `project`; todo su texto es inventado."""
    renew, reserve = (f"{project}-{number}" for number in DEMO_NUMBERS)
    return [
        Memory(
            artifact_type=ArtifactType.USER_STORY,
            jira_key=renew,
            version=2,
            objective="Ejemplo ficticio: permitir a una persona socia renovar un préstamo "
            "desde la web de la Biblioteca de Villaficticia sin pasar por el mostrador.",
            scope=f"{FICTITIOUS} Incluye la renovación desde «Mis préstamos»; no incluye pagos.",
            business_rules=[
                "RN-1: un préstamo se renueva como máximo dos veces.",
                "RN-2: no se renueva un libro que otra persona socia tenga reservado.",
            ],
            decisions=["La nueva fecha de devolución se calcula desde el día de la renovación."],
            dependencies=[f"{reserve}: reservas de libros (memoria de ejemplo)."],
            changes=["v2: se añade el límite de dos renovaciones (RN-1)."],
            acceptance_criteria=[
                "CA-1: con un préstamo renovable, al pulsar «Renovar» se muestra la nueva fecha.",
                "CA-2: con dos renovaciones hechas, el botón «Renovar» no aparece.",
            ],
            references=[renew, "Corpus ficticio: normativa-prestamo-villaficticia.md"],
        ),
        Memory(
            artifact_type=ArtifactType.USER_STORY,
            jira_key=reserve,
            version=1,
            objective="Ejemplo ficticio: permitir a una persona socia reservar un libro "
            "prestado para recogerlo cuando se devuelva.",
            scope=f"{FICTITIOUS} Incluye la cola de reservas; no incluye avisos por SMS.",
            business_rules=["RN-1: cada persona socia tiene como máximo tres reservas activas."],
            decisions=["La reserva caduca a los tres días de quedar el libro disponible."],
            dependencies=[],
            changes=[],
            acceptance_criteria=[
                "CA-1: con un libro prestado, al pulsar «Reservar» la reserva queda en la cola.",
            ],
            references=[reserve],
        ),
    ]


def seed(memory_dir: Path, project: str, *, force: bool = False) -> tuple[list[Path], list[Path]]:
    """Escribe las memorias de ejemplo; devuelve (escritas, omitidas porque ya existían)."""
    memory_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    skipped: list[Path] = []
    for memory in demo_memories(project):
        path = memory_dir / f"{memory.jira_key}.md"
        # Nunca a través de un enlace simbólico, ni con `--forzar`: podría apuntar a otra memoria.
        if path.is_symlink() or (path.exists() and not force):
            skipped.append(path)
            continue
        path.write_text(memory.to_markdown(), encoding="utf-8", newline="\n")
        written.append(path)
    return written, skipped


def main(
    argv: list[str] | None = None,
    *,
    app_env: str | None = None,
    memory_dir: Path | None = None,
) -> int:
    from core.config import Settings
    from core.container import DEFAULT_MEMORY_DIR

    parser = argparse.ArgumentParser(
        prog="python -m core.memory.seed_demo",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--proyecto", default="DEMO", help="clave del proyecto (por defecto DEMO)")
    parser.add_argument("--forzar", action="store_true", help="sobrescribe las que ya existan")
    args = parser.parse_args(argv or [])
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # consolas cp1252
    env = app_env if app_env is not None else Settings().app_env
    if env.strip().lower() != "development":
        sys.stderr.write("Solo se siembran memorias de ejemplo con APP_ENV=development.\n")
        return 2
    try:
        project = normalize_project_key(args.proyecto)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    target = memory_dir or DEFAULT_MEMORY_DIR
    written, skipped = seed(target, project, force=args.forzar)
    for path in written:
        print(f"Escrita: {path.name}")
    for path in skipped:
        print(f"Ya existía (usa --forzar para sobrescribirla): {path.name}")
    names = " y ".join(f"{project}-{number}.md" for number in DEMO_NUMBERS)
    print(
        f"\nSon memorias ficticias y no están indexadas en el RAG. Para quitarlas, borra {names} "
        f"de {target}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
