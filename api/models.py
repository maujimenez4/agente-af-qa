"""Modelos de petición y respuesta de la API (T-55). Textos para la persona, en español.

Reutiliza los modelos del dominio (`schemas/`) y de los servicios del núcleo para que el contrato
y la implementación no se separen.
"""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from adapters.base import IssueSummary, ProjectSummary
from core.conversations import ConversationSummary
from core.guided_start import SourcePreview, StartProposal
from schemas.artifact import Artifact
from schemas.impact import ImpactAnalysis
from schemas.quality import QualityReport
from schemas.test_case import MAX_EVIDENCE_CHARS, TestSuite
from schemas.user_story import UserStory

Role = Literal["functional", "qa", "admin"]
Mode = Literal["functional", "qa"]
Flow = Literal["need", "evolve", "tests"]
KEY_PATTERN = r"^[A-Za-z][A-Za-z0-9_]+-\d+$"
PROJECT_PATTERN = r"^[A-Za-z][A-Za-z0-9_]+$"
ID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
FINGERPRINT_PATTERN = r"^[0-9a-f]{64}$"
SourceRefText = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")]
FeedbackText = Annotated[str, Field(min_length=1, max_length=1000)]
# Flujo de la conversación → tipos de origen admitidos (T-53: opciones de `GuidedStart`).
FLOW_ORIGINS = {"need": ("need", "epic"), "evolve": ("story",), "tests": ("story",)}

# --- Errores ------------------------------------------------------------------------------------


# PA-306: todos los códigos que puede devolver la API (respuestas HTTP y `ConversationOut.error`).
ErrorCode = Literal[
    # sesión y permisos
    "unauthenticated",
    "invalid_credentials",
    "too_many_attempts",
    "forbidden",
    # petición
    "invalid_request",
    "payload_too_large",
    "not_found",
    "project_not_found",
    "method_not_allowed",
    "http_error",
    # estado de la conversación
    "not_in_review",
    "not_in_error",  # PA-276: reintentar una conversación que no está en error
    "not_cancellable",  # PA-314: no está generando, o lo que hace es aprobar o publicar
    "cancelled",  # PA-314: la persona detuvo la generación (se puede reintentar)
    "approval_rejected",
    "handoff_unavailable",
    "operation_failed",
    "restart",
    "too_many_streams",
    # servicios externos (Jira, LLM, PostgreSQL)
    "rate_limited",
    "service_unavailable",
    "provider_timeout",
    # generación (suelen llegar en `ConversationOut.error` o `QualityReviewOut.error`)
    "invalid_model_output",
    "citation_failed",
    "coverage_failed",
    "quality_failed",
    "publish_failed",
    # otros
    "unexpected",
]


class ErrorBody(BaseModel):
    code: ErrorCode = Field(
        description="Código estable para la UI. `message` ya está en español y listo para mostrar."
    )
    message: str = Field(description="Mensaje en español para mostrar a la persona.")
    retry_after: float | None = Field(
        default=None, description="Segundos a esperar antes de reintentar, si aplica."
    )


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Sesión --------------------------------------------------------------------------------------


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    username: str
    role: Role
    permissions: list[str] = Field(description="Permisos de `core/permissions.py` del rol.")


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str = Field(
        description="Se envía en la cabecera `X-CSRF-Token` en toda petición que modifica algo. "
        "La sesión va en una cookie HttpOnly que el frontend no ve."
    )


# --- Proyectos y Jira ----------------------------------------------------------------------------


class ProjectsOut(BaseModel):
    projects: list[ProjectSummary]
    preselected: str | None = Field(
        description="Último proyecto usado o, si no, `JIRA_PROJECT_KEY` si es visible (T-50)."
    )


class ChooseProjectIn(BaseModel):
    project: str = Field(pattern=PROJECT_PATTERN, max_length=50)


class ChooseProjectOut(BaseModel):
    project: str


