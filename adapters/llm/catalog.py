"""Catálogo de modelos de un proveedor compatible con la API de OpenAI (T-29, RF-40, RF-41).

`GET {base_url}/models` (en Ollama, `/v1/models`) devuelve los modelos **disponibles**: no genera
texto, no gasta tokens y no carga ningún modelo en memoria. Sirve igual para los modelos de las
tareas y para el de embeddings (mismo listado sobre su `base_url`). Implementa el `Protocol`
`ModelCatalog` de `core/health.py`.

Los errores se envuelven en `adapters/errors.py` con mensajes fijos en español, sin el texto de la
excepción, sin cabeceras ni claves: solo el proveedor, el host y, si lo hay, el código HTTP.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

import httpx
from pydantic import SecretStr

from adapters.errors import AuthenticationError, ExternalServiceError

DEFAULT_TIMEOUT_S = 5.0
MAX_MODELS = 1000  # tope de nombres leídos de una respuesta


def host_of(url: str) -> str:
    """Solo el host (y el puerto) de una URL: nunca usuario, contraseña, ruta ni consulta."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    return f"{host}:{parts.port}" if parts.port else host


class HttpModelCatalog:
    """Lista los modelos de cada proveedor con `GET {base_url}/models`, en un solo intento."""

    def __init__(
        self,
        base_urls: Mapping[str, str],
        api_keys: Mapping[str, SecretStr | None] | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._base_urls = dict(base_urls)
        self._api_keys = dict(api_keys or {})
        self._timeout_s = timeout_s
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        """Cierra el cliente HTTP si lo creó el catálogo."""
        if self._owns_client:
            self._client.close()

    def list_models(self, provider: str) -> set[str]:
        base_url = self._base_urls.get(provider)
        if not base_url:
            raise ExternalServiceError(
                f"El proveedor «{provider[:40]}» no está configurado.", service=provider
            )
        host = host_of(base_url)
        headers = {"Accept": "application/json"}
        key = self._api_keys.get(provider)
        if key is not None and key.get_secret_value():
            headers["Authorization"] = f"Bearer {key.get_secret_value()}"
        try:
            response = self._client.get(
                f"{base_url.rstrip('/')}/models",
                headers=headers,
                timeout=self._timeout_s,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise ExternalServiceError(
                f"{host} no respondió en {self._timeout_s:g} s.", service=provider
            ) from None
        except httpx.HTTPError:
            raise ExternalServiceError(
                f"No se pudo conectar con {host}.", service=provider
            ) from None

        status = response.status_code
        if status in (401, 403):
            raise AuthenticationError(
                f"{host} ha rechazado la clave del proveedor (HTTP {status}).", service=provider
            )
        if status != 200:
            raise ExternalServiceError(
                f"{host} ha respondido con un error (HTTP {status}).", service=provider
            )
        try:
            data = response.json()
        except ValueError:
            raise ExternalServiceError(
                f"{host} ha devuelto una respuesta no válida.", service=provider
            ) from None
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise ExternalServiceError(
                f"{host} ha devuelto una lista de modelos no válida.", service=provider
            )
        return {
            str(item["id"])
            for item in items[:MAX_MODELS]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
