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
    """Recorta descripción y comentarios para que la incidencia quepa en `max_tokens`."""
    # Mismo texto que mide `issue_tokens` («clave resumen descripción»), en caracteres.
    fixed = issue_tokens(issue.model_copy(update={"description_text": "", "comments": []}))
    room_chars = max(0, (max_tokens - fixed) * CHARS_PER_TOKEN - 1)
    description = issue.description_text
    if len(description) > room_chars:
        description = description[: max(0, room_chars - len(TRUNCATION_MARK))] + TRUNCATION_MARK
    return issue.model_copy(update={"description_text": description, "comments": []})


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
) -> tuple[list[IssueDetail], list[RetrievedChunk], BudgetReport]:
    """Selecciona el contexto por prioridad sin superar `budget` tokens.

    - `issues` llega ordenado por prioridad; la primera (el origen) entra siempre, recortada
      si hace falta. El resto se recorta o se descarta según quede sitio.
    - `chunks` llega ordenado por prioridad (memorias primero); se descartan los que no caben.
    - Jira puede usar hasta `jira_share` del presupuesto; lo que no use pasa al RAG.
    """
    report = BudgetReport(budget=budget, used=0)
    jira_cap = int(budget * jira_share)
    selected_issues: list[IssueDetail] = []
    used = 0
    for position, issue in enumerate(issues):
        cost = issue_tokens(issue)
        room = (jira_cap if position else budget) - used
        if cost <= room:
            selected_issues.append(issue)
            used += cost
        elif position == 0 or room >= 60:  # el origen siempre; el resto, si cabe algo útil
            trimmed = truncate_issue(issue, room if position else min(room, jira_cap))
            selected_issues.append(trimmed)
            used += issue_tokens(trimmed)
            report.truncated_issues += 1
        else:
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