class IssueCard(BaseModel):
    """Ficha de una incidencia para las tarjetas (HU parecida, clave reconocida)."""

    key: str
    project: str
    summary: str
    issue_type: str
    status: str
    epic_key: str | None = None
    criteria_count: int = Field(ge=0, description="CA contados en la descripción, sin IA.")
    rules_count: int = Field(ge=0, description="RN contadas en la descripción, sin IA.")
    test_cases: int | None = Field(
        default=None,
        ge=0,
        description="Subtareas CP («caso-prueba») de la HU en Jira (PA-104); `null` si no se "
        "pudo consultar.",
    )
    published_by_agent: bool | None = Field(
        default=None,
        description="El agente publicó esta HU en Jira (PA-104); `null` si no se sabe.",
    )


# --- Arranque guiado -----------------------------------------------------------------------------


class OriginIn(BaseModel):
    kind: Literal["epic", "story", "need"]
    key: str | None = Field(default=None, pattern=KEY_PATTERN, max_length=50)
    text: str | None = Field(default=None, max_length=4000)
    project: str = Field(pattern=PROJECT_PATTERN, max_length=50)


class ProposeIn(BaseModel):
    text: str = Field(max_length=4000)
    project: str = Field(pattern=PROJECT_PATTERN, max_length=50)
    mode: Mode = "functional"


class ContextBudgetOut(BaseModel):
    """Presupuesto de tokens del contexto que se enviará al LLM (PA-102)."""

    used: int = Field(ge=0, description="Tokens estimados de las fuentes seleccionadas.")
    limit: int = Field(ge=0, description="Tokens disponibles para las fuentes.")
    dropped_sources: int = Field(
        ge=0, description="Fuentes que no caben y no se enviarán (incidencias y fragmentos)."
    )
    truncated_sources: int = Field(ge=0, description="Incidencias recortadas para que quepan.")


class SourcesOut(BaseModel):
    sources: list[SourcePreview]
    budget: ContextBudgetOut


class SourcesIn(BaseModel):
    origin: OriginIn
    excluded_sources: list[SourceRefText] = Field(default=[], max_length=50)


# --- Conversaciones ------------------------------------------------------------------------------

ConversationState = Literal[
    "generating", "in_review", "approved", "simulated", "published", "discarded", "error"
]
StepState = Literal["pending", "running", "done"]


class ConversationCreateIn(BaseModel):
    flow: Flow
    origin: OriginIn
    excluded_sources: list[SourceRefText] = Field(default=[], max_length=50)
    feedback: list[FeedbackText] = Field(
        default=[],
        max_length=30,
        description="Restricciones, tipos de caso o `evolve_feedback` de T-48 (uno por hallazgo).",
    )

    @model_validator(mode="after")
    def _flow_matches_origin(self) -> Self:
        allowed = FLOW_ORIGINS[self.flow]
        if self.origin.kind not in allowed:
            raise ValueError(f"El flujo «{self.flow}» no admite un origen «{self.origin.kind}».")
        if self.flow == "tests" and self.origin.text:
            raise ValueError("El flujo de pruebas parte siempre de una HU, sin texto libre.")
        return self


class ProgressStep(BaseModel):
    node: Literal["load_origin", "retrieve_context", "generate", "publish", "memorize"]
    label: str
    state: StepState


class ReviewPayload(BaseModel):
    """La pausa de `human_review` (UI.md §5, anexo §11 de la SPEC)."""

    artifact: Artifact
    version: int
    target: dict[str, str | None] = Field(description="Operación que se aprobará (`describe()`).")
    fingerprint: str = Field(description="Huella que hay que devolver **tal cual** para aprobar.")
    impact: ImpactAnalysis | None = None
    plan: list[dict[str, str]] = Field(description="Operaciones de Jira: el recibo (RF-31).")
    decisions: list[Literal["iterate", "edit", "approve", "discard"]]
    error: str | None = Field(
        default=None, description="Motivo de la última respuesta rechazada (la revisión sigue)."
    )


class VersionOut(BaseModel):
    version: int
    artifact: Artifact
    created_at: datetime
    edited: bool = Field(default=False, description="Versión editada a mano (RF-32).")


class PublishOutcome(BaseModel):
    simulated: bool
    plan: list[dict[str, str]]
    approved_by: str
    approved_at: datetime
    published_keys: list[str] = []
    errors: list[str] = Field(default=[], description="Publicación parcial (RNF-13).")
    failed_ids: list[str] = Field(
        default=[], description="CP o adjuntos que fallaron (para «Reintentar solo los fallidos»)."
    )


