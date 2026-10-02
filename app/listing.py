"""Lista de conversaciones del marco común (`docs/specs/UI.md` §2, T-52).

Funciones puras sobre `ConversationSummary`: etiqueta de estado, flujo y agrupación por día.
El título lo compone el servidor solo con flujo y clave (nunca texto libre de la persona).
"""

from datetime import date, datetime

from core.conversations import ConversationSummary

_STATUS = {
    "started": "Empezada",
    "approved": "Aprobada",
    "simulated": "Simulado",
    "published": "Publicado",
    "discarded": "Descartada",
}
_FLOWS = {
    ("functional", "need"): "Nueva necesidad",
    ("functional", "epic"): "Nueva necesidad",
    ("functional", "story"): "Evolucionar una HU",
    ("qa", "story"): "Preparar pruebas",
}


def status_label(row: ConversationSummary) -> str:
    """«Versión N» en revisión, «Simulado», «Publicado»… (UI.md §2 y §9)."""
    if row.status == "in_review":
        return f"Versión {row.version}" if row.version else "En revisión"
    return _STATUS.get(row.status, row.status)


def flow_label(row: ConversationSummary) -> str:
    return _FLOWS.get((row.mode, row.origin_kind), "Conversación")


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Hoy"
    if (today - day).days == 1:
        return "Ayer"
    return day.strftime("%d/%m/%Y")


def group_by_day(
    rows: list[ConversationSummary], today: date | None = None
) -> list[tuple[str, list[ConversationSummary]]]:
    """Grupos por día de la última actividad, en el orden recibido (más reciente primero)."""
    today = today or datetime.now().astimezone().date()
    groups: list[tuple[str, list[ConversationSummary]]] = []
    for row in rows:
        label = day_label(row.updated_at.astimezone().date(), today)
        if groups and groups[-1][0] == label:
            groups[-1][1].append(row)
        else:
            groups.append((label, [row]))
    return groups
