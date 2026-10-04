"""Incidencias sintéticas que reproducen el fallo de citas del e2e local (PA-281).

Proyecto ficticio AFQP de la «Biblioteca Municipal de Villaficticia». En el e2e, el modelo citaba
la épica o padre (AFQP-10, AFQP-1, AFQP-17) con el extracto de la HU (AFQP-12, AFQP-2, AFQP-25).
Ningún dato corresponde a personas ni proyectos reales.
"""

from adapters.base import IssueDetail

HU_TEXTS: dict[str, str] = {
    "AFQP-12": (
        "Como persona socia, quiero ver en la ficha de un libro qué ejemplares hay y en qué "
        "estado, para decidir si lo reservo o voy directamente a la sala."
    ),
    "AFQP-2": (
        "Como persona socia, quiero reservar un libro disponible desde la web, para recogerlo "
        "en el mostrador sin que otra persona se lo lleve antes."
    ),
    "AFQP-25": (
        "Como persona socia de la biblioteca, quiero renovar un préstamo activo desde la web, "
        "para no tener que acudir al mostrador para ampliar el plazo."
    ),
}

# HU → épica o padre (la clave que el modelo citaba por error).
PARENTS: dict[str, str] = {"AFQP-12": "AFQP-10", "AFQP-2": "AFQP-1", "AFQP-25": "AFQP-17"}

SUMMARIES: dict[str, str] = {
    "AFQP-12": "[HU-05] Ver los ejemplares de un libro",
    "AFQP-2": "[HU-01] Reservar un libro disponible",
    "AFQP-25": "[HU-09] Renovar un préstamo",
}


def afqp_issue(key: str) -> IssueDetail:
    """HU ficticia con la descripción en el formato de la plantilla («## Historia de usuario»)."""
    return IssueDetail(
        key=key,
        summary=SUMMARIES[key],
        issue_type="Historia",
        status="Tareas por hacer",
        parent_key=PARENTS[key],
        description_text=f"## Historia de usuario\n{HU_TEXTS[key]}",
    )


AFQP_ISSUES: list[IssueDetail] = [afqp_issue(key) for key in HU_TEXTS]


def old_format_excerpt(key: str, *, with_parent: bool = True) -> str:
    """Extracto como lo devolvió el modelo en el e2e, con el formato antiguo de la fuente."""
    lines = ["Historia · Tareas por hacer"]
    if with_parent:
        lines.append(f"Épica/padre: {PARENTS[key]}")
        lines.append("## Historia de usuario")
    # El tercero de la captura venía sin el punto final.
    lines.append(HU_TEXTS[key].rstrip("."))
    return "\n".join(lines)


# Los tres pares de la captura: (cita errónea, HU real, ¿traía la línea del padre?).
CAPTURED_PAIRS: list[tuple[str, str, bool]] = [
    ("AFQP-10", "AFQP-12", True),
    ("AFQP-1", "AFQP-2", True),
    ("AFQP-17", "AFQP-25", False),
]
