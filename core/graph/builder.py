"""Construcción del grafo LangGraph (SPEC-00 §5)."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from adapters.base import Chunk, IssueDetail, IssueLink, IssueSummary, RetrievedChunk
from core.container import Container
from core.graph.nodes import GraphNodes
from core.graph.state import AgentState
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, Priority, SourceRef
from schemas.impact import ImpactAnalysis, ImpactItem, StoryDiff
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory

# Tipos que el checkpointer puede deserializar (lista explícita, sin pickle).
CHECKPOINT_TYPES: tuple[type, ...] = (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    Priority,
    SourceRef,
    UserStory,
    AcceptanceCriterion,
    BusinessRule,
    ImpactAnalysis,
    ImpactItem,
    StoryDiff,
    TestSuite,
    TestCase,
    TestCaseType,
    TestStep,
    IssueSummary,
    IssueDetail,
    IssueLink,
    Chunk,
    RetrievedChunk,
)


def checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES)


def memory_checkpointer() -> InMemorySaver:
    """Checkpointer en memoria para pruebas; el de Postgres se conecta más adelante."""
    return InMemorySaver(serde=checkpoint_serializer())


def _after_review(state: AgentState) -> str:
    return {"iterate": "generate", "approve": "publish"}.get(state["decision"] or "", END)


def build_graph(
    container: Container, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    nodes = GraphNodes(container)
    graph = StateGraph(AgentState)
    graph.add_node("load_origin", nodes.load_origin)
    graph.add_node("retrieve_context", nodes.retrieve_context)
    graph.add_node("generate", nodes.generate)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("publish", nodes.publish)
    graph.add_node("memorize", nodes.memorize)

    graph.add_edge(START, "load_origin")
    graph.add_edge("load_origin", "retrieve_context")
    graph.add_edge("retrieve_context", "generate")
    graph.add_edge("generate", "human_review")
    graph.add_conditional_edges(
        "human_review", _after_review, {"generate": "generate", "publish": "publish", END: END}
    )
    graph.add_edge("publish", "memorize")
    graph.add_edge("memorize", END)
    return graph.compile(checkpointer=checkpointer or memory_checkpointer())
