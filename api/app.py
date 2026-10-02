"""Aplicación FastAPI y rutas del contrato (T-55).

Parte 1: el contrato completo (rutas, modelos, errores y ejemplos). Las rutas aún responden 501;
la parte 2 las conecta al contenedor (`core/factories.build_app_container`) y al grafo.

Sesión: cookie HttpOnly `afqa_session` (SameSite=Strict) que el frontend no ve; toda petición que
modifica algo lleva además la cabecera `X-CSRF-Token` con el valor de `SessionOut.csrf_token`.
Las operaciones largas (generar, iterar, aprobar y publicar, revisar la calidad) responden 202
y su avance se sigue con eventos SSE o consultando el estado.
"""

from typing import Any

from fastapi import APIRouter, FastAPI, Path, Query, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from api import examples as ex
from api.models import (
    ID_PATTERN,
    KEY_PATTERN,
    PROJECT_PATTERN,
    ApproveIn,
    ChooseProjectIn,
    ChooseProjectOut,
    ConversationCreateIn,
    ConversationOut,
    ConversationSummary,
    EditIn,
    ErrorResponse,
    HandoffOut,
    IssueCard,
    IssueSummary,
    IterateIn,
    LoginIn,
    ModelOverrideIn,
    ProjectsOut,
    ProposeIn,
    QualityReviewIn,
    QualityReviewOut,
    SessionOut,
    SettingsOut,
    SourcePreview,
    SourcesIn,
    StartProposal,
    TaskModelsOut,
)

API_PREFIX = "/api/v1"
VERSION = "0.1.0"
NOT_YET = "Disponible en la parte 2 de T-55 (API real)."


class NotImplementedYetError(Exception):
    """Ruta del contrato aún sin implementar (parte 1)."""


def _json(example: Any) -> dict[str, Any]:
    return {"content": {"application/json": {"example": example}}}


def _err(code: str, message: str, description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description, **_json(ex.error(code, message))}


UNAUTHORIZED = {
    401: _err("unauthenticated", "Inicia sesión para continuar.", "Sin sesión o caducada."),
}
FORBIDDEN = {
    403: _err(
        "forbidden",
        "No tienes permiso para realizar esta acción.",
        "Sin permiso para el rol, o sin cabecera `X-CSRF-Token` válida.",
    ),
}
NOT_FOUND = {
    404: _err(
        "not_found",
        "No existe esa conversación o no es tuya.",
        "No existe o no pertenece a la persona (mismo mensaje en los dos casos).",
    ),
}
RATE_LIMITED = {
    429: {
        "model": ErrorResponse,
        "description": "Límite de un servicio externo (Jira o el LLM).",
        **_json(ex.error("rate_limited", "Jira ha alcanzado su límite de peticiones.", 30)),
    }
}
NOT_IN_REVIEW = {
    409: _err(
        "not_in_review",
        "La conversación no tiene una propuesta en revisión (está generando o ya terminó).",
        "Estado que no admite la operación. También «Demasiadas respuestas rechazadas…»: "
        "empieza una conversación nueva.",
    ),
}
UNAVAILABLE = {
    503: _err(
        "service_unavailable",
        "No se pudo conectar con Jira. Revisa la URL del sitio y la red.",
        "Servicio externo caído (Jira, PostgreSQL, Ollama).",
    ),
}
AUTH = {**UNAUTHORIZED, **FORBIDDEN}

auth = APIRouter(prefix="/auth", tags=["Sesión"])
projects = APIRouter(tags=["Proyectos y Jira"])
start = APIRouter(prefix="/start", tags=["Arranque guiado"])
conversations = APIRouter(prefix="/conversations", tags=["Conversaciones"])
quality = APIRouter(prefix="/quality-reviews", tags=["Revisar la calidad"])
qa = APIRouter(prefix="/qa", tags=["QA encadenada (provisional, T-54)"])
settings = APIRouter(prefix="/settings", tags=["Ajustes de la sesión"])

ConversationId = Path(description="Identificador de la conversación.", pattern=ID_PATTERN)

# --- Sesión -------------------------------------------------------------------------------------


@auth.post(
    "/login",
    response_model=SessionOut,
    summary="Iniciar sesión",
    description="Crea la cookie de sesión HttpOnly y devuelve el usuario y el token anti-CSRF.",
    responses={
        200: _json(ex.dump(ex.SESSION)),
        401: _err("invalid_credentials", "Usuario o contraseña incorrectos.", "Credenciales."),
        429: _err("too_many_attempts", "Demasiados intentos; espera unos minutos.", "Intentos."),
    },
)
def login(body: LoginIn) -> SessionOut:
    raise NotImplementedYetError


