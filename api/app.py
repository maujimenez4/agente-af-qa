"""Aplicación FastAPI y rutas del contrato (T-55).

Parte 1: el contrato completo (rutas, modelos, errores y ejemplos). Parte 2: las rutas sobre el
contenedor y el grafo (`api/service.py`), con sesión en el servidor (`api/sessions.py`) y las
comprobaciones de `docs/api/requisitos-parte-2.md` (`api/security.py`). QA encadenada (T-54,
PA-105): `/conversations/{id}/handoff` y `/qa/handoffs` sobre `core/handoff.py`.

Sesión: cookie HttpOnly `afqa_session` (SameSite=Strict) que el frontend no ve; toda petición que
modifica algo lleva además la cabecera `X-CSRF-Token` con el valor de `SessionOut.csrf_token`.
Las operaciones largas (generar, iterar, aprobar y publicar, revisar la calidad) responden 202
y su avance se sigue con eventos SSE o consultando el estado.
"""

import asyncio
import json
import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, FastAPI, Path, Query, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import Receive, Scope, Send

from adapters.base import TaskType, User
from adapters.errors import AgentError, NotFoundError
from adapters.llm.router import ModelChoice
from api import examples as ex
from api import executions, service
from api.errors import UNEXPECTED, ApiError, to_api_error
from api.models import (
    HANDOFF_ID_PATTERN,
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
    ExecutionCreateIn,
    ExecutionOut,
    ExecutionResultsIn,
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
    UsageTodayOut,
    UserOut,
)
from api.runtime import QualityJob, Runtime, Workspace, build_runtime
from api.security import (
    COOKIE,
    COOKIE_PATH,
    BodyLimitMiddleware,
    CatchAllMiddleware,
    RequestLogMiddleware,
    RuntimeHolder,
    SecurityHeadersMiddleware,
    Session,
    SessionGuardMiddleware,
    check_origin,
    client_ip,
    current_session,
    runtime,
    session_for,
)
from core.config import Settings
from core.context.jql import text_search_jql
from core.guided_start import GuidedStart
from core.logging import get_logger
from core.permissions import Permission, permissions_of, require
from core.projects import ISSUE_KEY, normalize_issue_key, normalize_project_key, project_of
from core.quality import REVIEW_PERMISSION, QualityReviewer

log = get_logger("api")

API_PREFIX = "/api/v1"
LOGIN_PATH = f"{API_PREFIX}/auth/login"
VERSION = "0.2.0"
MAX_QUALITY_JOBS = 20  # por persona
SSE_POLL_S = 0.5
SSE_HEARTBEAT_S = 15.0
# Tipos que no se buscan como origen (las épicas sí).
NOT_SEARCHABLE = frozenset({"subtarea", "sub-task", "subtask", "task", "tarea"})


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
# Respuestas que puede dar cualquier ruta (cuerpo demasiado grande, error inesperado y la API
# sin poder arrancar: BD caída o `.env` inválido).
COMMON = {
    413: _err("payload_too_large", "La petición es demasiado grande.", "Cuerpo de más de 256 KB."),
    500: _err(
        "unexpected",
        "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.",
        "Error no previsto (sin detalles internos).",
    ),
    **UNAVAILABLE,
}
# Toda ruta con sesión puede leer de Jira o llamar al LLM: también puede dar 429.
AUTH = {**UNAUTHORIZED, **FORBIDDEN, **RATE_LIMITED, **COMMON}
HANDOFF_CONFLICT = {
    409: _err(
        "handoff_unavailable",
        "Esa HU ya no está disponible para QA: puede que la haya recogido otra persona.",
        "Ya recogida por otra persona, o la HU no está aprobada o no coincide con la aprobada.",
    ),
}

auth = APIRouter(prefix="/auth", tags=["Sesión"])
projects = APIRouter(tags=["Proyectos y Jira"])
start = APIRouter(prefix="/start", tags=["Arranque guiado"])
conversations = APIRouter(prefix="/conversations", tags=["Conversaciones"])
quality = APIRouter(prefix="/quality-reviews", tags=["Revisar la calidad"])
qa = APIRouter(prefix="/qa", tags=["QA encadenada (T-54)"])
executions_router = APIRouter(prefix="/executions", tags=["Registrar la ejecución (QA 6)"])
settings_router = APIRouter(prefix="/settings", tags=["Ajustes de la sesión"])

ConversationId = Path(description="Identificador de la conversación.", pattern=ID_PATTERN)


def _ctx(request: Request) -> tuple[Runtime, Session, Workspace, User]:
    """Runtime, sesión (con CSRF si modifica algo), espacio de trabajo y persona."""
    session = session_for(request)
    return runtime(request), session, session.workspace, session.user


