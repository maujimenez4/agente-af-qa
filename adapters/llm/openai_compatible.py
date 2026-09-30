"""Proveedor LLM para APIs compatibles con OpenAI: Groq, OpenRouter y Ollama (RF-40, D-14).

- Ante un 429 respeta `retry-after` y reintenta hasta `max_retries_on_429` veces; si la espera
  supera `max_wait_s`, lanza `RateLimitError` para que `FallbackLLMProvider` pase al siguiente
  proveedor (RNF-27).
- `generate_structured` pide JSON Schema y, si el proveedor no lo admite, modo JSON. Siempre
  valida con Pydantic y reintenta una vez con el error de validación (RNF-28).
- Los errores del SDK se traducen a `adapters/errors.py` con mensajes en español, sin claves
  ni cuerpos de respuesta.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

import httpx
import openai
import structlog
from pydantic import BaseModel, SecretStr, ValidationError

from adapters.base import LLMResult, Message, StructuredResult, TaskType
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError

log = structlog.get_logger(__name__)

# El SDK exige una clave aunque el proveedor local (Ollama) no la use.
_LOCAL_PLACEHOLDER_KEY = "sin-clave"
_DEFAULT_TIMEOUT_S = 60.0
_MAX_ERRORS_IN_FEEDBACK = 5
_CODE_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class StructuredOutputError(ExternalServiceError):
    """El modelo no devolvió una salida válida para el esquema ni tras el reintento (RNF-28)."""


@dataclass(frozen=True)
class StructuredPrompts:
    """Textos de apoyo a la salida estructurada, cargados de `prompts/` por la composición.

    `json_mode` contiene `{schema}` y `retry` contiene `{errors}`.
    """

    json_mode: str
    retry: str


class OpenAICompatibleProvider:
    """Un modelo concreto de un proveedor compatible con la API de OpenAI."""

    def __init__(
        self,
        provider: str,
        model: str,
        client: openai.OpenAI,
        *,
        prompts: StructuredPrompts,
        max_retries_on_429: int = 2,
        max_wait_s: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.provider = provider
        self.model = model
        self._client = client
        self._prompts = prompts
        self._max_retries_on_429 = max_retries_on_429
        self._max_wait_s = max_wait_s
        self._sleep = sleep
        self._json_schema_supported = True

    @classmethod
    def create(
        cls,
        provider: str,
        model: str,
        base_url: str,
        api_key: SecretStr | None,
        *,
        http_client: httpx.Client | None = None,
        **kwargs: Any,
    ) -> Self:
        """Crea el cliente del SDK; `api_key=None` para proveedores sin clave (Ollama)."""
        client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key.get_secret_value() if api_key else _LOCAL_PLACEHOLDER_KEY,
            max_retries=0,  # los reintentos los controla este adaptador
            timeout=_DEFAULT_TIMEOUT_S,
            http_client=http_client,
        )
        return cls(provider, model, client, **kwargs)

    # --- LLMProvider -------------------------------------------------------------------

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        start = time.monotonic()
        payload = _to_openai_messages(messages)
        content, input_tokens, output_tokens = self._complete(payload)
        return LLMResult(
            content=content,
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=_elapsed_ms(start),
        )

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        start = time.monotonic()
        payload = _to_openai_messages(messages)
        content, input_tokens, output_tokens = self._complete_structured(payload, schema)
        try:
            parsed = _parse(content, schema)
        except ValidationError as exc:
            # Un único reintento con el error de validación (RNF-28).
            retry_payload = [
                *payload,
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": self._prompts.retry.replace("{errors}", _validation_errors(exc)),
                },
            ]
            content, extra_in, extra_out = self._complete_structured(retry_payload, schema)
            input_tokens += extra_in
            output_tokens += extra_out
            try:
                parsed = _parse(content, schema)
            except ValidationError:
                raise StructuredOutputError(
                    f"El modelo {self.model} de {self.provider} no devolvió una respuesta "
                    f"válida para «{schema.__name__}» tras reintentarlo. Prueba de nuevo o "
                    "elige otro modelo.",
                    service=self.provider,
                ) from None
        return StructuredResult[schema](
            content=parsed,
            provider=self.provider,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=_elapsed_ms(start),
        )

    # --- Internos ------------------------------------------------------------------------

    def _complete_structured(
        self, payload: list[dict[str, str]], schema: type[BaseModel]
    ) -> tuple[str, int, int]:
        if self._json_schema_supported:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            }
            try:
                return self._complete(payload, response_format=response_format, raw_400=True)
            except openai.BadRequestError:
                # El proveedor o el modelo no admiten JSON Schema: modo JSON desde ahora.
                log.info(
                    "llm_json_schema_unsupported",
                    action="llm_call",
                    provider=self.provider,
                    model=self.model,
                )
                self._json_schema_supported = False
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        instructions = {
            "role": "system",
            "content": self._prompts.json_mode.replace("{schema}", schema_json),
        }
        return self._complete([*payload, instructions], response_format={"type": "json_object"})

    def _complete(
        self,
        payload: list[dict[str, str]],
        *,
        response_format: dict[str, Any] | None = None,
        raw_400: bool = False,
    ) -> tuple[str, int, int]:
        """Llama al endpoint de chat; devuelve (contenido, tokens de entrada, de salida)."""
        extra: dict[str, Any] = {"response_format": response_format} if response_format else {}
        attempt = 0
        while True:
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=payload,  # type: ignore[arg-type]
                    **extra,
                )
                break
            except openai.RateLimitError as exc:
                retry_after = _retry_after(exc.response)
                if retry_after is not None:
                    wait = retry_after
                else:
                    wait = min(float(2**attempt), self._max_wait_s)
                if attempt >= self._max_retries_on_429 or wait > self._max_wait_s:
                    raise RateLimitError(
                        f"El proveedor {self.provider} ha alcanzado su límite de uso.",
                        service=self.provider,
                        retry_after=retry_after,
                    ) from None
                log.info(
                    "llm_rate_limited",
                    action="llm_call",
                    provider=self.provider,
                    model=self.model,
                    wait_s=wait,
                )
                self._sleep(wait)
                attempt += 1
            except openai.BadRequestError:
                if raw_400:
                    raise
                raise self._status_error(400) from None
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise AuthenticationError(
                    f"El proveedor {self.provider} ha rechazado las credenciales "
                    f"(HTTP {exc.status_code}). Revisa la clave configurada.",
                    service=self.provider,
                ) from None
            except openai.NotFoundError:
                raise ExternalServiceError(
                    f"El proveedor {self.provider} no encuentra el modelo '{self.model}'.",
                    service=self.provider,
                ) from None
            except openai.APIStatusError as exc:
                raise self._status_error(exc.status_code) from None
            except openai.APITimeoutError:
                raise ExternalServiceError(
                    f"El proveedor {self.provider} no ha respondido a tiempo.",
                    service=self.provider,
                ) from None
            except openai.APIConnectionError:
                raise ExternalServiceError(
                    f"No se pudo conectar con el proveedor {self.provider}.",
                    service=self.provider,
                ) from None

        content = (response.choices[0].message.content or "") if response.choices else ""
        usage = response.usage
        if usage is not None:
            return content, usage.prompt_tokens, usage.completion_tokens
        prompt_text = " ".join(m["content"] for m in payload)
        return content, _estimate_tokens(prompt_text), _estimate_tokens(content)

    def _status_error(self, status: int) -> ExternalServiceError:
        return ExternalServiceError(
            f"El proveedor {self.provider} ha respondido con un error (HTTP {status}).",
            service=self.provider,
        )


def _to_openai_messages(messages: list[Message]) -> list[dict[str, str]]:
    return [{"role": m.role, "content": m.content} for m in messages]


def _parse[T: BaseModel](content: str, schema: type[T]) -> T:
    text = content.strip()
    if match := _CODE_FENCE.match(text):
        text = match.group(1)
    return schema.model_validate_json(text)


def _validation_errors(exc: ValidationError) -> str:
    """Lista de errores sin los valores de entrada, para el prompt de reintento."""
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    return "\n".join(
        f"- {'.'.join(str(p) for p in e['loc']) or '(raíz)'}: {e['msg']}"
        for e in errors[:_MAX_ERRORS_IN_FEEDBACK]
    )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # formato de fecha HTTP: se usa el backoff exponencial


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _elapsed_ms(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))
