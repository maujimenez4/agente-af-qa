"""EmbeddingProvider sobre Ollama (bge-m3) mediante su API compatible con OpenAI (D-14)."""

import math
from collections.abc import Sequence
from typing import Any

import openai
from openai import OpenAI

from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError

SERVICE = "ollama"
# Ollama no valida la clave, pero el SDK de OpenAI exige un valor no vacío.
_NO_KEY = "ollama"


class OllamaEmbeddings:
    """Vectoriza textos en lotes y comprueba que cada vector tiene la dimensión configurada."""

    def __init__(
        self,
        model: str,
        dimensions: int,
        base_url: str,
        *,
        batch_size: int = 32,
        timeout: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if dimensions <= 0 or batch_size <= 0:
            raise ValueError("dimensions y batch_size deben ser positivos.")
        self.model_name = model
        self.dimensions = dimensions
        self._batch_size = batch_size
        self._client = client or OpenAI(
            base_url=base_url, api_key=_NO_KEY, timeout=timeout, max_retries=2
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors += self._embed_batch(texts[start : start + self._batch_size])
        return vectors

    def _embed_batch(self, batch: Sequence[str]) -> list[list[float]]:
        try:
            response = self._client.embeddings.create(model=self.model_name, input=list(batch))
        except openai.RateLimitError as exc:
            raise RateLimitError(
                "Ollama está saturado; vuelve a intentarlo en unos segundos.",
                service=SERVICE,
                retry_after=_retry_after(exc),
            ) from None
        except (openai.AuthenticationError, openai.PermissionDeniedError):  # 401 y 403 (PA-220)
            raise AuthenticationError(
                "Ollama ha rechazado la petición de embeddings.", service=SERVICE
            ) from None
        except openai.NotFoundError:
            raise ExternalServiceError(
                f"El modelo de embeddings '{self.model_name}' no está disponible en Ollama "
                f"(ejecuta `ollama pull {self.model_name}`).",
                service=SERVICE,
            ) from None
        except (openai.APIConnectionError, openai.APITimeoutError):
            raise ExternalServiceError(
                "No se pudo conectar con Ollama para generar los embeddings.", service=SERVICE
            ) from None
        except openai.APIError:
            raise ExternalServiceError(
                "Ollama devolvió un error al generar los embeddings.", service=SERVICE
            ) from None

        data = sorted(response.data, key=lambda item: item.index)
        if len(data) != len(batch):
            raise ExternalServiceError(
                "Ollama devolvió un número de embeddings distinto al de textos.", service=SERVICE
            )
        if [item.index for item in data] != list(range(len(batch))):  # PA-220
            raise ExternalServiceError(
                "Ollama devolvió embeddings con índices repetidos o fuera de rango.",
                service=SERVICE,
            )
        vectors = [list(item.embedding) for item in data]
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ExternalServiceError(
                    f"El modelo '{self.model_name}' devuelve vectores de {len(vector)} dimensiones "
                    f"y la base de datos espera {self.dimensions}.",
                    service=SERVICE,
                )
        return vectors


def _retry_after(exc: openai.RateLimitError) -> float | None:
    value = exc.response.headers.get("retry-after") if exc.response is not None else None
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None
    if seconds is None or not math.isfinite(seconds):  # PA-220: nan o inf no son una espera
        return None
    return max(0.0, seconds)  # como el adaptador del LLM