def _session_out(session: Session) -> SessionOut:
    user = session.user
    return SessionOut(
        user=UserOut(
            username=user.username,
            role=user.role,
            permissions=sorted(p.value for p in permissions_of(user)),
        ),
        csrf_token=session.csrf_token,
    )


def _set_cookie(response: Response, session_id: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE,
        session_id,
        max_age=settings.api_session_max_hours * 3600,
        path=COOKIE_PATH,
        secure=settings.api_cookie_secure,
        httponly=True,
        samesite="strict",
    )


# --- Sesión -------------------------------------------------------------------------------------


@auth.post(
    "/login",
    response_model=SessionOut,
    summary="Iniciar sesión",
    description="Crea la cookie de sesión HttpOnly y devuelve el usuario y el token anti-CSRF.",
    responses={
        200: _json(ex.dump(ex.SESSION)),
        401: _err("invalid_credentials", "Usuario o contraseña incorrectos.", "Credenciales."),
        403: _err(
            "forbidden",
            "La petición no viene de un origen permitido.",
            "`Origin`/`Referer` que no es el mismo origen ni está en la lista permitida.",
        ),
        429: _err("too_many_attempts", "Demasiados intentos; espera unos minutos.", "Intentos."),
        **COMMON,
    },
)
def login(body: LoginIn, request: Request, response: Response) -> SessionOut:
    rt = runtime(request)
    check_origin(request, rt.settings.api_origins)
    user_key, ip_key = f"user:{body.username.strip().lower()}", f"ip:{client_ip(request)}"
    if (wait := rt.limiter.retry_after(user_key, ip_key)) is not None:
        raise ApiError(429, "too_many_attempts", "Demasiados intentos; espera unos minutos.", wait)
    user = rt.auth.authenticate(body.username, body.password)
    if user is None:
        rt.limiter.failure(user_key, ip_key)
        log.info("login fallido", action="login_failed")
        raise ApiError(401, "invalid_credentials", "Usuario o contraseña incorrectos.")
    rt.limiter.success(user_key)
    if previous := request.cookies.get(COOKIE):
        rt.sessions.drop(previous)  # rotación: nunca se reutiliza un identificador anterior
    session = rt.sessions.create(user, rt.workspace_factory())
    _set_cookie(response, session.id, rt.settings)
    request.state.user = user.username
    log.info("login", user=user.username, action="login")
    return _session_out(session)


