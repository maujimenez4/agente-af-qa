"""Construcción del grafo LangGraph (SPEC-00 §5)."""

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from adapters.base import Chunk, IssueDetail, IssueLink, IssueSummary, RetrievedChunk
from adapters.errors import ExternalServiceError
from core.container import Container
from core.graph.nodes import GraphNodes
from core.graph.state import AgentState
from core.handoff import HandoffStore
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
    """Checkpointer en memoria para pruebas (las conversaciones no sobreviven al proceso)."""
    return InMemorySaver(serde=checkpoint_serializer())


def postgres_checkpointer(conninfo: str, *, max_size: int = 5) -> PostgresSaver:
    """Checkpointer en PostgreSQL con el serializador de tipos explícitos (T-52, RF-20).

    Crea sus tablas con `setup()` (idempotente): no van en Alembic porque sus índices se crean
    con `CREATE INDEX CONCURRENTLY`, que no admite transacción. `conninfo` lleva la contraseña:
    nunca se registra.
    """
    pool = ConnectionPool(
        conninfo,
        min_size=1,
        max_size=max_size,
        timeout=10.0,  # con la BD caída, la app avisa en segundos y no a los 30 por defecto
        # Lo que exige PostgresSaver: autocommit, sin sentencias preparadas y filas como dict.
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    saver = PostgresSaver(pool, serde=checkpoint_serializer())  # type: ignore[arg-type]
    try:
        saver.setup()
    except psycopg.Error:
        pool.close()
        raise ExternalServiceError(
            "No se pudo preparar el almacén de conversaciones en PostgreSQL.", service="postgres"
        ) from None
    return saver


def _after_review(state: AgentState) -> str:
    routes = {"iterate": "generate", "edit": "human_review", "approve": "publish"}
    return routes.get(state["decision"] or "", END)


def build_graph(
    container: Container,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    handoffs: HandoffStore | None = None,
) -> CompiledStateGraph:
    """`handoffs`: entregas a QA (T-54); sin ellas, una conversación de QA encadenada falla."""
    nodes = GraphNodes(container, handoffs)
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
        "human_review",
        _after_review,
        {"generate": "generate", "human_review": "human_review", "publish": "publish", END: END},
    )
    graph.add_edge("publish", "memorize")
    graph.add_edge("memorize", END)
    return graph.compile(checkpointer=checkpointer or memory_checkpointer())