@auth.post("/logout", status_code=204, summary="Cerrar sesión", responses=AUTH)
def logout() -> None:
    raise NotImplementedYetError


@auth.get(
    "/me",
    response_model=SessionOut,
    summary="Sesión actual",
    description="Al recargar la página: usuario y un token anti-CSRF nuevo.",
    responses={200: _json(ex.dump(ex.SESSION)), **UNAUTHORIZED},
)
def me() -> SessionOut:
    raise NotImplementedYetError


# --- Proyectos y Jira ----------------------------------------------------------------------------


@projects.get(
    "/projects",
    response_model=ProjectsOut,
    summary="Proyectos que ve la conexión y el preseleccionado (T-50)",
    responses={200: _json(ex.dump(ex.PROJECTS)), **AUTH, **UNAVAILABLE},
)
def list_projects() -> ProjectsOut:
    raise NotImplementedYetError


@projects.post(
    "/projects/choose",
    response_model=ChooseProjectOut,
    summary="Fijar el proyecto de la conversación y recordarlo como último usado",
    responses={
        200: _json({"project": "DEMO"}),
        **AUTH,
        404: _err(
            "project_not_found",
            "El proyecto DEMO no existe o la conexión no tiene acceso a él.",
            "Proyecto que no ve la conexión de Jira.",
        ),
    },
)
def choose_project(body: ChooseProjectIn) -> ChooseProjectOut:
    raise NotImplementedYetError


