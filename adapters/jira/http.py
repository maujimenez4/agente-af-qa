"""Cliente HTTP de Jira Cloud compartido por `JiraCloudTracker` y `JiraNativeTests` (SPEC-00 §8).

- `get`: lectura con backoff ante 429 y 5xx.
- `send` (JSON) y `upload` (adjuntos multipart): escrituras de **un solo intento**; una
  escritura repetida podría duplicar incidencias, comentarios o adjuntos.

Con tokens con scopes (RNF-04), las peticiones van a `api.atlassian.com/ex/jira/{cloudId}`. Los
errores se envuelven en `adapters/errors.py` con mensajes en español, sin cuerpos de respuesta,
cabeceras ni credenciales.
"""

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from adapters.errors import (
    AgentError,
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)

SERVICE = "jira"
UNEXPECTED_FORMAT = "Jira ha devuelto datos con un formato inesperado."  # PA-185
_GATEWAY = "https://api.atlassian.com/ex/jira"
_CLOUD_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")


class JiraHttp:
    """Autenticación Basic sobre `https` (o el gateway de `cloud_id`) y manejo de errores."""

    def __init__(
        self,
        base_url: str,
        email: SecretStr,
        api_token: SecretStr,
        *,
        cloud_id: SecretStr | None = None,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        max_wait_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        if cloud_id is not None and cloud_id.get_secret_value():
            if not _CLOUD_ID_RE.fullmatch(cloud_id.get_secret_value()):
                raise AuthenticationError(
                    "JIRA_CLOUD_ID no tiene un formato válido.", service=SERVICE
                )
            self._api_root = f"{_GATEWAY}/{cloud_id.get_secret_value()}"
        else:
            # Basic auth: las credenciales solo pueden viajar cifradas.
            if not base_url.lower().startswith("https://"):
                raise AuthenticationError(
                    "JIRA_BASE_URL debe empezar por https://.", service=SERVICE
                )
            self._api_root = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(email.get_secret_value(), api_token.get_secret_value())
        self._client = http_client or httpx.Client(timeout=timeout)
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._sleep = sleep

    @property
    def api_root(self) -> str:
        """Raíz de la API (con gateway incluye el `cloud_id`): no registrarla en logs."""
        return self._api_root

    # --- Lectura -----------------------------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        key: str | None = None,
        invalid: str | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._client.get(
                    f"{self._api_root}{path}",
                    params=params,
                    auth=self._auth,
                    headers={"Accept": "application/json"},
                    timeout=self._timeout,
                    follow_redirects=False,  # PA-183: como en las escrituras
                )
            except httpx.HTTPError:
                if attempt < self._max_retries:
                    self._sleep(min(float(2**attempt), self._max_wait_s))
                    attempt += 1
                    continue
                raise ExternalServiceError(
                    "No se pudo conectar con Jira. Revisa la URL del sitio y la red.",
                    service=SERVICE,
                ) from None

            status = response.status_code
            if status < 300:
                if not response.content:
                    return {}
                try:
                    data = response.json()
                except ValueError:
                    raise ExternalServiceError(
                        "Jira ha devuelto una respuesta no válida.", service=SERVICE
                    ) from None
                if not isinstance(data, dict):  # PA-185: las lecturas siempre son objetos
                    raise ExternalServiceError(UNEXPECTED_FORMAT, service=SERVICE)
                return data
            if status < 400:  # PA-183: un 3xx (URL del sitio mal puesta) no es un éxito vacío
                raise ExternalServiceError(
                    f"Jira ha respondido con una redirección (HTTP {status}). Revisa la URL del "
                    "sitio.",
                    service=SERVICE,
                )
            if status in (401, 403):
                raise AuthenticationError(
                    f"Jira ha rechazado las credenciales (HTTP {status}). Revisa el email, "
                    "el token y sus scopes.",
                    service=SERVICE,
                )
            if status == 400 and invalid:
                raise ExternalServiceError(
                    f"{invalid} no es válida para Jira (HTTP 400).", service=SERVICE
                )
            if status == 404:
                target = f"La incidencia {key}" if key else "El recurso solicitado"
                raise NotFoundError(
                    f"{target} no existe o no tienes permiso para verla.", service=SERVICE
                )
            if status == 429:
                retry_after = _retry_after(response)
                wait = retry_after if retry_after is not None else float(2**attempt)
                if attempt >= self._max_retries or wait > self._max_wait_s:
                    raise RateLimitError(
                        "Jira ha alcanzado su límite de peticiones. Inténtalo más tarde.",
                        service=SERVICE,
                        retry_after=retry_after,
                    )
                self._sleep(wait)
                attempt += 1
                continue
            if status >= 500 and attempt < self._max_retries:
                self._sleep(min(float(2**attempt), self._max_wait_s))
                attempt += 1
                continue
            raise ExternalServiceError(
                f"Jira ha respondido con un error (HTTP {status}).", service=SERVICE
            )

    # --- Escritura (un solo intento) ---------------------------------------------------------

    def send(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        failure: type[AgentError],
        key: str | None = None,
    ) -> dict[str, Any]:
        """Escritura JSON de un solo intento; la respuesta, como objeto (o `{}`)."""
        data = self._write(method, path, failure, key, json=body)
        return data if isinstance(data, dict) else {}

    def upload(
        self,
        path: str,
        filename: str,
        content: str,
        failure: type[AgentError],
        key: str | None = None,
    ) -> Any:
        """Adjunto (`multipart/form-data`, campo `file`) de un solo intento."""
        files = {"file": (filename, content.encode("utf-8"), "text/markdown")}
        # Jira exige esta cabecera en los adjuntos (protección XSRF).
        return self._write(
            "POST", path, failure, key, files=files, headers={"X-Atlassian-Token": "no-check"}
        )

    def _write(
        self,
        method: str,
        path: str,
        failure: type[AgentError],
        key: str | None,
        *,
        json: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        def fail(message: str) -> AgentError:
            if issubclass(failure, ExternalServiceError):
                return failure(message, service=SERVICE)
            return failure(message)

        try:
            response = self._client.request(
                method,
                f"{self._api_root}{path}",
                json=json,
                files=files,
                auth=self._auth,
                headers={"Accept": "application/json", **(headers or {})},
                timeout=self._timeout,
                follow_redirects=False,  # aunque el cliente inyectado las siga
            )
        except httpx.HTTPError:
            raise fail(
                "No se pudo confirmar la escritura en Jira (fallo de red). Comprueba en Jira "
                "si se ha aplicado antes de reintentar."
            ) from None

        status = response.status_code
        if status < 300:
            if not response.content:
                return {}
            try:
                data = response.json()
            except ValueError:
                raise fail("Jira ha devuelto una respuesta no válida al escribir.") from None
            return data if isinstance(data, dict | list) else {}
        if status < 400:  # httpx no sigue redirecciones: la escritura no se ha aplicado
            raise fail(
                f"Jira ha respondido con una redirección (HTTP {status}) y no se ha escrito "
                "nada. Revisa la URL del sitio."
            )
        if status in (401, 403):
            raise AuthenticationError(
                f"Jira no permite esta escritura (HTTP {status}). Revisa el token, sus scopes "
                "de escritura y los permisos del proyecto.",
                service=SERVICE,
            )
        if status == 404:
            target = f"La incidencia {key}" if key else "Alguna de las incidencias"
            raise NotFoundError(
                f"{target} no existe o no tienes permiso para verla.", service=SERVICE
            )
        if status == 429:
            raise RateLimitError(
                "Jira ha alcanzado su límite de peticiones; la escritura no se ha reintentado. "
                "Inténtalo más tarde.",
                service=SERVICE,
                retry_after=_retry_after(response),
            )
        if status == 400:
            raise fail(
                "Jira ha rechazado los datos (HTTP 400). Revisa el tipo de incidencia, la épica "
                "y los campos obligatorios del proyecto."
            )
        raise fail(f"Jira ha respondido con un error al escribir (HTTP {status}).")


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
