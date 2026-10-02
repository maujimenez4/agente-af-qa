"""Protocolos de los adaptadores y tipos auxiliares (SPEC-00 §4).

El núcleo depende solo de estos protocolos; las implementaciones se eligen en
`core/container.py`. Los métodos de ESCRITURA solo pueden llamarse desde el nodo `publish`.
"""

from enum import StrEnum
from typing import Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, Field

from schemas.artifact import Artifact
from schemas.common import SourceRef
from schemas.memory import Memory
from schemas.test_case import ExecutionStatus, TestSuite
from schemas.user_story import UserStory

T = TypeVar("T", bound=BaseModel)


class TaskType(StrEnum):
    """Tipos de tarea del LLM; sus valores coinciden con las claves de `config/models.yaml`."""

    GENERATE_STORY = "generate_story"
    EVOLVE_STORY = "evolve_story"
    REVIEW_STORY = "review_story"
    ANALYZE_IMPACT = "analyze_impact"
    GENERATE_TESTS = "generate_tests"
    SYNTHESIZE_MEMORY = "synthesize_memory"
    CLASSIFY_SOURCE = "classify_source"
    NL_TO_JQL = "nl_to_jql"


# --- Tipos auxiliares ------------------------------------------------------------------


class ProjectSummary(BaseModel):
    key: str
    name: str


class IssueSummary(BaseModel):
    key: str
    summary: str
    issue_type: str
    status: str


class IssueLink(BaseModel):
    link_type: str  # p. ej. "relates to", "blocks"
    key: str


class IssueDetail(IssueSummary):
    """Incidencia con su descripción en texto (ADF → texto) y sus relaciones (RF-03)."""

    description_text: str = ""
    parent_key: str | None = None
    subtasks: list[IssueSummary] = []
    links: list[IssueLink] = []
    comments: list[str] = []
    labels: list[str] = []


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class _LLMUsage(BaseModel):
    provider: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class LLMResult(_LLMUsage):
    content: str


class StructuredResult[T: BaseModel](_LLMUsage):
    content: T


class Chunk(BaseModel):
    id: str
    document_id: str
    ordinal: int = Field(ge=0)
    section: str | None = None
    content: str
    embedding: list[float] | None = None
    metadata: dict[str, str] = {}  # categoría, fuente, related_key… (RF-10)


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float
    source: SourceRef


class PublishResult(BaseModel):
    """Resultado de una publicación parcial (RNF-13): claves creadas e IDs fallidos."""

    created: list[str] = []
    failed: list[str] = []


class User(BaseModel):
    username: str
    role: Literal["functional", "qa", "admin"]


# --- Protocolos --------------------------------------------------------------------------


@runtime_checkable
class IssueTracker(Protocol):  # Área A · Jira
    def test_connection(self) -> None: ...
    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]: ...
    def get_issue(self, key: str) -> IssueDetail: ...  # descripción ADF → texto (RF-03)
    def list_projects(self) -> list[ProjectSummary]: ...  # navegación §6.1 (RF-02)
    def list_epics(self, project: str) -> list[IssueSummary]: ...
    def list_children(self, epic_key: str) -> list[IssueSummary]: ...
    # --- ESCRITURA: solo desde el nodo publish ---
    def create_story(
        self, story: UserStory, epic_key: str | None, project: str
    ) -> str: ...  # en `project`, el de la conversación (T-50)
    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None: ...
    def link(
        self, from_key: str, to_key: str, link_type: str, comment_md: str | None = None
    ) -> None: ...


@runtime_checkable
class TestManagement(Protocol):  # Área A · Jira nativo (D-09)
    # --- ESCRITURA: solo desde el nodo publish ---
    def publish_suite(self, suite: TestSuite) -> PublishResult: ...
    # crea subtareas CP, adjunta la estrategia y la matriz; devuelve las claves creadas y los fallos
    def list_cases(self, story_key: str) -> list[IssueSummary]: ...
    # T-47 · ESCRITURA (solo desde el nodo publish del grafo de ejecución): resultado de un CP
    # y evidencia como comentario en su subtarea
    def record_execution(
        self, case_key: str, status: ExecutionStatus, evidence_md: str
    ) -> None: ...


@runtime_checkable
class LLMProvider(Protocol):  # Área A
    def generate(self, messages: list[Message], task: TaskType) -> LLMResult: ...
    def generate_structured(
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):  # Área B
    model_name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


@runtime_checkable
class VectorStore(Protocol):  # Área B
    def upsert(self, chunks: list[Chunk]) -> None: ...
    def delete_by_document(self, document_id: str) -> None: ...
    # PA-225 (PA-216): sustituye los fragmentos de un documento de forma atómica (reindexado)
    def replace_document(self, document_id: str, chunks: list[Chunk]) -> None: ...
    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]: ...  # RF-51


@runtime_checkable
class AuthProvider(Protocol):  # Área A
    def authenticate(self, username: str, password: str) -> User | None: ...


@runtime_checkable
class MemoryGenerator(Protocol):  # Área B · agnóstico al tipo (RNF-25)
    def generate(self, artifact: Artifact) -> Memory: ...