@auth.post("/logout", status_code=204, summary="Cerrar sesión", responses=AUTH)
def logout(request: Request, response: Response) -> None:
    rt, session, _ws, user = _ctx(request)
    rt.sessions.drop(session.id)
    response.delete_cookie(
        COOKIE,
        path=COOKIE_PATH,
        secure=runtime(request).settings.api_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    log.info("logout", user=user.username, action="logout")


@auth.get(
    "/me",
    response_model=SessionOut,
    summary="Sesión actual",
    description="Al recargar la página: usuario y el token anti-CSRF de la sesión.",
    responses={200: _json(ex.dump(ex.SESSION)), **UNAUTHORIZED, **COMMON},
)
def me(request: Request) -> SessionOut:
    return _session_out(current_session(request))


# --- Proyectos y Jira ----------------------------------------------------------------------------


@projects.get(
    "/projects",
    response_model=ProjectsOut,
    summary="Proyectos que ve la conexión y el preseleccionado (T-50)",
    responses={200: _json(ex.dump(ex.PROJECTS)), **AUTH, **UNAVAILABLE},
)
def list_projects(request: Request) -> ProjectsOut:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    choice = ws.container.projects.available(user.username)
    return ProjectsOut(projects=choice.projects, preselected=choice.preselected)


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
def choose_project(body: ChooseProjectIn, request: Request) -> ChooseProjectOut:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    try:
        project = ws.container.projects.choose(user.username, body.project)
    except NotFoundError as exc:
        raise ApiError(404, "project_not_found", str(exc)) from None
    return ChooseProjectOut(project=project)


@projects.get(
    "/projects/{project}/epics",
    response_model=list[IssueSummary],
    summary="Épicas del proyecto (Elegir en Jira)",
    responses={200: _json(ex.dump(ex.EPICS)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def list_epics(
    request: Request, project: str = Path(pattern=PROJECT_PATTERN)
) -> list[IssueSummary]:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    return ws.container.issue_tracker.list_epics(normalize_project_key(project))


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
    *,
    request: Request,
) -> list[IssueSummary]:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    project = normalize_project_key(project)
    tracker = ws.container.issue_tracker
    text = (q or "").strip()
    if text and ISSUE_KEY.fullmatch(text.upper()):
        key = normalize_issue_key(text)
        if project_of(key) != project:
            return []
        try:
            issue = tracker.get_issue(key)
        except NotFoundError:
            return []
        found = [
            IssueSummary.model_validate(issue.model_dump(include=set(IssueSummary.model_fields)))
        ]
    elif text:
        found = tracker.search(text_search_jql(project, text), limit=limit)  # texto escapado
    else:
        # `project` ya está validado (`normalize_project_key`): no hay texto libre en la JQL.
        found = tracker.search(f'project = "{project}" ORDER BY updated DESC', limit=limit)
    return [i for i in found if i.issue_type.strip().lower() not in NOT_SEARCHABLE][:limit]


@projects.get(
    "/epics/{key}/stories",
    response_model=list[IssueSummary],
    summary="HU de una épica",
    responses={200: _json(ex.dump(ex.STORIES)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def list_children(request: Request, key: str = Path(pattern=KEY_PATTERN)) -> list[IssueSummary]:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    return ws.container.issue_tracker.list_children(normalize_issue_key(key))


@projects.get(
    "/issues/{key}",
    response_model=IssueCard,
    summary="Ficha de una incidencia (tarjetas de HU parecida o clave reconocida)",
    responses={200: _json(ex.dump(ex.CARD)), **AUTH, **NOT_FOUND, **UNAVAILABLE},
)
def issue_card(request: Request, key: str = Path(pattern=KEY_PATTERN)) -> IssueCard:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    issue = ws.container.issue_tracker.get_issue(normalize_issue_key(key))
    criteria, rules = service.count_ids(issue.description_text or "")  # sin IA
    return IssueCard(
        key=issue.key,
        project=project_of(issue.key),
        summary=issue.summary,
        issue_type=issue.issue_type,
        status=issue.status,
        epic_key=issue.parent_key,
        criteria_count=criteria,
        rules_count=rules,
    )


# --- Arranque guiado -----------------------------------------------------------------------------


@start.post(
    "/propose",
    response_model=StartProposal,
    summary="Proponer con qué empezar a partir del texto (sin IA, T-53)",
    description="Claves de Jira en el texto (también en minúsculas, si existen) o HU parecidas. "
    "Si `project_changed`, avisar; si `ignored_projects` no está vacío, avisar también.",
    responses={200: _json(ex.dump(ex.PROPOSAL)), **AUTH, **UNAVAILABLE},
)
def propose(body: ProposeIn, request: Request) -> StartProposal:
    _rt, _s, ws, user = _ctx(request)
    require(user, service.generate_permission(body.mode))
    return GuidedStart(ws.container).propose(body.text, body.project, body.mode)


@start.post(
    "/sources",
    response_model=list[SourcePreview],
    summary="Fuentes que usaría la propuesta (panel «Antes de generar»)",
    description="Las desmarcadas van en `excluded_sources` al crear la conversación; la fila "
    "`required` (la incidencia de origen) no se puede desmarcar.",
    responses={
        200: _json(ex.dump(ex.SOURCES)),
        **AUTH,
        404: _err(
            "not_found",
            "La incidencia DEMO-999 no existe.",
            "Incidencia de origen que no existe o no ve la conexión.",
        ),
    },
)
def sources(body: SourcesIn, request: Request) -> list[SourcePreview]:
    _rt, _s, ws, user = _ctx(request)
    require(user, Permission.VIEW_CONTEXT)
    origin = service.preview_origin(body.origin)
    excluded = service.excluded_for(body.excluded_sources, origin.get("key"))
    return GuidedStart(ws.container).preview_sources(origin, excluded)


# --- Conversaciones ------------------------------------------------------------------------------


@conversations.get(
    "",
    response_model=list[ConversationSummary],
    summary="Conversaciones de la persona (más recientes primero)",
    responses={200: _json(ex.dump(ex.CONVERSATIONS)), **AUTH},
)
def list_conversations(
    request: Request, limit: int = Query(default=50, ge=1, le=100)
) -> list[ConversationSummary]:
    _rt, _s, ws, user = _ctx(request)
    return ws.container.conversations.list_for(user.username, limit)


@conversations.post(
    "",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Crear una conversación y empezar a generar",
    description="Responde 202 con `state=generating`; el avance llega por `/events` o "
    "consultando la conversación. El `id` lo genera el servidor.",
    responses={
        202: _json(ex.dump(ex.CONVERSATION_GENERATING)),
        **AUTH,
        404: _err(
            "not_found",
            "El proyecto DEMO no existe o la conexión no tiene acceso a él.",
            "Proyecto que no ve la conexión de Jira, o incidencia de origen que no existe.",
        ),
        **RATE_LIMITED,
    },
)
def create_conversation(body: ConversationCreateIn, request: Request) -> ConversationOut:
    rt, _s, ws, user = _ctx(request)
    run = service.create_conversation(rt, ws, user, body)
    return service.conversation_out(rt, ws, user, run.thread_id)


@conversations.get(
    "/{conversation_id}",
    response_model=ConversationOut,
    summary="Estado completo de una conversación",
    description="Progreso, propuesta en revisión (con `plan`, `fingerprint` y `error`), "
    "versiones y resultado. Sirve también para retomarla.",
    responses={200: _json(ex.dump(ex.CONVERSATION)), **AUTH, **NOT_FOUND},
)
def get_conversation(request: Request, conversation_id: str = ConversationId) -> ConversationOut:
    rt, _s, ws, user = _ctx(request)
    return service.conversation_out(rt, ws, user, conversation_id)


@conversations.get(
    "/{conversation_id}/events",
    response_class=StreamingResponse,
    summary="Eventos en vivo (SSE)",
    description="`text/event-stream`. Eventos: `progress` (`data`: un `ProgressStep` completo), "
    "`review_ready`, `result` (publicación simulada, real o parcial, o descarte) y `error` "
    "(`data`: la conversación completa, como en `GET /conversations/{id}`; si falla la lectura "
    "a mitad del flujo, la última conocida con `state=error` y `error`). El servidor cierra "
    "el flujo tras `result` de una conversación terminada: ciérralo también en el cliente para "
    "que `EventSource` no reconecte. Hay un comentario `: ping` cada 15 s. Si se corta, basta "
    "con consultar el estado.",
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: progress\ndata: {"node": "generate", "label": '
                    '"Generar la propuesta, validar las citas y analizar el impacto", '
                    '"state": "running"}\n\n'
                    'event: review_ready\ndata: {"id": "' + ex.THREAD_ID + '", "state": '
                    '"in_review"}\n\n'
                }
            }
        },
        **AUTH,
        **NOT_FOUND,
        429: _err(
            "too_many_streams",
            "Tienes demasiadas pestañas siguiendo conversaciones.",
            "Límite de flujos SSE abiertos por persona (3).",
        ),
    },
)
async def events(request: Request, conversation_id: str = ConversationId) -> StreamingResponse:
    rt, session, ws, user = _ctx(request)
    # Propiedad comprobada antes de abrir el flujo (404 idéntico si no existe o no es suya).
    first = await run_in_threadpool(service.conversation_out, rt, ws, user, conversation_id)
    if not rt.sessions.open_stream(session, rt.settings.api_max_streams_per_user):
        raise ApiError(
            429, "too_many_streams", "Tienes demasiadas pestañas siguiendo conversaciones."
        )
    released = False

    def release() -> None:
        """Libera la plaza una sola vez: al acabar el flujo o, si el cliente se va antes de
        que el generador arranque, en la tarea de fondo de la respuesta."""
        nonlocal released
        if not released:
            released = True
            rt.sessions.close_stream(session)

    stream = _event_stream(request, rt, session, conversation_id, first, release)
    return _ReleasingStream(stream, release)


class _ReleasingStream(StreamingResponse):
    """SSE que libera la plaza al terminar la respuesta pase lo que pase (también si el cliente
    se va antes de que el generador arranque o si `send` falla con el socket cerrado)."""

    def __init__(self, content: AsyncIterator[str], on_close: Callable[[], None]) -> None:
        super().__init__(content, media_type="text/event-stream")
        self._content, self._on_close = content, on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        except ClientDisconnect:
            pass  # la persona cerró la pestaña: no es un error
        finally:
            self._on_close()
            aclose = getattr(self._content, "aclose", None)
            if aclose is not None:
                await aclose()  # cierra el generador aunque no haya llegado a arrancar


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _event_stream(
    request: Request,
    rt: Runtime,
    session: Session,
    thread_id: str,
    first: ConversationOut,
    release: Callable[[], None],
) -> AsyncIterator[str]:
    """Eventos SSE: `progress` por paso que cambia y uno final (`review_ready`, `result`, `error`).

    Se cierra al desconectarse, al caducar la sesión o cuando la conversación termina.
    """
    ws, user = session.workspace, session.user
    steps: dict[str, str] = {}
    last_seq, last_final, waited = -1, "", 0.0
    out: ConversationOut | None = first
    last: ConversationOut = first
    try:
        while True:
            if await request.is_disconnected() or not rt.sessions.alive(session):
                return
            run = rt.runs.get(thread_id)
            seq = run.seq if run else 0
            if seq != last_seq:
                last_seq, waited = seq, 0.0
                if out is None:
                    try:
                        out = await run_in_threadpool(
                            service.conversation_out, rt, ws, user, thread_id
                        )
                    except Exception as exc:  # mensaje con lista blanca, sin trazas
                        # Contrato: `data` es la conversación; la última conocida, en error.
                        failed = last.model_copy(
                            update={"state": "error", "error": to_api_error(exc).body}
                        )
                        yield _sse("error", failed.model_dump(mode="json"))
                        return
                for step in out.progress:
                    if steps.get(step.node) != step.state:
                        steps[step.node] = step.state
                        yield _sse("progress", step.model_dump())  # PA-307
                final = {"in_review": "review_ready", "error": "error"}.get(out.state)
                if out.state in ("simulated", "published", "discarded") or out.result:
                    final = "result"
                marker = f"{final}:{out.updated_at.isoformat()}"
                if final and out.state != "generating" and marker != last_final:
                    last_final = marker
                    yield _sse(final, out.model_dump(mode="json"))
                if out.state in ("simulated", "published", "discarded"):
                    return
                last, out = out, None
            elif waited >= SSE_HEARTBEAT_S:
                waited = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(SSE_POLL_S)
            waited += SSE_POLL_S
    finally:
        release()


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
def iterate(
    body: IterateIn, request: Request, conversation_id: str = ConversationId
) -> ConversationOut:
    _ctx(request)  # PA-162: sesión, origen y CSRF antes de validar el feedback
    return _resume(request, conversation_id, "iterate", service.iterate_answer(body.feedback))


def _resume(
    request: Request, conversation_id: str, operation: str, answer: dict[str, Any]
) -> ConversationOut:
    rt, _s, ws, user = _ctx(request)
    service.resume(rt, ws, user, conversation_id, operation, answer)
    return service.conversation_out(rt, ws, user, conversation_id)


@conversations.post(
    "/{conversation_id}/edit",
    response_model=ConversationOut,
    summary="Editar a mano (RF-32): versión nueva con su huella",
    description="`fingerprint` es la del payload mostrado. Una edición inválida no da error HTTP:"
    " la revisión sigue con `review.error` (UI.md §5).",
    responses={200: _json(ex.dump(ex.CONVERSATION)), **AUTH, **NOT_FOUND, **NOT_IN_REVIEW},
)
def edit(body: EditIn, request: Request, conversation_id: str = ConversationId) -> ConversationOut:
    answer: dict[str, Any] = {
        "decision": "edit",
        "content": body.content.model_dump(mode="json"),
        "fingerprint": body.fingerprint,
    }
    if body.feedback:
        answer["feedback"] = body.feedback
    return _resume(request, conversation_id, "edit", answer)


@conversations.post(
    "/{conversation_id}/approve",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Aprobar y publicar (simulación o real)",
    description="Con la `fingerprint` exacta del último payload. Si no casa, la revisión sigue "
    "con `review.error`. Un rechazo del registro de aprobaciones da 409 `approval_rejected` y "
    "obliga a empezar de nuevo; si la conversación no está en revisión o ya hay una operación "
    "en curso, 409 `not_in_review` (como en `iterate`).",
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
def approve(
    body: ApproveIn, request: Request, conversation_id: str = ConversationId
) -> ConversationOut:
    # Solo reanuda el grafo con la huella: `publish` comprueba la aprobación en el registro.
    answer = {"decision": "approve", "fingerprint": body.fingerprint}
    return _resume(request, conversation_id, "approve", answer)


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
def discard(request: Request, conversation_id: str = ConversationId) -> ConversationOut:
    return _resume(request, conversation_id, "discard", {"decision": "discard"})


@conversations.post(
    "/{conversation_id}/handoff",
    response_model=HandoffOut,
    summary="Pasar la HU aprobada o publicada a QA (T-54)",
    description="Deja la HU de esta conversación (aprobada, simulada o publicada) en la lista de "
    "QA. La HU sale del servidor, nunca de la petición. Sin clave de Jira (aprobada en "
    "simulación), QA puede generar y revisar casos pero no publicarlos. Repetirlo es idempotente. "
    "Si la conversación tiene una operación en curso, 409 `not_in_review`.",
    responses={
        200: _json(ex.dump(ex.HANDOFFS[0])),
        **AUTH,
        **NOT_FOUND,
        **HANDOFF_CONFLICT,
    },
)
def handoff(request: Request, conversation_id: str = ConversationId) -> HandoffOut:
    rt, _s, ws, user = _ctx(request)
    return service.pass_to_qa(rt, ws, user, conversation_id)


# --- Revisar la calidad --------------------------------------------------------------------------


@quality.post(
    "",
    response_model=QualityReviewOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Revisar la calidad de una HU (T-48, no publica)",
    description="Responde 202 con `state=running`. Una HU que no existe o un límite del LLM "
    "llegan después en `state=error` con `error` (consultando la revisión).",
    responses={202: _json(ex.dump(ex.QUALITY)), **AUTH},
)
def create_quality_review(body: QualityReviewIn, request: Request) -> QualityReviewOut:
    rt, _s, ws, user = _ctx(request)
    require(user, REVIEW_PERMISSION)
    key = normalize_issue_key(body.issue_key)
    excluded = service.excluded_for(body.excluded_sources, key)
    job = QualityJob(id=str(uuid4()), owner=user.username, issue_key=key)
    _keep_quality_job(rt, job)
    rt.submit(_quality_task(ws, user, job, excluded))
    return _quality_out(job)


def _keep_quality_job(rt: Runtime, job: QualityJob) -> None:
    """Guarda la revisión; cada persona conserva sus `MAX_QUALITY_JOBS` más recientes."""
    with rt.quality_lock:
        rt.quality[job.id] = job
        mine = [jid for jid, j in rt.quality.items() if j.owner == job.owner]
        for old in mine[:-MAX_QUALITY_JOBS]:  # las más antiguas salen primero
            del rt.quality[old]


def _quality_job(rt: Runtime, review_id: str) -> QualityJob | None:
    with rt.quality_lock:
        return rt.quality.get(review_id)


def _quality_task(
    ws: Workspace, user: User, job: QualityJob, excluded: list[str]
) -> Callable[[], None]:
    def task() -> None:
        try:
            job.result = QualityReviewer(ws.container).review(user, job.issue_key, excluded)
            job.state = "done"
        except Exception as exc:  # mensaje con lista blanca; el tipo va al log
            job.error, job.state = to_api_error(exc).body, "error"
            log.warning(
                "error al revisar la calidad",
                user=user.username,
                action="review_quality",
                error_type=type(exc).__name__,
            )

    return task


def _quality_out(job: QualityJob) -> QualityReviewOut:
    result = job.result
    return QualityReviewOut(
        id=job.id,
        issue_key=job.issue_key,
        state=job.state,  # type: ignore[arg-type]
        report=result.report if result else None,
        evolve_feedback=result.evolve_feedback() if result else [],
        report_markdown=result.report.to_markdown(job.issue_key) if result else None,
        error=job.error,
    )


@quality.get(
    "/{review_id}",
    response_model=QualityReviewOut,
    summary="Estado e informe de una revisión de calidad",
    description="`report` se pinta campo a campo como texto; `report_markdown` es solo para "
    "descargarlo.",
    responses={200: _json(ex.dump(ex.QUALITY)), **AUTH, **NOT_FOUND},
)
def get_quality_review(
    request: Request, review_id: str = Path(pattern=ID_PATTERN)
) -> QualityReviewOut:
    rt, _s, _ws, user = _ctx(request)
    job = _quality_job(rt, review_id)
    if job is None or job.owner != user.username:
        raise ApiError(404, "not_found", "No existe esa revisión o no es tuya.")
    return _quality_out(job)


# --- Registrar la ejecución (QA 6, T-47) ---------------------------------------------------------

ExecutionId = Path(description="Identificador del registro de la ejecución.", pattern=ID_PATTERN)
EXECUTION_NOT_IN_REVIEW = {
    409: _err(
        "not_in_review",
        executions.NOT_IN_REVIEW_EXECUTION.message,
        "El registro no está en revisión o hay otra operación en curso.",
    ),
}
EXECUTION_NOT_FOUND = {
    404: _err(
        "not_found",
        "No existe ese registro o no es tuyo.",
        "No existe o no pertenece a la persona (mismo mensaje en los dos casos).",
    ),
}


@executions_router.post(
    "",
    response_model=ExecutionOut,
    summary="Empezar a registrar la ejecución de las pruebas de una HU",
    description="Lee de Jira las subtareas CP de la HU (su suite tiene que estar publicada) y "
    "devuelve el registro en revisión, sin resultados. Nada se escribe en Jira.",
    responses={
        200: _json(ex.dump(ex.EXECUTION.model_copy(update={"results": [], "plan": []}))),
        **AUTH,
        404: _err("not_found", "La incidencia DEMO-999 no existe.", "HU que no existe."),
        409: _err(
            "publish_failed",
            "La HU DEMO-3 no tiene casos de prueba publicados en Jira: publica antes su suite.",
            "La HU no tiene subtareas CP.",
        ),
    },
)
def create_execution(body: ExecutionCreateIn, request: Request) -> ExecutionOut:
    rt, _s, ws, user = _ctx(request)
    thread_id = executions.create(rt, ws, user, body.story_key)
    return executions.describe(rt, ws, user, thread_id)


@executions_router.get(
    "/{execution_id}",
    response_model=ExecutionOut,
    summary="Estado del registro de la ejecución (recibo, huella y resultado)",
    responses={200: _json(ex.dump(ex.EXECUTION)), **AUTH, **EXECUTION_NOT_FOUND},
)
def get_execution(request: Request, execution_id: str = ExecutionId) -> ExecutionOut:
    rt, _s, ws, user = _ctx(request)
    return executions.describe(rt, ws, user, execution_id)


@executions_router.put(
    "/{execution_id}/results",
    response_model=ExecutionOut,
    summary="Guardar el borrador de resultados (nada se escribe en Jira)",
    description="Sustituye los resultados y el entorno. Un resultado no válido (caso ajeno, "
    "«fallo» sin evidencia…) no da error HTTP: el registro sigue en revisión con "
    "`review_error`. Cada guardado cambia la `fingerprint`.",
    responses={
        200: _json(ex.dump(ex.EXECUTION)),
        **AUTH,
        **EXECUTION_NOT_FOUND,
        **EXECUTION_NOT_IN_REVIEW,
    },
)
def save_execution(
    body: ExecutionResultsIn, request: Request, execution_id: str = ExecutionId
) -> ExecutionOut:
    rt, _s, ws, user = _ctx(request)
    executions.save(rt, ws, user, execution_id, body)
    return executions.describe(rt, ws, user, execution_id)


@executions_router.post(
    "/{execution_id}/approve",
    response_model=ExecutionOut,
    summary="Aprobar el recibo y registrar en Jira",
    description="Con la `fingerprint` exacta del último registro mostrado. Si no casa, sigue en "
    "revisión con `review_error`. Escribe en cada subtarea (transición, etiqueta y comentario con "
    "la evidencia); las que fallan quedan en `outcome.failed` (`state=partial`).",
    responses={
        200: _json(ex.dump(ex.EXECUTION_RECORDED)),
        **AUTH,
        **EXECUTION_NOT_FOUND,
        **EXECUTION_NOT_IN_REVIEW,
    },
)
def approve_execution(
    body: ApproveIn, request: Request, execution_id: str = ExecutionId
) -> ExecutionOut:
    rt, _s, ws, user = _ctx(request)
    executions.approve(rt, ws, user, execution_id, body.fingerprint)
    return executions.describe(rt, ws, user, execution_id)


@executions_router.post(
    "/{execution_id}/discard",
    response_model=ExecutionOut,
    summary="Descartar el registro (nada se escribe en Jira)",
    responses={
        200: _json(
            ex.dump(
                ex.EXECUTION.model_copy(
                    update={"state": "discarded", "plan": [], "fingerprint": None}
                )
            )
        ),
        **AUTH,
        **EXECUTION_NOT_FOUND,
        **EXECUTION_NOT_IN_REVIEW,
    },
)
def discard_execution(request: Request, execution_id: str = ExecutionId) -> ExecutionOut:
    rt, _s, ws, user = _ctx(request)
    executions.discard(rt, ws, user, execution_id)
    return executions.describe(rt, ws, user, execution_id)


# --- QA encadenada (T-54) -----------------------------------------------------------------------


@qa.get(
    "/handoffs",
    response_model=list[HandoffOut],
    summary="HU aprobadas listas para preparar pruebas (rol QA)",
    description="Cualquier persona con rol QA las ve (D-01); solo las de los proyectos que ve la "
    "conexión de Jira.",
    responses={200: _json(ex.dump(ex.HANDOFFS)), **AUTH},
)
def list_handoffs(request: Request) -> list[HandoffOut]:
    rt, _s, ws, user = _ctx(request)
    return service.pending_handoffs(rt, ws, user)


@qa.post(
    "/handoffs/{handoff_id}/take",
    response_model=ConversationOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Recoger una HU y empezar su conversación de QA",
    description="Solo una persona puede recogerla: si ya la recogió otra, 409 "
    "`handoff_unavailable`. Responde 202 con la conversación de QA generando; el avance llega "
    "por `/conversations/{id}/events`. No relee Jira ni vuelve a estructurar la HU.",
    responses={202: _json(ex.dump(ex.CONVERSATION_QA)), **AUTH, **HANDOFF_CONFLICT},
)
def take_handoff(
    request: Request, handoff_id: str = Path(pattern=HANDOFF_ID_PATTERN)
) -> ConversationOut:
    rt, _s, ws, user = _ctx(request)
    run = service.take(rt, ws, user, handoff_id)
    return service.conversation_out(rt, ws, user, run.thread_id)


# --- Ajustes de la sesión ------------------------------------------------------------------------


@settings_router.get(
    "",
    response_model=SettingsOut,
    summary="Modo de publicación y modelos por tarea",
    responses={200: _json(ex.dump(ex.SETTINGS)), **AUTH},
)
def get_settings(request: Request) -> SettingsOut:
    _rt, _s, ws, _user = _ctx(request)
    return SettingsOut(
        publish_mode=ws.container.publish_mode,
        tasks=[service.task_models(ws, task) for task in TaskType],
    )


@settings_router.get(
    "/usage",
    response_model=UsageTodayOut,
    summary="Consumo de tokens de hoy (anillo del carril, PA-305)",
    description="Consumo de toda la instalación: el registro de uso no guarda la persona.",
    responses={
        200: _json({"tokens_today": 42000, "warning_threshold": 180000, "scope": "global"}),
        **AUTH,
    },
)
def usage_today(request: Request) -> UsageTodayOut:
    rt, _s, _ws, _user = _ctx(request)
    if rt.usage is None:
        raise ApiError(503, "service_unavailable", "El registro de consumo no está disponible.")
    try:
        tokens = service.tokens_today(rt.usage)
    except SQLAlchemyError:  # `core/usage` no envuelve los errores de la BD
        raise ApiError(503, "service_unavailable", "No se pudo leer el consumo de hoy.") from None
    return UsageTodayOut(tokens_today=tokens, warning_threshold=rt.token_warning)


@settings_router.put(
    "/models/{task}",
    response_model=TaskModelsOut,
    summary="Cambiar el modelo de una tarea en la sesión (RF-42)",
    responses={200: _json(ex.dump(ex.SETTINGS.tasks[0])), **AUTH, **NOT_FOUND},
)
def override_model(
    body: ModelOverrideIn, request: Request, task: str = Path(max_length=50)
) -> TaskModelsOut:
    _rt, _s, ws, user = _ctx(request)
    task_type = service.task_type(task)
    choice = ModelChoice(body.provider, body.model)
    service.set_override(ws, task_type, choice)
    log.info(
        "modelo elegido",
        user=user.username,
        action="override_model",
        model=f"{choice.provider}/{choice.model}",
    )
    return service.task_models(ws, task_type)


@settings_router.delete(
    "/models/{task}",
    response_model=TaskModelsOut,
    summary="Volver a «Modelo automático» en una tarea (quita el cambio de la sesión)",
    responses={200: _json(ex.dump(ex.SETTINGS.tasks[0])), **AUTH, **NOT_FOUND},
)
def clear_model_override(request: Request, task: str = Path(max_length=50)) -> TaskModelsOut:
    _rt, _s, ws, _user = _ctx(request)
    task_type = service.task_type(task)
    service.clear_override(ws, task_type)
    return service.task_models(ws, task_type)


def _error_response(error: ApiError) -> JSONResponse:
    headers = {"Retry-After": str(math.ceil(error.retry_after))} if error.retry_after else None
    return JSONResponse(
        status_code=error.status,
        content={"error": error.body.model_dump()},
        headers=headers,
    )


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    response = _error_response(
        ApiError(413, "payload_too_large", "La petición es demasiado grande.")
    )
    await response(scope, receive, send)


async def _unexpected(scope: Scope, receive: Receive, send: Send) -> None:
    response = _error_response(ApiError(500, "unexpected", UNEXPECTED))
    await response(scope, receive, send)


def create_app(
    runtime_factory: Callable[[], Runtime] = build_runtime,
    *,
    settings: Settings | None = None,
    runtime_instance: Runtime | None = None,
) -> FastAPI:
    """Aplicación FastAPI. La composición real se hace en la primera petición (`build_runtime`).

    Las pruebas pasan `runtime_instance` con fakes; `settings` decide `/docs` y CORS.
    """
    settings = settings or (runtime_instance.settings if runtime_instance else Settings())
    development = settings.is_development
    holder = RuntimeHolder(runtime_factory, runtime_instance)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if (ready := holder.ready) is not None:
            ready.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title="Agente de IA de Análisis Funcional y QA",
        version=VERSION,
        description="API para el frontend propio (T-55). Sesión con cookie HttpOnly "
        "`afqa_session` y cabecera `X-CSRF-Token` en las peticiones que modifican algo.",
        docs_url="/api/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if development else None,
    )
    app.state.runtime = holder
    for router in (
        auth,
        projects,
        start,
        conversations,
        quality,
        executions_router,
        qa,
        settings_router,
    ):
        app.include_router(router, prefix=API_PREFIX)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Any, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=ex.error("invalid_request", _validation_message(exc))
        )

    @app.exception_handler(ApiError)
    async def _api_error(_request: Any, exc: ApiError) -> JSONResponse:
        return _error_response(exc)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Any, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            404: ("not_found", "No existe ese recurso."),
            405: ("method_not_allowed", "Método no permitido."),
            413: ("payload_too_large", "La petición es demasiado grande."),
        }
        code, message = codes.get(exc.status_code, ("http_error", "La petición no es válida."))
        return _error_response(ApiError(exc.status_code, code, message))

    async def _domain_error(_request: Any, exc: Exception) -> JSONResponse:
        error = to_api_error(exc)
        if error.status >= 500 and error.code == "unexpected":
            log.error("error inesperado", error_type=type(exc).__name__)
        return _error_response(error)

    for exc_type in (AgentError, ValueError):
        app.add_exception_handler(exc_type, _domain_error)

    app.add_middleware(SessionGuardMiddleware, prefix=API_PREFIX, public={LOGIN_PATH})
    app.add_middleware(RequestLogMiddleware)
    app.add_middleware(CatchAllMiddleware, on_error=_unexpected)
    if settings.api_origins:  # sin orígenes: solo el mismo origen (proxy), sin CORS
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )
    app.add_middleware(
        BodyLimitMiddleware, max_bytes=settings.api_max_body_bytes, on_too_large=_too_large
    )
    app.add_middleware(SecurityHeadersMiddleware)
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
