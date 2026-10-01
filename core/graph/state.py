"""Estado del grafo (SPEC-00 §5.1)."""

import re
from typing import Literal, NotRequired, TypedDict

from adapters.base import IssueDetail, RetrievedChunk
from core.projects import ISSUE_KEY
from schemas.artifact import Artifact

Decision = Literal["iterate", "edit", "approve", "discard"]
MAX_EXCLUDED_SOURCES = 50
# Clave de Jira, id de documento o de memoria: nunca texto libre (llega a la auditoría).
SOURCE_REF = re.compile(r"^[A-Za-z0-9_.:/-]{1,100}$")


class Origin(TypedDict):
    kind: Literal["epic", "story", "need"]
    key: NotRequired[str]
    text: NotRequired[str]
    project: NotRequired[str]  # proyecto de Jira de la conversación (T-50)


class AgentState(TypedDict):
    user: str
    mode: Literal["functional", "qa"]
    origin: Origin  # {kind: "epic"|"story"|"need", key?: str, text?: str, project?: str}
    jira_context: list[IssueDetail]
    rag_context: list[RetrievedChunk]
    artifact: Artifact | None
    feedback: list[str]  # historial de iteración (RF-20)
    decision: Decision | None
    excluded_sources: list[str]  # fuentes desmarcadas antes de generar (T-51, RF-21)
    published_keys: list[str]
    errors: list[str]


def initial_state(
    user: str,
    mode: Literal["functional", "qa"],
    origin: Origin,
    excluded_sources: list[str] | None = None,
) -> AgentState:
    """Estado inicial; con clave de origen, el proyecto es el de la clave (T-50).

    `excluded_sources`: claves de Jira o referencias del RAG que no influirán en la propuesta
    (T-51). La incidencia de origen no se puede excluir.
    """
    origin = Origin(**origin)
    if (key := origin.get("key")) and (match := ISSUE_KEY.fullmatch(key)):
        origin["project"] = match.group(1)  # una clave de otro proyecto lo cambia
    excluded = sorted({ref.strip() for ref in excluded_sources or [] if ref.strip()})
    if len(excluded) > MAX_EXCLUDED_SOURCES:
        raise ValueError(f"Se pueden excluir como máximo {MAX_EXCLUDED_SOURCES} fuentes.")
    if invalid := [ref for ref in excluded if not SOURCE_REF.fullmatch(ref)]:
        raise ValueError(f"Referencia de fuente no válida: {invalid[0][:50]!r}.")
    if key and key in excluded:
        raise ValueError(f"La incidencia de origen {key} no se puede excluir de las fuentes.")
    return AgentState(
        user=user,
        mode=mode,
        origin=origin,
        jira_context=[],
        rag_context=[],
        artifact=None,
        feedback=[],
        decision=None,
        excluded_sources=excluded,
        published_keys=[],
        errors=[],
    )
