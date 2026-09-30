"""Estado del grafo (SPEC-00 §5.1)."""

from typing import Literal, NotRequired, TypedDict

from adapters.base import IssueDetail, RetrievedChunk
from schemas.artifact import Artifact

Decision = Literal["iterate", "approve", "discard"]


class Origin(TypedDict):
    kind: Literal["epic", "story", "need"]
    key: NotRequired[str]
    text: NotRequired[str]


class AgentState(TypedDict):
    user: str
    mode: Literal["functional", "qa"]
    origin: Origin  # {kind: "epic"|"story"|"need", key?: str, text?: str}
    jira_context: list[IssueDetail]
    rag_context: list[RetrievedChunk]
    artifact: Artifact | None
    feedback: list[str]  # historial de iteración (RF-20)
    decision: Decision | None
    published_keys: list[str]
    errors: list[str]


def initial_state(user: str, mode: Literal["functional", "qa"], origin: Origin) -> AgentState:
    return AgentState(
        user=user,
        mode=mode,
        origin=origin,
        jira_context=[],
        rag_context=[],
        artifact=None,
        feedback=[],
        decision=None,
        published_keys=[],
        errors=[],
    )
