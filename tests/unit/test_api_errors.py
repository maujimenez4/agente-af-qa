"""Traducción de excepciones a la forma común de error de la API (T-55, requisito 8).

Solo se muestran mensajes escritos para la persona; cualquier otro error da el mensaje genérico
y nunca `str(exc)`. Textos 100 % ficticios.
"""

import pytest

from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    PublishError,
    RateLimitError,
)
from api import service
from api.errors import MAX_RETRY_AFTER, UNEXPECTED, ApiError, safe_message, to_api_error
from core.approvals import ApprovalError
from core.graph.nodes import ReviewRejectedError

SECRET_TEXT = "detalle-interno-ficticio-0000"


def _raised(exc: BaseException) -> BaseException:
    """La excepción con traceback de este módulo (como si se hubiera lanzado aquí)."""
    try:
        raise exc
    except BaseException as caught:
        return caught


def test_api_error_passes_through_unchanged() -> None:
    """Req. 8: un `ApiError` ya preparado se devuelve tal cual."""
    error = ApiError(409, "not_in_review", "Mensaje ficticio.", 5)
    assert to_api_error(error) is error
    assert error.body.model_dump() == {
        "code": "not_in_review",
        "message": "Mensaje ficticio.",
        "retry_after": 5,
    }


def test_rate_limit_maps_to_429_with_retry_after() -> None:
    """Req. 8: 429 `rate_limited` con `retry_after` del servicio."""
    error = to_api_error(RateLimitError("El LLM está saturado (ficticio).", "llm", 30))
    assert (error.status, error.code, error.retry_after) == (429, "rate_limited", 30.0)
    assert error.message == "El LLM está saturado (ficticio)."


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, None), (-5, 0.0), (0, 0.0), (12.5, 12.5), (10**9, MAX_RETRY_AFTER)],
)
def test_retry_after_is_bounded(raw: float | None, expected: float | None) -> None:
    """Req. 8: `retry_after` acotado entre 0 y una hora."""
    assert to_api_error(RateLimitError("Límite ficticio.", "jira", raw)).retry_after == expected


def test_not_found_maps_to_404() -> None:
    """Req. 5 y 8: `NotFoundError` -> 404 con su mensaje."""
    error = to_api_error(NotFoundError("No existe esa conversación o no es tuya."))
    assert (error.status, error.code) == (404, "not_found")
    assert error.message == "No existe esa conversación o no es tuya."


def test_permission_error_without_service_is_403() -> None:
    """Req. 5: el permiso del rol (`core/permissions`) -> 403 `forbidden`."""
    error = to_api_error(AuthenticationError("No tienes permiso para realizar esta acción."))
    assert (error.status, error.code) == (403, "forbidden")


def test_external_auth_error_is_503() -> None:
    """Req. 8: credenciales de un servicio externo -> 503 (no 401/403 de la API)."""
    error = to_api_error(AuthenticationError("Jira rechazó las credenciales (ficticio).", "jira"))
    assert (error.status, error.code) == (503, "service_unavailable")


def test_external_service_error_is_503() -> None:
    """Req. 8: servicio externo caído -> 503."""
    error = to_api_error(ExternalServiceError("Jira no responde (ficticio).", "jira"))
    assert (error.status, error.code) == (503, "service_unavailable")


def test_approval_error_is_409_approval_rejected() -> None:
    """Req. 8 / approve: rechazo del registro de aprobaciones -> 409 `approval_rejected`."""
    error = to_api_error(ApprovalError("La aprobación no corresponde (ficticio)."))
    assert (error.status, error.code) == (409, "approval_rejected")


@pytest.mark.parametrize(
    "exc",
    [PublishError("No se pudo publicar (ficticio)."), ReviewRejectedError("Huella antigua.")],
)
def test_domain_errors_are_409_operation_failed(exc: Exception) -> None:
    """Req. 8: errores del agente con mensaje para la persona -> 409 `operation_failed`."""
    error = to_api_error(exc)
    assert (error.status, error.code) == (409, "operation_failed")
    assert error.message == str(exc)


def test_agent_error_without_message_uses_generic_text() -> None:
    """Req. 8: un error del agente sin mensaje no deja el texto vacío."""
    assert safe_message(AgentError()) == UNEXPECTED


def test_value_error_from_safe_module_is_422_with_its_message() -> None:
    """Req. 8: los `ValueError` de validación de módulos en la lista blanca se muestran."""
    try:
        service.iterate_answer("   ")
    except ValueError as exc:
        error = to_api_error(exc)
    assert (error.status, error.code) == (422, "invalid_request")
    assert error.message == "Escribe qué quieres cambiar de la propuesta."


def test_value_error_from_other_module_is_generic_500() -> None:
    """Req. 8: un `ValueError` de otro módulo nunca muestra `str(exc)`."""
    error = to_api_error(_raised(ValueError(SECRET_TEXT)))
    assert (error.status, error.code, error.message) == (500, "unexpected", UNEXPECTED)
    assert SECRET_TEXT not in error.message


def test_value_error_without_traceback_is_generic() -> None:
    """Req. 8 (límite): sin traceback no se sabe el origen -> mensaje genérico."""
    assert safe_message(ValueError(SECRET_TEXT)) == UNEXPECTED


def test_value_error_subclass_is_not_trusted() -> None:
    """Req. 8: solo `ValueError` exacto; una subclase ajena (p. ej. de una librería) no."""

    class LibraryError(ValueError):
        pass

    assert safe_message(_raised(LibraryError(SECRET_TEXT))) == UNEXPECTED


@pytest.mark.parametrize(
    "exc", [RuntimeError(SECRET_TEXT), KeyError(SECRET_TEXT), TypeError(SECRET_TEXT)]
)
def test_unexpected_errors_never_expose_str(exc: Exception) -> None:
    """Req. 8: excepciones inesperadas -> 500 `unexpected` con el mensaje genérico."""
    error = to_api_error(_raised(exc))
    assert (error.status, error.code, error.message) == (500, "unexpected", UNEXPECTED)
    assert error.retry_after is None
