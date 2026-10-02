"""Errores de la API con la forma común `{"error": {code, message, retry_after}}` (requisito 8).

Solo se muestran los mensajes escritos para la persona: las excepciones de `adapters/errors.py`,
la respuesta rechazada de la revisión, el registro de aprobaciones y los `ValueError` exactos de
los módulos de validación. Cualquier otro error da `UNEXPECTED` (el tipo va al log, nunca
`str(exc)` a la respuesta).
"""

from types import TracebackType

from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)
from api.models import ErrorBody
from core.approvals import ApprovalError
from core.graph.nodes import ReviewRejectedError

UNEXPECTED = "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo."
MAX_RETRY_AFTER = 3600.0
# Módulos cuyos `ValueError` llevan un mensaje para la persona (validación de lo que escribe).
SAFE_VALUE_ERROR_MODULES = frozenset(
    {
        "core.projects",
        "core.graph.state",
        "core.guided_start",
        "app.origin",
        "app.review",
        "adapters.llm.router",
        "api.service",
    }
)


class ApiError(Exception):
    """Error que la API devuelve tal cual (código HTTP, código estable y mensaje en español)."""

    def __init__(
        self, status: int, code: str, message: str, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.retry_after = status, code, message, retry_after

    @property
    def body(self) -> ErrorBody:
        return ErrorBody(code=self.code, message=self.message, retry_after=self.retry_after)


def _raised_in(exc: BaseException) -> str:
    """Módulo del código Python que lanzó la excepción (último frame del traceback)."""
    tb: TracebackType | None = exc.__traceback__
    module = ""
    while tb is not None:
        module = str(tb.tb_frame.f_globals.get("__name__", ""))
        tb = tb.tb_next
    return module


def safe_message(exc: BaseException) -> str:
    if isinstance(exc, AgentError | ReviewRejectedError | ApprovalError):
        return str(exc) or UNEXPECTED
    if type(exc) is ValueError and _raised_in(exc) in SAFE_VALUE_ERROR_MODULES:
        return str(exc) or UNEXPECTED
    return UNEXPECTED


def _retry_after(exc: RateLimitError) -> float | None:
    if exc.retry_after is None:
        return None
    return max(0.0, min(float(exc.retry_after), MAX_RETRY_AFTER))


def to_api_error(exc: BaseException) -> ApiError:
    """Traduce cualquier excepción a un `ApiError` con un mensaje que se puede mostrar."""
    if isinstance(exc, ApiError):
        return exc
    message = safe_message(exc)
    if isinstance(exc, RateLimitError):
        return ApiError(429, "rate_limited", message, _retry_after(exc))
    if isinstance(exc, NotFoundError):
        return ApiError(404, "not_found", message)
    if isinstance(exc, AuthenticationError):
        # Sin servicio: permiso del rol (`core/permissions`); con servicio: credenciales de Jira.
        if exc.service is None:
            return ApiError(403, "forbidden", message)
        return ApiError(503, "service_unavailable", message)
    if isinstance(exc, ExternalServiceError):
        return ApiError(503, "service_unavailable", message)
    if isinstance(exc, ApprovalError):
        return ApiError(409, "approval_rejected", message)
    if isinstance(exc, AgentError | ReviewRejectedError):
        return ApiError(409, "operation_failed", message)
    if message != UNEXPECTED:  # ValueError de validación
        return ApiError(422, "invalid_request", message)
    return ApiError(500, "unexpected", UNEXPECTED)