class ConversationOut(BaseModel):
    """Detalle de una conversación.

    `state` amplía el `status` de la lista (`ConversationSummary`): `generating` cuando el grafo
    está trabajando (en la lista, `started` o el estado anterior) y `error` cuando la última
    operación falló. Una publicación parcial queda en `approved` con `result.errors`.
    """

    id: str = Field(description="Identificador de la conversación (generado por el servidor).")
    title: str
    project: str
    flow: Flow
    mode: Mode
    state: ConversationState
    progress: list[ProgressStep]
    review: ReviewPayload | None = None
    versions: list[VersionOut] = []
    feedback: list[str] = []
    result: PublishOutcome | None = None
    error: ErrorBody | None = None
    updated_at: datetime
    cancel_requested: bool = Field(
        default=False,
        description="PA-314: se pidió detener la generación y aún está terminando el paso en "
        "curso («Deteniendo…»). Vuelve a `false` al terminar.",
    )
    jira_baseline: UserStory | None = Field(
        default=None,
        description="PA-316: la HU tal como está en Jira, estructurada (la versión de partida que "
        "el agente ya calculó; nunca se llama al LLM para esto). Solo al evolucionar una HU "
        "existente y mientras se puede iterar; `null` en una HU nueva, en QA, antes de la primera "
        "versión y cuando la conversación termina (aprobada, simulada, publicada o descartada).",
    )


class IterateIn(BaseModel):
    feedback: str = Field(min_length=1, max_length=4000)


class EditIn(BaseModel):
    content: UserStory | TestSuite = Field(
        description="Contenido completo editado: HU o suite, según el artefacto en revisión."
    )
    feedback: FeedbackText | None = Field(default=None, description="Nota opcional (RF-20).")
    fingerprint: str = Field(min_length=64, max_length=64, pattern=FINGERPRINT_PATTERN)


class ApproveIn(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64, pattern=FINGERPRINT_PATTERN)


# --- Revisar la calidad --------------------------------------------------------------------------


class QualityReviewIn(BaseModel):
    issue_key: str = Field(pattern=KEY_PATTERN, max_length=50)
    excluded_sources: list[SourceRefText] = Field(default=[], max_length=50)


class QualityReviewOut(BaseModel):
    id: str
    issue_key: str
    state: Literal["running", "done", "error"]
    report: QualityReport | None = None
    evolve_feedback: list[str] = Field(
        default=[], description="Feedback inicial para «Evolucionar con esto»."
    )
    report_markdown: str | None = Field(
        default=None, description="Informe escapado, **solo para descargar** (no pintarlo)."
    )
    error: ErrorBody | None = None
    created_at: datetime
    updated_at: datetime


class QualityReviewSummary(BaseModel):
    """Una revisión en la lista de la persona (PA-103): «Informe listo» si `state=done`."""

    id: str
    issue_key: str
    project: str
    title: str = Field(description="Solo el flujo y la clave («Revisar la calidad de DEMO-3»).")
    state: Literal["running", "done", "error"]
    created_at: datetime
    updated_at: datetime


# --- Registrar la ejecución (QA 6, T-47) ---------------------------------------------------------

ExecutionStatusValue = Literal["paso", "fallo", "bloqueado", "sin-ejecutar"]
ExecutionState = Literal[
    "in_review", "recording", "simulated", "recorded", "partial", "discarded", "error"
]


class ExecutionCreateIn(BaseModel):
    story_key: str = Field(
        pattern=KEY_PATTERN, max_length=50, description="HU con su suite publicada."
    )


class ExecutionResultIn(BaseModel):
    case_key: str = Field(pattern=KEY_PATTERN, max_length=50, description="Subtarea CP en Jira.")
    status: ExecutionStatusValue = Field(description="Lo elige la persona, nunca la IA.")
    evidence_md: str = Field(
        default="",
        max_length=MAX_EVIDENCE_CHARS,
        description="Obligatoria si el caso falla (`fallo`).",
    )


class ExecutionResultsIn(BaseModel):
    results: list[ExecutionResultIn] = Field(max_length=200)
    environment: str = Field(default="", max_length=100, description="P. ej. «preproducción».")


