"""Presupuesto de tokens del contexto (T-18, PA-07): prioriza y recorta lo que se envía al LLM."""

import math
from collections.abc import Sequence

from pydantic import BaseModel

from adapters.base import IssueDetail, RetrievedChunk

CHARS_PER_TOKEN = 4
TRUNCATION_MARK = " […]"
# Margen por la serialización JSON (nombres de campos, estado, tipo, fuente…).
ISSUE_OVERHEAD_TOKENS = 30
CHUNK_OVERHEAD_TOKENS = 20


def estimate_tokens(text: str) -> int:
    """Estimación barata y conservadora (≈4 caracteres por token)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def issue_tokens(issue: IssueDetail) -> int:
    """Tokens que ocupa la incidencia tal como se envía al LLM (texto + relaciones + margen)."""
    parts = [issue.key, issue.summary, issue.description_text, *issue.comments]
    related = [f"{s.key} {s.summary}" for s in issue.subtasks]
    related += [f"{link.link_type} {link.key}" for link in issue.links]
    related += issue.labels
    return (
        estimate_tokens(" ".join(parts))
        + estimate_tokens(" ".join(related))
        + (ISSUE_OVERHEAD_TOKENS)
    )


def chunk_tokens(chunk: RetrievedChunk) -> int:
    return estimate_tokens(chunk.chunk.content) + CHUNK_OVERHEAD_TOKENS


def truncate_issue(issue: IssueDetail, max_tokens: int) -> IssueDetail:
    """Recorta la incidencia para que quepa en `max_tokens`.

    Se quitan los comentarios; vínculos, subtareas y etiquetas se conservan mientras quepan
    (PA-165: una HU con cientos de subtareas de casos de prueba, D-09, no rompe el presupuesto)
    y la descripción ocupa el resto. Clave y resumen siempre se conservan. Se cuenta de forma
    incremental, con la misma medida que `issue_tokens`, en tiempo lineal (revisión de
    seguridad: sin coste cuadrático con miles de elementos).
    """
    # «clave resumen descripción» con la descripción vacía: dos separadores.
    parts_chars = len(issue.key) + 1 + len(issue.summary) + 1
    related_chars = 0
    count = 0
    kept: dict[str, list[object]] = {"links": [], "subtasks": [], "labels": []}
    # Si hay descripción, se reserva sitio para la marca de recorte: sigue viéndose que se
    # recortó y no se supera el máximo por ella.
    reserve = (
        math.ceil((len(TRUNCATION_MARK) + 1) / CHARS_PER_TOKEN) if issue.description_text else 0
    )
    texts = {
        "links": lambda link: f"{link.link_type} {link.key}",
        "subtasks": lambda sub: f"{sub.key} {sub.summary}",
        "labels": lambda label: label,
    }
    for name in ("links", "subtasks", "labels"):
        for item in getattr(issue, name):
            extra = len(texts[name](item)) + (1 if count else 0)
            cost = (
                math.ceil(parts_chars / CHARS_PER_TOKEN)
                + math.ceil((related_chars + extra) / CHARS_PER_TOKEN)
                + ISSUE_OVERHEAD_TOKENS
            )
            if cost > max_tokens - reserve:
                break
            kept[name].append(item)
            related_chars += extra
            count += 1
    current = issue.model_copy(
        update={"description_text": "", "comments": [], **kept}  # type: ignore[arg-type]
    )
    fixed = issue_tokens(current)
    room_chars = max(0, (max_tokens - fixed) * CHARS_PER_TOKEN - 1)
    description = issue.description_text
    if len(description) > room_chars:
        description = description[: max(0, room_chars - len(TRUNCATION_MARK))] + TRUNCATION_MARK
    return current.model_copy(update={"description_text": description})


class BudgetReport(BaseModel):
    budget: int
    used: int
    dropped_issues: int = 0
    dropped_chunks: int = 0
    truncated_issues: int = 0


def apply_budget(
    issues: Sequence[IssueDetail],
    chunks: Sequence[RetrievedChunk],
    budget: int,
    jira_share: float = 0.5,
    *,
    has_origin: bool = True,
) -> tuple[list[IssueDetail], list[RetrievedChunk], BudgetReport]:
    """Selecciona el contexto por prioridad sin superar `budget` tokens.

    - `issues` llega ordenado por prioridad; la primera (el origen) entra siempre, recortada
      si hace falta. El resto se recorta o se descarta según quede sitio.
    - `chunks` llega ordenado por prioridad (memorias primero); se descartan los que no caben.
    - Jira puede usar hasta `jira_share` del presupuesto; lo que no use pasa al RAG.
    - `has_origin=False` (una necesidad, PA-167): no hay origen; todas son secundarias.
    """
    report = BudgetReport(budget=budget, used=0)
    jira_cap = int(budget * jira_share)
    selected_issues: list[IssueDetail] = []
    used = 0
    for position, issue in enumerate(issues):
        is_origin = has_origin and position == 0
        cost = issue_tokens(issue)
        room = (budget if is_origin else jira_cap) - used
        if cost <= room:
            selected_issues.append(issue)
            used += cost
            continue
        if is_origin or room >= 60:  # el origen siempre; el resto, si cabe algo útil
            trimmed = truncate_issue(issue, min(room, jira_cap) if is_origin else room)
            if is_origin or issue_tokens(trimmed) <= room:
                selected_issues.append(trimmed)
                used += issue_tokens(trimmed)
                report.truncated_issues += 1
                continue
        report.dropped_issues += 1

    selected_chunks: list[RetrievedChunk] = []
    for chunk in chunks:
        cost = chunk_tokens(chunk)
        if used + cost <= budget:
            selected_chunks.append(chunk)
            used += cost
        else:
            report.dropped_chunks += 1
    report.used = used
    return selected_issues, selected_chunks, report