@projects.get(
    "/projects/{project}/epics",
    response_model=list[IssueSummary],
    summary="Épicas del proyecto (Elegir en Jira)",
    responses={200: _json(ex.dump(ex.EPICS)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def list_epics(project: str = Path(pattern=PROJECT_PATTERN)) -> list[IssueSummary]:
    raise NotImplementedYetError


@projects.get(
    "/projects/{project}/search",
    response_model=list[IssueSummary],
    summary="Buscar HU y épicas por texto o clave; sin `q`, las recientes del proyecto",
    responses={200: _json(ex.dump(ex.STORIES)), **AUTH, **UNAVAILABLE},
)
def search(
    project: str = Path(pattern=PROJECT_PATTERN),
    q: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[IssueSummary]:
    raise NotImplementedYetError


@projects.get(
    "/epics/{key}/stories",
    response_model=list[IssueSummary],
    summary="HU de una épica",
    responses={200: _json(ex.dump(ex.STORIES)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def list_children(key: str = Path(pattern=KEY_PATTERN)) -> list[IssueSummary]:
    raise NotImplementedYetError


@projects.get(
    "/issues/{key}",
    response_model=IssueCard,
    summary="Ficha de una incidencia (tarjetas de HU parecida o clave reconocida)",
    responses={200: _json(ex.dump(ex.CARD)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def issue_card(key: str = Path(pattern=KEY_PATTERN)) -> IssueCard:
    raise NotImplementedYetError


# --- Arranque guiado -----------------------------------------------------------------------------


@start.post(
    "/propose",
    response_model=StartProposal,
    summary="Proponer con qué empezar a partir del texto (sin IA, T-53)",
    description="Claves de Jira en el texto (también en minúsculas, si existen) o HU parecidas. "
    "Si `project_changed`, avisar; si `ignored_projects` no está vacío, avisar también.",
    responses={200: _json(ex.dump(ex.PROPOSAL)), **AUTH, **UNAVAILABLE},
)
def propose(body: ProposeIn) -> StartProposal:
    raise NotImplementedYetError


@start.post(
    "/sources",
    response_model=list[SourcePreview],
    summary="Fuentes que usaría la propuesta (panel «Antes de generar»)",
    description="Las desmarcadas van en `excluded_sources` al crear la conversación; la fila "
    "`required` (la incidencia de origen) no se puede desmarcar.",
    responses={200: _json(ex.dump(ex.SOURCES)), **AUTH, **UNAVAILABLE},
)
def sources(body: SourcesIn) -> list[SourcePreview]:
    raise NotImplementedYetError


# --- Conversaciones ------------------------------------------------------------------------------


@conversations.get(
    "",
    response_model=list[ConversationSummary],
    summary="Conversaciones de la persona (más recientes primero)",
    responses={200: _json(ex.dump(ex.CONVERSATIONS)), **AUTH},
)
def list_conversations(limit: int = Query(default=50, ge=1, le=100)) -> list[ConversationSummary]:
    raise NotImplementedYetError


@conversations.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Crear una conversación y empezar a generar",
    description="Responde 202 con `state=generating`; el avance llega por `/events` o "
    "consultando la conversación. El `id` lo genera el servidor.",
    responses={202: _json(ex.dump(ex.CONVERSATION_GENERATING)), **AUTH, **RATE_LIMITED},
)
def create_conversation(body: ConversationCreateIn) -> ConversationOut:
    raise NotImplementedYetError


@conversations.get(
    "/{conversation_id}",
    response_model=ConversationOut,
    summary="Estado completo de una conversación",
    description="Progreso, propuesta en revisión (con `plan`, `fingerprint` y `error`), "
    "versiones y resultado. Sirve también para retomarla.",
    responses={200: _json(ex.dump(ex.CONVERSATION)), **AUTH, **NOT_FOUND},
)
def get_conversation(conversation_id: str = ConversationId) -> ConversationOut:
    raise NotImplementedYetError


@conversations.get(
    "/{conversation_id}/events",
    response_class=StreamingResponse,
    summary="Eventos en vivo (SSE)",
    description="`text/event-stream`. Eventos: `progress` (`data`: nodo y estado del paso), "
    "`review_ready`, `result` (publicación simulada, real o parcial) y `error` (`data`: la "
    "conversación completa, como en `GET /conversations/{id}`). Si se corta, basta con "
    "consultar el estado.",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: progress\ndata: {"node": "generate", "state": "running"}\n\n'
                    'event: review_ready\ndata: {"id": "' + ex.THREAD_ID + '", "state": '
                    '"in_review"}\n\n'
                }
            }
        },
        **AUTH,
        **NOT_FOUND,
    },
)
def events(conversation_id: str = ConversationId) -> None:
    raise NotImplementedYetError


@conversations.post(
    "/{conversation_id}/iterate",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Pedir un cambio (RF-20)",
    responses={
        202: _json(ex.dump(ex.CONVERSATION_GENERATING)),
        **AUTH,
        **NOT_FOUND,
        **NOT_IN_REVIEW,
        **RATE_LIMITED,
    },
)
def iterate(body: IterateIn, conversation_id: str = ConversationId) -> ConversationOut:
    raise NotImplementedYetError


@conversations.post(
    "/{conversation_id}/edit",
    response_model=ConversationOut,
    summary="Editar a mano (RF-32): versión nueva con su huella",
    description="`fingerprint` es la del payload mostrado. Una edición inválida no da error HTTP:"
    " la revisión sigue con `review.error` (UI.md §5).",
    responses={200: _json(ex.dump(ex.CONVERSATION)), **AUTH, **NOT_FOUND, **NOT_IN_REVIEW},
)
def edit(body: EditIn, conversation_id: str = ConversationId) -> ConversationOut:
    raise NotImplementedYetError


@conversations.post(
    "/{conversation_id}/approve",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Aprobar y publicar (simulación o real)",
    description="Con la `fingerprint` exacta del último payload. Si no casa, la revisión sigue "
    "con `review.error`. Un rechazo del registro de aprobaciones da 409 y obliga a empezar de "
    "nuevo.",
    responses={
        202: _json(ex.dump(ex.CONVERSATION_SIMULATED)),
        409: _err(
            "approval_rejected",
            "La aprobación no corresponde a la versión revisada; empieza de nuevo.",
            "Rechazo del registro de aprobaciones: la conversación no se recupera.",
        ),
        **AUTH,
        **NOT_FOUND,
        **RATE_LIMITED,
    },
)
def approve(body: ApproveIn, conversation_id: str = ConversationId) -> ConversationOut:
    raise NotImplementedYetError


@conversations.post(
    "/{conversation_id}/discard",
    response_model=ConversationOut,
    summary="Descartar la propuesta",
    responses={
        200: _json(ex.dump(ex.CONVERSATION_DISCARDED)),
        **AUTH,
        **NOT_FOUND,
        **NOT_IN_REVIEW,
    },
)
def discard(conversation_id: str = ConversationId) -> ConversationOut:
    raise NotImplementedYetError


@conversations.post(
    "/{conversation_id}/handoff",
    response_model=HandoffOut,
    summary="Pasar la HU aprobada a QA (provisional, T-54)",
    responses={200: _json(ex.dump(ex.HANDOFFS[0])), **AUTH, **NOT_FOUND},
)
def handoff(conversation_id: str = ConversationId) -> HandoffOut:
    raise NotImplementedYetError


# --- Revisar la calidad --------------------------------------------------------------------------


@quality.post(
    "",
    response_model=QualityReviewOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Revisar la calidad de una HU (T-48, no publica)",
    responses={202: _json(ex.dump(ex.QUALITY)), **AUTH, **NOT_FOUND, **RATE_LIMITED},
)
def create_quality_review(body: QualityReviewIn) -> QualityReviewOut:
    raise NotImplementedYetError


@quality.get(
    "/{review_id}",
    response_model=QualityReviewOut,
    summary="Estado e informe de una revisión de calidad",
    description="`report` se pinta campo a campo como texto; `report_markdown` es solo para "
    "descargarlo.",
    responses={200: _json(ex.dump(ex.QUALITY)), **AUTH, **NOT_FOUND},
)
def get_quality_review(review_id: str = Path(pattern=ID_PATTERN)) -> QualityReviewOut:
    raise NotImplementedYetError


# --- QA encadenada (provisional) -----------------------------------------------------------------


@qa.get(
    "/handoffs",
    response_model=list[HandoffOut],
    summary="HU aprobadas listas para preparar pruebas (rol QA)",
    responses={200: _json(ex.dump(ex.HANDOFFS)), **AUTH},
)
def list_handoffs() -> list[HandoffOut]:
    raise NotImplementedYetError


@qa.post(
    "/handoffs/{handoff_id}/take",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recoger una HU y empezar su conversación de QA",
    responses={202: _json(ex.dump(ex.CONVERSATION_QA)), **AUTH, **NOT_FOUND},
)
def take_handoff(handoff_id: str = Path(pattern=ID_PATTERN)) -> ConversationOut:
    raise NotImplementedYetError


# --- Ajustes de la sesión ------------------------------------------------------------------------


@settings.get(
    "",
    response_model=SettingsOut,
    summary="Modo de publicación y modelos por tarea",
    responses={200: _json(ex.dump(ex.SETTINGS)), **AUTH},
)
def get_settings() -> SettingsOut:
    raise NotImplementedYetError


@settings.put(
    "/models/{task}",
    response_model=TaskModelsOut,
    summary="Cambiar el modelo de una tarea en la sesión (RF-42)",
    responses={200: _json(ex.dump(ex.SETTINGS.tasks[0])), **AUTH, **NOT_FOUND},
)
def override_model(body: ModelOverrideIn, task: str = Path(max_length=50)) -> TaskModelsOut:
    raise NotImplementedYetError


@settings.delete(
    "/models/{task}",
    response_model=TaskModelsOut,
    summary="Volver a «Modelo automático» en una tarea (quita el cambio de la sesión)",
    responses={200: _json(ex.dump(ex.SETTINGS.tasks[0])), **AUTH, **NOT_FOUND},
)
def clear_model_override(task: str = Path(max_length=50)) -> TaskModelsOut:
    raise NotImplementedYetError


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agente de IA de Análisis Funcional y QA",
        version=VERSION,
        description="API para el frontend propio (T-55). Sesión con cookie HttpOnly "
        "`afqa_session` y cabecera `X-CSRF-Token` en las peticiones que modifican algo.",
    )
    for router in (auth, projects, start, conversations, quality, qa, settings):
        app.include_router(router, prefix=API_PREFIX)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Any, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=ex.error("invalid_request", _validation_message(exc))
        )

    @app.exception_handler(NotImplementedYetError)
    async def _not_yet(_request: Any, _exc: NotImplementedYetError) -> JSONResponse:
        return JSONResponse(status_code=501, content=ex.error("not_implemented", NOT_YET))

    return app


app = create_app()


def _validation_message(exc: RequestValidationError) -> str:
    """Mensaje del 422 sin `input` ni valores: nunca devuelve lo enviado (p. ej. la contraseña).

    Los validadores de modelo (p. ej. flujo frente a origen) ya dan un mensaje propio en español;
    para el resto se nombran los campos.
    """
    errors = exc.errors()
    if any(e.get("type") == "json_invalid" for e in errors):
        return "El cuerpo de la petición no es un JSON válido."
    messages: list[str] = []
    fields: set[str] = set()
    for error in errors:
        path = [str(p) for p in error.get("loc", ())[1:] if not isinstance(p, int)]
        if not path and error.get("type") == "value_error":
            messages.append(str(error.get("msg", "")).removeprefix("Value error, "))
        elif path:
            fields.add(".".join(path))
    if messages:
        return " ".join(dict.fromkeys(m for m in messages if m))
    if fields:
        return f"La petición no es válida: revisa {', '.join(sorted(fields)[:8])}."
    return "La petición no es válida."
