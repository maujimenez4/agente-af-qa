"""Pruebas de adapters/llm/openai_compatible.py (T-10 · RF-40, RF-43, RNF-27, RNF-28).

Todo el HTTP pasa por `httpx.MockTransport`: no hay red. La clave es un valor ficticio
("test-key") y las esperas se registran con un `sleep` falso (nunca se duerme de verdad).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, SecretStr
from structlog.testing import capture_logs

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    RateLimitError,
)
from adapters.llm.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderTimeoutError,
    StructuredOutputError,
    StructuredPrompts,
)

FAKE_KEY = "test-key"
PROVIDER = "proveedor-ficticio"
MODEL = "modelo-configurado"
BODY_MARKER = "MARCADOR-CUERPO-NO-MOSTRAR"

MESSAGES = [
    Message(role="system", content="Eres un analista funcional ficticio."),
    Message(role="user", content="Resume la renovación de préstamos de Villaficticia."),
]


class Answer(BaseModel):
    title: str
    score: int


VALID_ANSWER = '{"title": "Renovación ficticia", "score": 7}'


# --- Servidor falso ------------------------------------------------------------------------


def completion(
    content: str,
    *,
    usage: bool = True,
    model: str = "modelo-de-la-respuesta",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
) -> httpx.Response:
    body: dict[str, Any] = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage:
        body["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    return httpx.Response(200, json=body)


def error_response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    body = {"error": {"message": f"{BODY_MARKER} detalle interno", "type": "error"}}
    return httpx.Response(status, json=body, headers=headers or {})


def schema_rejected_response() -> httpx.Response:
    """400 de un proveedor que no admite JSON Schema (PA-16)."""
    body = {
        "error": {
            "message": f"{BODY_MARKER} response_format json_schema no admitido",
            "type": "invalid_request_error",
            "param": "response_format",
        }
    }
    return httpx.Response(400, json=body)


Reply = httpx.Response | Exception


@dataclass
class FakeServer:
    """Devuelve las respuestas en orden; la última se repite. Registra cada petición."""

    replies: list[Reply]
    requests: list[httpx.Request] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(request.content) for request in self.requests]


def make_client(server: Callable[[httpx.Request], httpx.Response]) -> openai.OpenAI:
    return openai.OpenAI(
        base_url="https://llm.example/v1",
        api_key=FAKE_KEY,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
    )


@dataclass
class Setup:
    server: FakeServer
    provider: OpenAICompatibleProvider
    sleeps: list[float]


TEST_PROMPTS = StructuredPrompts(
    json_mode="INSTRUCCION-JSON-FICTICIA\n{schema}",
    retry="REINTENTO-FICTICIO\n{errors}",
)


def make_provider(*replies: Reply, **kwargs: Any) -> Setup:
    server = FakeServer(list(replies))
    sleeps: list[float] = []
    kwargs.setdefault("prompts", TEST_PROMPTS)
    provider = OpenAICompatibleProvider(
        PROVIDER, MODEL, make_client(server), sleep=sleeps.append, **kwargs
    )
    return Setup(server=server, provider=provider, sleeps=sleeps)


def assert_safe_message(exc: BaseException) -> None:
    text = str(exc)
    assert text.strip()
    assert FAKE_KEY not in text
    assert BODY_MARKER not in text


# --- Contrato ------------------------------------------------------------------------------


def test_provider_satisfies_llm_protocol_when_built() -> None:
    """RF-40: OpenAICompatibleProvider implementa el protocolo LLMProvider."""
    setup = make_provider(completion("hola"))
    assert isinstance(setup.provider, LLMProvider)
    assert setup.provider.provider == PROVIDER
    assert setup.provider.model == MODEL


# --- generate ------------------------------------------------------------------------------


def test_generate_returns_result_with_usage_when_ok() -> None:
    """RF-40 · RF-43: devuelve contenido, proveedor/modelo configurados y tokens de la respuesta."""
    setup = make_provider(completion("Texto ficticio", prompt_tokens=12, completion_tokens=7))

    result = setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert isinstance(result, LLMResult)
    assert result.content == "Texto ficticio"
    assert result.provider == PROVIDER
    assert result.model == MODEL  # el configurado, no el que devuelve la respuesta
    assert result.input_tokens == 12
    assert result.output_tokens == 7
    assert result.latency_ms >= 0


def test_generate_sends_configured_model_and_messages() -> None:
    """RF-40: la petición va a /chat/completions con el modelo configurado y los mensajes."""
    setup = make_provider(completion("ok"))

    setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert len(setup.server.requests) == 1
    request = setup.server.requests[0]
    assert request.method == "POST"
    assert request.url.path.endswith("/chat/completions")
    body = setup.server.bodies()[0]
    assert body["model"] == MODEL
    assert body["messages"] == [{"role": m.role, "content": m.content} for m in MESSAGES]


def test_generate_estimates_tokens_when_usage_missing() -> None:
    """RF-43 (límite): si la respuesta no trae `usage`, se estiman los tokens (> 0)."""
    setup = make_provider(completion("Respuesta ficticia sin uso", usage=False))

    result = setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.input_tokens > 0
    assert result.output_tokens > 0


# --- 429 y backoff (RNF-27) ---------------------------------------------------------------


def test_generate_waits_retry_after_and_retries_when_429() -> None:
    """RNF-27: ante un 429 con retry-after se espera ese tiempo y se reintenta."""
    setup = make_provider(error_response(429, {"retry-after": "3"}), completion("ok"))

    result = setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "ok"
    assert setup.sleeps == [3.0]
    assert len(setup.server.requests) == 2


def test_generate_raises_rate_limit_when_429_persists() -> None:
    """RNF-27: con max_retries_on_429=2 hace como mucho 3 peticiones y lanza RateLimitError."""
    setup = make_provider(error_response(429, {"retry-after": "3"}), max_retries_on_429=2)

    with pytest.raises(RateLimitError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert len(setup.server.requests) == 3
    assert setup.sleeps == [3.0, 3.0]
    assert info.value.retry_after == 3.0
    assert info.value.service == PROVIDER
    assert_safe_message(info.value)


def test_generate_raises_without_waiting_when_retry_after_exceeds_max_wait() -> None:
    """RNF-27 (límite): si retry-after supera max_wait_s, se lanza RateLimitError sin esperar."""
    setup = make_provider(error_response(429, {"retry-after": "60"}), max_wait_s=20.0)

    with pytest.raises(RateLimitError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert len(setup.server.requests) == 1
    assert setup.sleeps == []
    assert info.value.retry_after == 60.0


def test_generate_uses_exponential_backoff_when_no_retry_after() -> None:
    """RNF-27: sin cabecera retry-after el backoff es exponencial (1.0, 2.0…)."""
    setup = make_provider(error_response(429), max_retries_on_429=2)

    with pytest.raises(RateLimitError):
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == [1.0, 2.0]
    assert len(setup.server.requests) == 3


def test_generate_caps_backoff_at_max_wait_when_no_retry_after() -> None:
    """RNF-27 (límite): el backoff exponencial está acotado por max_wait_s."""
    setup = make_provider(error_response(429), max_retries_on_429=3, max_wait_s=1.5)

    with pytest.raises(RateLimitError):
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == [1.0, 1.5, 1.5]
    assert all(wait <= 1.5 for wait in setup.sleeps)


def test_generate_does_not_retry_when_max_retries_is_zero() -> None:
    """RNF-27 (límite): con max_retries_on_429=0 no se reintenta ni se espera."""
    setup = make_provider(error_response(429, {"retry-after": "1"}), max_retries_on_429=0)

    with pytest.raises(RateLimitError):
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert len(setup.server.requests) == 1
    assert setup.sleeps == []


# --- Traducción de errores (SPEC-00 §8) ----------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_generate_raises_authentication_error_when_unauthorized(status: int) -> None:
    """RF-40 · §8: 401/403 → AuthenticationError, sin clave ni cuerpo en el mensaje."""
    setup = make_provider(error_response(status))

    with pytest.raises(AuthenticationError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert_safe_message(info.value)


def test_generate_raises_external_error_when_not_found() -> None:
    """RF-40 · §8: 404 (p. ej. modelo inexistente) → ExternalServiceError, no RateLimitError."""
    setup = make_provider(error_response(404))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert not isinstance(info.value, RateLimitError)
    assert not isinstance(info.value, AuthenticationError)
    assert_safe_message(info.value)


def test_generate_raises_external_error_when_server_fails() -> None:
    """RF-40 · §8: 500 → ExternalServiceError con mensaje seguro."""
    setup = make_provider(error_response(500))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert not isinstance(info.value, RateLimitError)
    assert_safe_message(info.value)


def test_generate_raises_external_error_when_connection_fails() -> None:
    """RF-40 · §8: un error de conexión → ExternalServiceError con mensaje seguro."""
    setup = make_provider(httpx.ConnectError("conexión rechazada (ficticia)"))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert not isinstance(info.value, RateLimitError)
    assert_safe_message(info.value)


# --- generate_structured (RNF-28) ----------------------------------------------------------


def test_structured_sends_json_schema_and_returns_model_when_valid() -> None:
    """RNF-28 · §8: primero pide JSON Schema y devuelve una instancia validada del esquema."""
    setup = make_provider(completion(VALID_ANSWER))

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert isinstance(result, StructuredResult)
    assert result.content == Answer(title="Renovación ficticia", score=7)
    assert result.provider == PROVIDER
    assert result.model == MODEL
    assert result.input_tokens == 10
    assert result.output_tokens == 5
    body = setup.server.bodies()[0]
    assert body["model"] == MODEL
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "Answer",
            "schema": Answer.model_json_schema(),
            "strict": False,
        },
    }


def test_structured_falls_back_to_json_mode_when_schema_rejected() -> None:
    """§8: si el proveedor responde 400 a json_schema, reintenta en modo JSON con el esquema."""
    setup = make_provider(schema_rejected_response(), completion(VALID_ANSWER))

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content == Answer(title="Renovación ficticia", score=7)
    assert len(setup.server.requests) == 2
    first, second = setup.server.bodies()
    assert first["response_format"]["type"] == "json_schema"
    assert second["response_format"] == {"type": "json_object"}
    system_texts = [m["content"] for m in second["messages"] if m["role"] == "system"]
    assert any("title" in text and "score" in text for text in system_texts)


def test_structured_remembers_json_mode_when_schema_rejected_before() -> None:
    """§8: tras un 400 a json_schema, las siguientes llamadas van directas a modo JSON."""
    setup = make_provider(
        schema_rejected_response(), completion(VALID_ANSWER), completion(VALID_ANSWER)
    )
    setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    assert len(setup.server.requests) == 2

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    assert len(setup.server.requests) == 3  # una sola petición en la segunda llamada
    assert setup.server.bodies()[2]["response_format"] == {"type": "json_object"}


def test_structured_raises_external_error_when_json_mode_also_rejected() -> None:
    """§8 (error): si también se rechaza el modo JSON, se lanza ExternalServiceError."""
    setup = make_provider(schema_rejected_response(), error_response(400))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert_safe_message(info.value)


def test_structured_retries_once_with_error_when_invalid_json() -> None:
    """RNF-28: si la salida no es JSON válido, reintenta una vez con el error y suma tokens."""
    bad = "esto no es JSON (ficticio)"
    setup = make_provider(
        completion(bad, prompt_tokens=10, completion_tokens=5),
        completion(VALID_ANSWER, prompt_tokens=20, completion_tokens=6),
    )

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content == Answer(title="Renovación ficticia", score=7)
    assert result.input_tokens == 30
    assert result.output_tokens == 11
    assert len(setup.server.requests) == 2
    first, second = setup.server.bodies()
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][-2] == {"role": "assistant", "content": bad}
    assert second["messages"][-1]["role"] == "user"
    assert second["messages"][-1]["content"].strip()


def test_structured_retries_once_when_schema_validation_fails() -> None:
    """RNF-28: un JSON que no valida con Pydantic también provoca un único reintento."""
    invalid = '{"title": "Ficticio", "score": "no-es-un-numero"}'
    setup = make_provider(completion(invalid), completion(VALID_ANSWER))

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    assert len(setup.server.requests) == 2
    second = setup.server.bodies()[1]
    assert second["messages"][-2] == {"role": "assistant", "content": invalid}
    assert second["messages"][-1]["role"] == "user"


def test_structured_raises_structured_output_error_when_invalid_twice() -> None:
    """RNF-28: si la salida vuelve a ser inválida tras el reintento se informa del error."""
    setup = make_provider(completion("{no json"), completion('{"title": 1}'))

    with pytest.raises(StructuredOutputError) as info:
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert isinstance(info.value, ExternalServiceError)
    assert len(setup.server.requests) == 2
    assert FAKE_KEY not in str(info.value)


# --- create (RF-40) ------------------------------------------------------------------------

GROQ_LIKE_URL = "https://groq.example/openai/v1"
LOCAL_URL = "http://ollama.example:11434/v1"


def test_create_sends_bearer_key_to_given_base_url() -> None:
    """RF-40: `create` apunta al base_url indicado y envía la clave como Bearer."""
    server = FakeServer([completion("ok")])

    provider = OpenAICompatibleProvider.create(
        "groq",
        "m",
        GROQ_LIKE_URL,
        SecretStr(FAKE_KEY),
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        prompts=TEST_PROMPTS,
        sleep=lambda _seconds: None,
    )
    result = provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert (provider.provider, provider.model) == ("groq", "m")
    assert (result.provider, result.model) == ("groq", "m")
    request = server.requests[0]
    assert str(request.url) == f"{GROQ_LIKE_URL}/chat/completions"
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert server.bodies()[0]["model"] == "m"


def test_create_works_without_key_when_local_provider() -> None:
    """RF-40 (límite): sin clave (proveedor local) funciona con una clave de relleno."""
    server = FakeServer([completion("ok")])

    provider = OpenAICompatibleProvider.create(
        "local",
        "modelo-local-ficticio",
        LOCAL_URL,
        None,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        prompts=TEST_PROMPTS,
    )
    result = provider.generate(MESSAGES, TaskType.CLASSIFY_SOURCE)

    assert result.content == "ok"
    request = server.requests[0]
    assert str(request.url) == f"{LOCAL_URL}/chat/completions"
    assert request.headers.get("authorization", "").startswith("Bearer ")
    assert FAKE_KEY not in request.headers.get("authorization", "")


def test_create_forwards_retry_kwargs_to_constructor() -> None:
    """RNF-27: los kwargs de `create` (max_retries_on_429, sleep) llegan al proveedor."""
    server = FakeServer([error_response(429, {"retry-after": "2"})])
    sleeps: list[float] = []

    provider = OpenAICompatibleProvider.create(
        "groq",
        "m",
        GROQ_LIKE_URL,
        SecretStr(FAKE_KEY),
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        prompts=TEST_PROMPTS,
        max_retries_on_429=1,
        sleep=sleeps.append,
    )
    with pytest.raises(RateLimitError):
        provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert len(server.requests) == 2
    assert sleeps == [2.0]


# --- Prompts desde prompts/ (CLAUDE.md: sin prompts en el código) --------------------------


def test_json_mode_uses_injected_prompt_with_schema() -> None:
    """El mensaje de modo JSON es el prompt inyectado con `{schema}` sustituido."""
    setup = make_provider(schema_rejected_response(), completion(VALID_ANSWER))

    setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    second = setup.server.bodies()[1]
    system = [m["content"] for m in second["messages"] if m["role"] == "system"][-1]
    assert system.startswith("INSTRUCCION-JSON-FICTICIA\n")
    assert "{schema}" not in system
    assert json.loads(system.split("\n", 1)[1]) == Answer.model_json_schema()


def test_retry_uses_injected_prompt_with_errors() -> None:
    """El reintento de RNF-28 usa el prompt inyectado con `{errors}` sustituido."""
    setup = make_provider(completion('{"title": "x"}'), completion(VALID_ANSWER))

    setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    retry = setup.server.bodies()[1]["messages"][-1]
    assert retry["role"] == "user"
    assert retry["content"].startswith("REINTENTO-FICTICIO\n")
    assert "{errors}" not in retry["content"]
    assert "score" in retry["content"]


# --- T-32 · Ayudas -------------------------------------------------------------------------

BASE_URL_HOST = "llm.example"
HTTP_DATE = "Wed, 21 Oct 2026 07:28:00 GMT"


def bad_request(message: str, param: str | None = None) -> httpx.Response:
    """400 del proveedor con un mensaje y un `param` concretos (PA-16)."""
    error: dict[str, Any] = {
        "message": f"{BODY_MARKER} {message}",
        "type": "invalid_request_error",
    }
    if param is not None:
        error["param"] = param
    return httpx.Response(400, json={"error": error})


def make_strict_provider(*replies: Reply) -> Setup:
    """Proveedor cuyo SDK valida estrictamente la respuesta (APIResponseValidationError)."""
    server = FakeServer(list(replies))
    sleeps: list[float] = []
    client = openai.OpenAI(
        base_url=f"https://{BASE_URL_HOST}/v1",
        api_key=FAKE_KEY,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        _strict_response_validation=True,
    )
    provider = OpenAICompatibleProvider(
        PROVIDER, MODEL, client, prompts=TEST_PROMPTS, sleep=sleeps.append
    )
    return Setup(server=server, provider=provider, sleeps=sleeps)


def assert_ui_safe_error(exc: BaseException) -> None:
    """RNF-02: mensaje en español, sin cuerpo, URL, clave ni volcados de Pydantic."""
    text = str(exc)
    assert "proveedor" in text.lower()  # mensaje propio, en español
    for forbidden in (BODY_MARKER, BASE_URL_HOST, FAKE_KEY, "input_value", "Traceback"):
        assert forbidden not in text
    assert exc.__cause__ is None
    assert exc.__suppress_context__ is True  # `raise ... from None`


# --- T-32 · 429 (RNF-27) -------------------------------------------------------------------


def test_generate_waits_exactly_retry_after_when_equal_to_max_wait() -> None:
    """CA-1 (límite): retry-after igual a max_wait_s se espera exactamente y se reintenta."""
    setup = make_provider(
        error_response(429, {"retry-after": "20"}), completion("ok"), max_wait_s=20.0
    )

    result = setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "ok"
    assert setup.sleeps == [20.0]
    assert len(setup.server.requests) == 2


def test_generate_waits_fractional_retry_after_when_below_max_wait() -> None:
    """CA-1: un retry-after con decimales se respeta tal cual."""
    setup = make_provider(error_response(429, {"retry-after": "0.5"}), completion("ok"))

    setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == [0.5]


def test_generate_raises_immediately_when_retry_after_just_above_max_wait() -> None:
    """CA-1 (límite): retry-after > max_wait_s → RateLimitError sin dormir ni reintentar."""
    setup = make_provider(error_response(429, {"retry-after": "20.5"}), max_wait_s=20.0)

    with pytest.raises(RateLimitError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == []
    assert len(setup.server.requests) == 1
    assert info.value.retry_after == 20.5


def test_generate_retries_exactly_max_retries_when_no_retry_after() -> None:
    """CA-1: sin retry-after, backoff exponencial y tantos reintentos como max_retries_on_429."""
    setup = make_provider(error_response(429), max_retries_on_429=4, max_wait_s=100.0)

    with pytest.raises(RateLimitError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == [1.0, 2.0, 4.0, 8.0]
    assert len(setup.server.requests) == 5
    assert info.value.retry_after is None


def test_generate_uses_backoff_when_retry_after_is_http_date() -> None:
    """CA-1: un retry-after con fecha HTTP no se interpreta: se usa el backoff exponencial."""
    setup = make_provider(error_response(429, {"retry-after": HTTP_DATE}), max_retries_on_429=2)

    with pytest.raises(RateLimitError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert setup.sleeps == [1.0, 2.0]
    assert len(setup.server.requests) == 3
    assert info.value.retry_after is None


def test_generate_recovers_with_backoff_when_retry_after_is_http_date() -> None:
    """CA-1: tras el backoff por fecha HTTP la llamada se completa si el proveedor responde."""
    setup = make_provider(error_response(429, {"retry-after": HTTP_DATE}), completion("ok"))

    assert setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY).content == "ok"
    assert setup.sleeps == [1.0]


# --- T-32 · Tiempo de espera (RNF-12) ------------------------------------------------------


def test_generate_raises_provider_timeout_with_single_request_when_timeout() -> None:
    """CA-2: un tiempo agotado → ProviderTimeoutError tras una sola petición, sin esperas."""
    setup = make_provider(httpx.ReadTimeout("tiempo agotado (ficticio)"))

    with pytest.raises(ProviderTimeoutError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert isinstance(info.value, ExternalServiceError)
    assert not isinstance(info.value, RateLimitError)
    assert info.value.service == PROVIDER
    assert len(setup.server.requests) == 1
    assert setup.sleeps == []
    assert "a tiempo" in str(info.value)


def test_structured_raises_provider_timeout_without_json_mode_when_timeout() -> None:
    """CA-2: en salida estructurada, el tiempo agotado no provoca el paso a modo JSON."""
    setup = make_provider(httpx.ReadTimeout("tiempo agotado (ficticio)"), completion(VALID_ANSWER))

    with pytest.raises(ProviderTimeoutError):
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    first, second = setup.server.bodies()
    assert first["response_format"]["type"] == "json_schema"
    assert second["response_format"]["type"] == "json_schema"


def test_create_passes_request_timeout_to_sdk_client() -> None:
    """CA-2 · RNF-12: `create(timeout_s=...)` configura el tiempo de espera del cliente."""
    provider = OpenAICompatibleProvider.create(
        "local", "m", LOCAL_URL, None, prompts=TEST_PROMPTS, timeout_s=7.5
    )

    assert provider._client.timeout == 7.5


# --- T-32 · PA-16: solo un 400 de response_format pasa a modo JSON -------------------------


@pytest.mark.parametrize(
    ("message", "param"),
    [
        ("parámetro no admitido", "response_format"),
        ("tipo no admitido", "response_format.json_schema"),
        ("This model does not support json_schema", None),
        ("JSON Schema is not supported by this model", None),
        ("structured output is unavailable", None),
    ],
    ids=["param", "param-subcampo", "msg-json_schema", "msg-json-schema", "msg-structured"],
)
def test_structured_switches_to_json_mode_when_400_refers_to_response_format(
    message: str, param: str | None
) -> None:
    """CA-3 · PA-16: un 400 por `response_format`/`json_schema` pasa a modo JSON."""
    setup = make_provider(bad_request(message, param), completion(VALID_ANSWER))

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    first, second = setup.server.bodies()
    assert first["response_format"]["type"] == "json_schema"
    assert second["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("message", "param"),
    [
        ("context length exceeded: reduce the length of the messages", "messages"),
        ("Please reduce the length of the messages", None),
        ("invalid value for temperature", "temperature"),
    ],
    ids=["contexto-param", "contexto-sin-param", "otro-param"],
)
def test_structured_raises_external_error_without_json_mode_when_generic_400(
    message: str, param: str | None
) -> None:
    """CA-3 · PA-16: otro 400 → ExternalServiceError y no se envía la petición en modo JSON."""
    setup = make_provider(bad_request(message, param))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert not isinstance(info.value, StructuredOutputError)
    assert len(setup.server.requests) == 1
    assert setup.server.bodies()[0]["response_format"]["type"] == "json_schema"
    assert "HTTP 400" in str(info.value)
    assert_ui_safe_error(info.value)


def test_structured_keeps_json_schema_for_next_call_when_generic_400() -> None:
    """CA-3 · PA-16: un 400 genérico no desactiva JSON Schema para las llamadas siguientes."""
    setup = make_provider(
        bad_request("context length exceeded", "messages"), completion(VALID_ANSWER)
    )
    with pytest.raises(ExternalServiceError):
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    assert len(setup.server.requests) == 2
    assert setup.server.bodies()[1]["response_format"]["type"] == "json_schema"


# --- T-32 · Mensajes de error (RNF-02) -----------------------------------------------------


def _timeout_with_marker(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout(f"{BODY_MARKER} https://{BASE_URL_HOST}/v1", request=request)


def _connect_error_with_marker(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError(f"{BODY_MARKER} https://{BASE_URL_HOST}/v1", request=request)


ERROR_CASES: list[tuple[str, Any, type[ExternalServiceError]]] = [
    ("400-generico", bad_request("context length exceeded", "messages"), ExternalServiceError),
    ("401", error_response(401), AuthenticationError),
    ("403", error_response(403), AuthenticationError),
    ("404", error_response(404), ExternalServiceError),
    ("429-agotado", error_response(429, {"retry-after": "1"}), RateLimitError),
    ("500", error_response(500), ExternalServiceError),
    ("418-otro-estado", error_response(418), ExternalServiceError),
    ("timeout", _timeout_with_marker, ProviderTimeoutError),
    ("conexion", _connect_error_with_marker, ExternalServiceError),
]


def _provider_for(reply: Any) -> OpenAICompatibleProvider:
    handler = reply if callable(reply) else FakeServer([reply])
    return OpenAICompatibleProvider(
        PROVIDER,
        MODEL,
        make_client(handler),
        prompts=TEST_PROMPTS,
        max_retries_on_429=1,
        sleep=lambda _s: None,
    )


@pytest.mark.parametrize(
    ("reply", "expected"),
    [(reply, expected) for _id, reply, expected in ERROR_CASES],
    ids=[case_id for case_id, _reply, _expected in ERROR_CASES],
)
def test_generate_error_message_is_spanish_and_safe_when_sdk_fails(
    reply: Any, expected: type[ExternalServiceError]
) -> None:
    """CA-9 · RNF-02: cada error del SDK → excepción propia, en español, sin datos internos."""
    with pytest.raises(expected) as info:
        _provider_for(reply).generate(MESSAGES, TaskType.GENERATE_STORY)

    assert info.value.service == PROVIDER
    assert_ui_safe_error(info.value)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [(reply, expected) for _id, reply, expected in ERROR_CASES],
    ids=[case_id for case_id, _reply, _expected in ERROR_CASES],
)
def test_structured_error_message_is_spanish_and_safe_when_sdk_fails(
    reply: Any, expected: type[ExternalServiceError]
) -> None:
    """CA-9 · RNF-02: lo mismo en `generate_structured` (petición con JSON Schema)."""
    with pytest.raises(expected) as info:
        _provider_for(reply).generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert_ui_safe_error(info.value)


def test_generate_hides_sdk_text_when_response_validation_fails() -> None:
    """CA-9 · RNF-02: un `openai.OpenAIError` genérico (APIResponseValidationError) se envuelve
    en ExternalServiceError sin el texto del SDK (cuerpo, `input_value`)."""
    setup = make_strict_provider(httpx.Response(200, json={"id": 1, "choices": BODY_MARKER}))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert type(info.value) is ExternalServiceError
    assert isinstance(info.value.__context__, openai.APIResponseValidationError)
    assert "inesperada" in str(info.value)
    assert_ui_safe_error(info.value)


@pytest.mark.parametrize(
    "reply",
    [
        httpx.Response(200, text=f"<html>{BODY_MARKER}</html>"),
        httpx.Response(
            200, content=BODY_MARKER.encode(), headers={"content-type": "application/json"}
        ),
    ],
    ids=["texto", "json-invalido"],
)
def test_generate_wraps_error_when_200_body_is_not_json(reply: httpx.Response) -> None:
    """CA-9 · RNF-02: una respuesta 200 que no es JSON (proxy, HTML) debería traducirse a
    ExternalServiceError en español para que la cadena pase al siguiente proveedor."""
    setup = make_provider(reply)

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert BODY_MARKER not in str(info.value)


def _completion_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "cmpl-ficticio",
        "object": "chat.completion",
        "created": 0,
        "model": "modelo-ficticio",
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    "body",
    [
        _completion_body(choices=[{"index": 0}]),
        _completion_body(choices="no-es-una-lista"),
        _completion_body(usage={"prompt_tokens": None, "completion_tokens": 1}),
        {"respuesta": BODY_MARKER},
    ],
    ids=["choice-sin-message", "choices-no-lista", "usage-sin-tokens", "sin-choices"],
)
def test_generate_wraps_error_when_200_is_malformed_completion(body: dict[str, Any]) -> None:
    """CA-9 · RNF-12: un 200 con JSON que no es una respuesta de chat válida se traduce a
    ExternalServiceError en español (la cadena pasa al siguiente) sin mostrar el cuerpo."""
    setup = make_provider(httpx.Response(200, json=body))

    with pytest.raises(ExternalServiceError) as info:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert "inesperada" in str(info.value)
    assert BODY_MARKER not in str(info.value)


# --- T-32 · Logs (RNF-02) ------------------------------------------------------------------


def _log_text(logs: list[Any]) -> str:
    return json.dumps(logs, ensure_ascii=False, default=str)


def test_logs_omit_messages_key_and_body_when_rate_limited() -> None:
    """CA-10 · RNF-02: el aviso de 429 no registra mensajes, clave ni cuerpo de la respuesta."""
    setup = make_provider(error_response(429, {"retry-after": "1"}), completion("ok"))

    with capture_logs() as logs:
        setup.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert "llm_rate_limited" in [entry["event"] for entry in logs]
    text = _log_text(logs)
    for forbidden in (FAKE_KEY, BODY_MARKER, "Villaficticia", "authorization", "Bearer"):
        assert forbidden not in text


def test_logs_omit_messages_key_and_body_when_json_schema_unsupported() -> None:
    """CA-10 · RNF-02: el paso a modo JSON se registra sin contenido ni cuerpo del 400."""
    setup = make_provider(schema_rejected_response(), completion(VALID_ANSWER))

    with capture_logs() as logs:
        setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert [entry["event"] for entry in logs] == ["llm_json_schema_unsupported"]
    text = _log_text(logs)
    for forbidden in (FAKE_KEY, BODY_MARKER, "Villaficticia", "Renovación ficticia"):
        assert forbidden not in text
