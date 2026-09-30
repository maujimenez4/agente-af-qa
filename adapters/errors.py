"""Excepciones del dominio y de los servicios externos (SPEC-00 §8).

Los adaptadores envuelven los errores externos en estas clases. El mensaje está en español
y es apto para la UI: nunca incluye secretos, cabeceras ni cuerpos de respuesta completos.
"""


class AgentError(Exception):
    """Base de todos los errores del agente."""


class ExternalServiceError(AgentError):
    """Fallo de un servicio externo (Jira, proveedor LLM, base de datos)."""

    def __init__(self, message: str, service: str | None = None) -> None:
        super().__init__(message)
        self.service = service


class AuthenticationError(ExternalServiceError):
    """Credenciales ausentes, inválidas o sin permisos suficientes."""


class NotFoundError(ExternalServiceError):
    """El recurso solicitado no existe (p. ej. una clave de Jira)."""


class RateLimitError(ExternalServiceError):
    """Límite de uso alcanzado (HTTP 429); `retry_after` en segundos si el servicio lo indica."""

    def __init__(
        self, message: str, service: str | None = None, retry_after: float | None = None
    ) -> None:
        super().__init__(message, service)
        self.retry_after = retry_after


class PublishError(AgentError):
    """La publicación en Jira no está permitida o ha fallado."""


class InvalidTransitionError(AgentError):
    """Transición de estado de artefacto no permitida (RF-34)."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"No se puede pasar un artefacto de '{current}' a '{target}'.")
        self.current = current
        self.target = target