class ExecutionCaseOut(BaseModel):
    key: str
    summary: str
    status: str = Field(description="Estado actual de la subtarea en Jira.")


class ExecutionResultOut(BaseModel):
    case_key: str
    status: ExecutionStatusValue
    evidence_md: str


class ExecutionOutcome(BaseModel):
    recorded: list[str] = Field(description="Subtareas en las que se registró el resultado.")
    failed: list[str] = Field(default=[], description="Subtareas que fallaron (parcial, RNF-13).")
    errors: list[str] = []
    approved_by: str
    approved_at: datetime | None = None
    simulated: bool = Field(
        default=False, description="Modo simulación: no se escribió nada en Jira."
    )


class ExecutionOut(BaseModel):
    """Registro de la ejecución de las pruebas de una HU (UI.md §6.6).

    `in_review`: borrador editable con `PUT /results`; `fingerprint` es la huella del registro
    tal como está, y se devuelve exacta al aprobar. Si una respuesta no se pudo aplicar, la revisión
    sigue con `review_error`. Tras aprobar: `recorded` o `partial` (con `outcome.failed`).
    """

    id: str
    story_key: str
    project: str
    state: ExecutionState
    cases: list[ExecutionCaseOut]
    results: list[ExecutionResultOut] = []
    environment: str = ""
    plan: list[dict[str, str]] = Field(default=[], description="Recibo: una operación por caso.")
    fingerprint: str | None = None
    review_error: str | None = None
    outcome: ExecutionOutcome | None = None
    error: ErrorBody | None = None


# --- QA encadenada (T-54) -----------------------------------------------------------------------

HANDOFF_ID_PATTERN = r"^[0-9a-f]{32}$"


class HandoffOut(BaseModel):
    """Una HU aprobada o publicada lista para preparar sus pruebas (T-54)."""

    id: str = Field(pattern=HANDOFF_ID_PATTERN)
    title: str
    project: str
    story_key: str | None = Field(description="Sin clave si la HU solo se aprobó en simulación.")
    version: int
    from_user: str
    created_at: datetime


# --- Ajustes de la sesión ------------------------------------------------------------------------


class ModelChoiceOut(BaseModel):
    provider: str
    model: str


class TaskModelsOut(BaseModel):
    task: str
    chain: list[ModelChoiceOut]
    override: ModelChoiceOut | None = None


class UsageTodayOut(BaseModel):
    """Consumo de tokens de hoy (PA-305), para el anillo del carril."""

    tokens_today: int = Field(ge=0, description="Tokens de todas las llamadas al LLM de hoy.")
    warning_threshold: int = Field(
        gt=0, description="Umbral de aviso diario (`limits.daily_token_warning`)."
    )
    scope: Literal["global"] = Field(
        default="global",
        description="El registro de uso no guarda la persona: el consumo es el de toda la "
        "instalación.",
    )


class SettingsOut(BaseModel):
    publish_mode: Literal["simulation", "live"]
    tasks: list[TaskModelsOut]


class ModelOverrideIn(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)


# --- Administración (T-29 mínima) ---------------------------------------------------------------


class ConnectionCheckOut(BaseModel):
    """Resultado de comprobar un servicio; `detail` en español y sin secretos."""

    service: str = Field(description="«Jira», «PostgreSQL», «Modelos · <proveedor>», «Embeddings».")
    ok: bool
    detail: str
    duration_ms: int = Field(ge=0)


class ConnectionsTestOut(BaseModel):
    checks: list[ConnectionCheckOut]


class AdminModelOut(BaseModel):
    provider: str
    model: str
    host: str = Field(description="Solo el host (y el puerto) del proveedor; nunca la URL entera.")


class AdminTaskModelsOut(BaseModel):
    task: str
    chain: list[AdminModelOut]
    override: ModelChoiceOut | None = Field(
        default=None, description="Modelo elegido en la sesión de quien consulta, si lo hay."
    )


class AdminModelsOut(BaseModel):
    tasks: list[AdminTaskModelsOut]
    embeddings: AdminModelOut


__all__ = [
    "ConversationSummary",
    "IssueSummary",
    "SourcePreview",
    "StartProposal",
]
