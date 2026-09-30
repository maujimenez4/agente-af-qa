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

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    RateLimitError,
)
from adapters.llm.openai_compatible import (
    OpenAICompatibleProvider,
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
    setup = make_provider(error_response(400), completion(VALID_ANSWER))

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
    setup = make_provider(error_response(400), completion(VALID_ANSWER), completion(VALID_ANSWER))
    setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    assert len(setup.server.requests) == 2

    result = setup.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    assert len(setup.server.requests) == 3  # una sola petición en la segunda llamada
    assert setup.server.bodies()[2]["response_format"] == {"type": "json_object"}


def test_structured_raises_external_error_when_json_mode_also_rejected() -> None:
    """§8 (error): si también se rechaza el modo JSON, se lanza ExternalServiceError."""
    setup = make_provider(error_response(400))

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
    setup = make_provider(error_response(400), completion(VALID_ANSWER))

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
