"""Prueba cruzada T-35 (RNF-19): el área B prueba `adapters/llm/` del área A «con mirada de fuera».

Cubre la salida estructurada (JSON Schema → modo JSON solo ante un 400 por `response_format`,
PA-16; validación pydantic y un único reintento, RNF-28), la reparación de IDs y `schema_hints`
de T-58 (`sources` obligatorio en el esquema enviado), el 429 con `retry-after` y umbral y el
tiempo agotado (RNF-27, RNF-12, RF-44), el motivo del cambio de proveedor (PA-67), los errores en
español sin datos internos (RNF-02), el registro de uso sin prompts (RF-43) con
`limits.max_output_tokens`, y el override del selector (RF-42) sobre la cadena de respaldo.

Se centra en lo que no fijan `test_llm_*.py` y `test_usage_*.py`: el recorrido completo de una
cadena con proveedores reales sobre `httpx.MockTransport`, el tope de salida en los tres tipos de
petición estructurada, el tiempo agotado en el reintento, URLs con credenciales, respuestas con
`usage` incompleto o incoherente, y el consumo de las llamadas que acaban en error.

Nada de red ni LLM reales: todo el HTTP va por `httpx.MockTransport` y las esperas se registran
con un `sleep` falso. Datos 100 % ficticios (clave «test-key», dominio llm.example, textos
«ficticio»). Los defectos confirmados van como `xfail(strict=True)` con su PA; el resto fija el
comportamiento actual.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field, fields
from typing import Any
from uuid import uuid4

import httpx
import openai
import pytest
from pydantic import BaseModel, SecretStr
from structlog.testing import capture_logs

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError
from adapters.llm.fallback import FallbackLLMProvider, capture_fallbacks
from adapters.llm.openai_compatible import (
    OpenAICompatibleProvider,
    ProviderTimeoutError,
    StructuredOutputError,
    StructuredPrompts,
)
from adapters.llm.router import ModelChoice, ModelRouter
from adapters.llm.usage import (
    LLM_USAGE_TABLE,
    InMemoryUsageRecorder,
    UsageRecord,
    usage_scope,
)
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.llm import renewal_test_suite

FAKE_KEY = "test-key"
CRED_URL = "https://usuario-ficticio:clave-ficticia-9f3@llm.example/v1"
BODY_MARKER = "MARCADOR-CUERPO-NO-MOSTRAR"
PROMPT_MARKER = "MARCADOR-PROMPT-NO-REGISTRAR"
INPUT_MARKER = "MARCADOR-ENTRADA-NO-MOSTRAR"

MESSAGES = [
    Message(role="system", content="Eres un analista funcional ficticio."),
    Message(role="user", content=f"Necesidad ficticia de Villaficticia. {PROMPT_MARKER}"),
]

TEST_PROMPTS = StructuredPrompts(
    json_mode="INSTRUCCION-JSON-FICTICIA\n{schema}",
    retry="REINTENTO-FICTICIO\n{errors}",
)


class Answer(BaseModel):
    title: str
    score: int


VALID_ANSWER = '{"title": "Respuesta ficticia", "score": 7}'


# --- servidor falso ------------------------------------------------------------------------


def completion(content: str, *, usage: Any = ..., tokens: tuple[int, int] = (10, 5)) -> Any:
    body: dict[str, Any] = {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "modelo-de-la-respuesta",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is ...:
        body["usage"] = {
            "prompt_tokens": tokens[0],
            "completion_tokens": tokens[1],
            "total_tokens": sum(tokens),
        }
    elif usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def error_response(
    status: int, *, headers: dict[str, str] | None = None, param: str | None = None
) -> httpx.Response:
    error: dict[str, Any] = {
        "message": f"{BODY_MARKER} detalle interno {CRED_URL}",
        "type": "invalid_request_error",
    }
    if param is not None:
        error["param"] = param
    return httpx.Response(status, json={"error": error}, headers=headers or {})


def schema_rejected() -> httpx.Response:
    """400 de un proveedor que no admite JSON Schema (PA-16)."""
    return error_response(400, param="response_format")


Reply = httpx.Response | Exception


@dataclass
class FakeServer:
    """Devuelve las respuestas en orden (la última se repite) y registra cada petición."""

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


def timeout_error() -> httpx.ReadTimeout:
    return httpx.ReadTimeout(f"lectura agotada {CRED_URL} {BODY_MARKER}")


@dataclass
class Built:
    provider: OpenAICompatibleProvider
    server: FakeServer
    sleeps: list[float]


def build(name: str, *replies: Reply, model: str = "modelo-ficticio", **kwargs: Any) -> Built:
    """Proveedor real con el cliente del SDK sobre `httpx.MockTransport`."""
    server = FakeServer(list(replies))
    sleeps: list[float] = []
    client = openai.OpenAI(
        base_url=CRED_URL,
        api_key=FAKE_KEY,
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
    )
    kwargs.setdefault("prompts", TEST_PROMPTS)
    kwargs.setdefault("sleep", sleeps.append)
    provider = OpenAICompatibleProvider(name, model, client, **kwargs)
    return Built(provider, server, sleeps)


def chain_of(*providers: LLMProvider) -> Callable[[TaskType], list[LLMProvider]]:
    return lambda _task: list(providers)


def assert_safe(text: str) -> None:
    """Sin clave, cuerpo, URL con credenciales, prompt ni restos de pydantic."""
    for forbidden in (
        FAKE_KEY,
        BODY_MARKER,
        "clave-ficticia-9f3",
        "llm.example",
        PROMPT_MARKER,
        INPUT_MARKER,
        "input_value",
        "errors.pydantic.dev",
    ):
        assert forbidden not in text, forbidden


def story_json(**changes: Any) -> str:
    data = dataset.renewal_story(jira_key=None).model_dump(mode="json")
    data.update(changes)
    return json.dumps(data, ensure_ascii=False)


# --- RNF-28 · salida estructurada y un único reintento -------------------------------------


def test_structured_sends_max_tokens_in_schema_json_mode_and_retry_requests() -> None:
    """RNF-27 · `limits.max_output_tokens`: el tope va en JSON Schema, modo JSON y reintento."""
    built = build(
        "local",
        schema_rejected(),
        completion('{"title": "sin score"}'),
        completion(VALID_ANSWER),
        max_output_tokens={TaskType.GENERATE_STORY: 321},
    )

    built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    bodies = built.server.bodies()
    assert [b["response_format"]["type"] for b in bodies] == [
        "json_schema",
        "json_object",
        "json_object",
    ]
    assert [b.get("max_tokens") for b in bodies] == [321, 321, 321]


def test_structured_sends_no_max_tokens_when_task_has_no_cap() -> None:
    """RNF-27 (límite): una tarea sin tope en `max_output_tokens` no envía `max_tokens`."""
    built = build(
        "local",
        completion("{no json"),
        completion(VALID_ANSWER),
        max_output_tokens={TaskType.GENERATE_STORY: 321},
    )

    built.provider.generate_structured(MESSAGES, Answer, TaskType.NL_TO_JQL)

    assert all("max_tokens" not in b for b in built.server.bodies())


def test_structured_retry_feedback_omits_input_values_when_validation_fails() -> None:
    """RNF-28 · RNF-02: el texto `{errors}` del reintento no lleva valores de entrada."""
    built = build(
        "local",
        completion(json.dumps({"title": "t", "score": INPUT_MARKER})),
        completion(VALID_ANSWER),
    )

    built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    feedback = built.server.bodies()[1]["messages"][-1]["content"]
    assert feedback.startswith("REINTENTO-FICTICIO\n")
    assert "score" in feedback
    assert INPUT_MARKER not in feedback
    assert "input_value" not in feedback


def test_structured_error_is_spanish_and_has_no_model_output_when_invalid_twice() -> None:
    """RNF-28 · RNF-02: el error final está en español y no muestra la salida ni pydantic."""
    bad = completion(json.dumps({"title": INPUT_MARKER, "score": "x"}))
    built = build("local", bad, bad)

    with pytest.raises(StructuredOutputError) as info:
        built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    text = str(info.value)
    assert "no devolvió una respuesta válida" in text
    assert_safe(text)
    assert info.value.__cause__ is None
    assert len(built.server.requests) == 2


def test_structured_makes_at_most_two_requests_when_output_never_valid() -> None:
    """RNF-28 (límite): nunca más de un reintento, aunque la reparación de IDs no baste."""
    bad_ids = story_json(
        acceptance_criteria=[
            {"id": "CA1", "title": "Ficticio", "given": [], "when": ["w"], "then": ["t"]}
        ]
    )
    built = build("local", completion(bad_ids))

    with pytest.raises(StructuredOutputError):
        built.provider.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)

    assert len(built.server.requests) == 2


def test_structured_result_sums_tokens_of_both_requests_when_retried() -> None:
    """RF-43: el resultado suma los tokens de la petición inicial y del reintento."""
    built = build(
        "local",
        completion("{no json", tokens=(100, 20)),
        completion(VALID_ANSWER, tokens=(130, 9)),
    )

    result = built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert (result.input_tokens, result.output_tokens) == (230, 29)


# --- T-58 · reparación de IDs y schema_hints -----------------------------------------------


def test_structured_repairs_story_ids_without_retry_and_keeps_original_in_text() -> None:
    """T-58: IDs copiados de las fuentes se renumeran sin volver a llamar al LLM."""
    data = json.loads(story_json())
    data["business_rules"] = [
        {"id": "RN-RES-01", "description": "Regla ficticia uno"},
        {"id": "RN-02", "description": "Regla ficticia dos"},
    ]
    built = build("local", completion(json.dumps(data, ensure_ascii=False)))

    result = built.provider.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)

    rules = result.content.business_rules
    assert [r.id for r in rules] == ["RN-03", "RN-02"]
    assert rules[0].description.endswith("(ref. original: RN-RES-01)")
    assert len(built.server.requests) == 1


def test_structured_repair_log_has_no_content_when_ids_repaired() -> None:
    """T-58 · RNF-02: el log de la reparación no lleva textos ni IDs originales."""
    data = json.loads(story_json())
    data["business_rules"] = [{"id": f"RN-{INPUT_MARKER}", "description": "Regla ficticia"}]
    built = build("local", completion(json.dumps(data, ensure_ascii=False)))

    with capture_logs() as logs:
        built.provider.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)

    repaired = [e for e in logs if e["event"] == "llm_output_repaired"]
    assert repaired and repaired[0]["repaired_ids"] == 1
    assert_safe(json.dumps(logs, default=str))


@pytest.mark.parametrize("schema", [UserStory, TestSuite])
def test_sent_schema_requires_sources_in_schema_request_and_retry(
    schema: type[BaseModel],
) -> None:
    """T-58 (ba1e52b): `sources` es obligatorio (minItems 1) también en el reintento."""
    built = build("local", completion("{no json"), completion("{no json"))

    with pytest.raises(StructuredOutputError):
        built.provider.generate_structured(MESSAGES, schema, TaskType.GENERATE_STORY)

    for body in built.server.bodies():
        sent = body["response_format"]["json_schema"]["schema"]
        assert "sources" in sent["required"]
        assert sent["properties"]["sources"]["minItems"] == 1
        assert "default" not in sent["properties"]["sources"]


def test_sent_schema_requires_sources_when_json_mode_retry() -> None:
    """T-58: en modo JSON el esquema del prompt pide `sources` en la petición y el reintento."""
    built = build("local", schema_rejected(), completion("{no json"), completion("{no json"))

    with pytest.raises(StructuredOutputError):
        built.provider.generate_structured(MESSAGES, TestSuite, TaskType.GENERATE_TESTS)

    for body in built.server.bodies()[1:]:
        system = [m["content"] for m in body["messages"] if m["role"] == "system"][-1]
        sent = json.loads(system.split("\n", 1)[1])
        assert "sources" in sent["required"]
        assert sent["properties"]["sources"]["minItems"] == 1


def test_sent_schema_does_not_force_sources_when_schema_not_cited() -> None:
    """T-58 (límite): `QualityReport` tiene `sources` pero no se fuerza en el esquema enviado."""
    built = build("local", completion("{no json"), completion("{no json"))

    with pytest.raises(StructuredOutputError):
        built.provider.generate_structured(MESSAGES, QualityReport, TaskType.REVIEW_STORY)

    sent = built.server.bodies()[0]["response_format"]["json_schema"]["schema"]
    assert "sources" not in sent.get("required", [])
    assert sent == QualityReport.model_json_schema()


def test_structured_accepts_suite_without_sources_when_model_omits_them() -> None:
    """T-58: la validación pydantic sigue admitiendo `sources` vacío (no hay reintento)."""
    suite = renewal_test_suite().model_dump(mode="json")
    suite.pop("sources", None)
    built = build("local", completion(json.dumps(suite, ensure_ascii=False)))

    result = built.provider.generate_structured(MESSAGES, TestSuite, TaskType.GENERATE_TESTS)

    assert result.content.sources == []
    assert len(built.server.requests) == 1


# --- PA-16 · JSON Schema → modo JSON ------------------------------------------------------


@pytest.mark.parametrize(
    "param",
    ["response_format", "response_format.json_schema", "response_format.json_schema.schema"],
)
def test_structured_switches_to_json_mode_when_400_param_is_response_format(param: str) -> None:
    """PA-16: un 400 cuyo `param` es `response_format…` pasa a modo JSON en la misma llamada."""
    built = build("local", error_response(400, param=param), completion(VALID_ANSWER))

    result = built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.score == 7
    assert [b["response_format"]["type"] for b in built.server.bodies()] == [
        "json_schema",
        "json_object",
    ]


@pytest.mark.parametrize("param", ["messages", "max_tokens", None])
def test_structured_keeps_json_schema_and_fails_when_400_is_not_about_format(
    param: str | None,
) -> None:
    """PA-16 (negativa): un 400 por otra causa no desactiva JSON Schema ni tiene reintento."""
    built = build("local", error_response(400, param=param), completion(VALID_ANSWER))

    with pytest.raises(ExternalServiceError) as info:
        built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert "HTTP 400" in str(info.value)
    assert_safe(str(info.value))
    assert len(built.server.requests) == 1
    built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)
    assert built.server.bodies()[-1]["response_format"]["type"] == "json_schema"


def test_json_schema_rejection_in_one_provider_does_not_affect_next_one() -> None:
    """PA-16 · RF-44: el modo JSON se recuerda por proveedor, no para toda la cadena."""
    first = build("p1", schema_rejected(), error_response(500))
    second = build("p2", completion(VALID_ANSWER))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert second.server.bodies()[0]["response_format"]["type"] == "json_schema"


# --- RNF-27 · 429 con retry-after y umbral ------------------------------------------------


def test_chain_moves_on_without_sleeping_when_retry_after_exceeds_threshold() -> None:
    """RNF-27 · RF-44: `retry-after` > umbral → al siguiente sin dormir ni repetir."""
    first = build("p1", error_response(429, headers={"retry-after": "3600"}), max_wait_s=20.0)
    second = build("p2", completion(VALID_ANSWER))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    with capture_fallbacks() as events:
        result = llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.provider == "p2"
    assert first.sleeps == []
    assert len(first.server.requests) == 1
    assert [(e.provider, e.reason) for e in events] == [("p1", "limite")]


def test_provider_waits_retry_after_then_answers_when_within_threshold() -> None:
    """RNF-27: con `retry-after` dentro del umbral espera lo indicado y responde."""
    built = build(
        "p1",
        error_response(429, headers={"retry-after": "3"}),
        completion(VALID_ANSWER),
        max_wait_s=20.0,
    )

    result = built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.content.title == "Respuesta ficticia"
    assert built.sleeps == [3.0]


def test_provider_never_sleeps_more_than_threshold_per_wait_nor_retries_beyond_limit() -> None:
    """RNF-27 (límite): cada espera ≤ `max_wait_s` y como mucho `max_retries_on_429` esperas.

    Fija el comportamiento actual: el umbral es por espera y por petición, no acumulado.
    """
    built = build(
        "p1",
        error_response(429, headers={"retry-after": "20"}),
        max_wait_s=20.0,
        max_retries_on_429=2,
    )

    with pytest.raises(RateLimitError) as info:
        built.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert built.sleeps == [20.0, 20.0]
    assert len(built.server.requests) == 3
    assert info.value.retry_after == 20.0
    assert_safe(str(info.value))


def test_rate_limit_error_of_exhausted_chain_is_spanish_and_has_min_retry_after() -> None:
    """RNF-27 · RNF-02: cadena agotada por límites → `RateLimitError` en español, sin cuerpos."""
    first = build("p1", error_response(429, headers={"retry-after": "900"}))
    second = build("p2", error_response(429, headers={"retry-after": "120"}))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    with pytest.raises(RateLimitError) as info:
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert info.value.retry_after == 120.0
    assert "límite de uso" in str(info.value)
    assert_safe(str(info.value))
    assert first.sleeps == second.sleeps == []


# --- RNF-12 · tiempo agotado ---------------------------------------------------------------


def test_timeout_on_retry_request_fails_provider_and_chain_uses_next() -> None:
    """RNF-12 · RF-44: si el reintento agota el tiempo, el proveedor falla y se pasa al siguiente.

    Sin bucle: el primero recibe exactamente dos peticiones y no duerme.
    """
    first = build("p1", completion("{no json"), timeout_error())
    second = build("p2", completion(VALID_ANSWER))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    with capture_fallbacks() as events:
        result = llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.provider == "p2"
    assert len(first.server.requests) == 2
    assert first.sleeps == []
    assert [(e.provider, e.reason) for e in events] == [("p1", "tiempo_espera")]


def test_timeout_in_json_mode_after_schema_rejection_makes_no_third_request() -> None:
    """RNF-12 · PA-16: 400 por formato y luego tiempo agotado → error, sin más peticiones."""
    built = build("p1", schema_rejected(), timeout_error())

    with pytest.raises(ProviderTimeoutError) as info:
        built.provider.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert len(built.server.requests) == 2
    assert "no ha respondido a tiempo" in str(info.value)
    assert_safe(str(info.value))


def test_chain_of_timeouts_tries_each_provider_once_and_raises_spanish_error() -> None:
    """RNF-12 (límite): todos agotan el tiempo → una petición por proveedor y error claro."""
    providers = [build(f"p{i}", timeout_error()) for i in range(3)]
    llm = FallbackLLMProvider(chain_of(*(b.provider for b in providers)))

    with capture_fallbacks() as events, pytest.raises(ExternalServiceError) as info:
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert [len(b.server.requests) for b in providers] == [1, 1, 1]
    assert [e.reason for e in events] == ["tiempo_espera"] * 3
    assert "han fallado" in str(info.value)
    assert_safe(str(info.value))


# --- PA-67 · motivo del cambio de proveedor ------------------------------------------------


def test_events_report_each_reason_in_order_with_real_providers() -> None:
    """PA-67: límite, tiempo agotado y error → tres eventos con su motivo y mensaje seguro."""
    limited = build("p-limite", error_response(429, headers={"retry-after": "999"}))
    slow = build("p-lento", timeout_error())
    broken = build("p-roto", error_response(503))
    good = build("p-bueno", completion(VALID_ANSWER))
    llm = FallbackLLMProvider(
        chain_of(limited.provider, slow.provider, broken.provider, good.provider)
    )

    with capture_fallbacks() as events:
        result = llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert result.provider == "p-bueno"
    assert [(e.provider, e.model, e.reason) for e in events] == [
        ("p-limite", "modelo-ficticio", "limite"),
        ("p-lento", "modelo-ficticio", "tiempo_espera"),
        ("p-roto", "modelo-ficticio", "error"),
    ]
    assert [e.message for e in events] == [
        "p-limite ha alcanzado su límite de uso.",
        "p-lento no ha respondido a tiempo.",
        "p-roto ha fallado.",
    ]
    for event in events:
        assert event.task is TaskType.GENERATE_STORY
        assert_safe(event.message)


def test_authentication_failure_is_reported_as_error_and_chain_continues() -> None:
    """PA-67 · RF-44: una clave rechazada (401) es motivo «error» y se usa el siguiente."""
    rejected = build("p-clave", error_response(401))
    good = build("p-bueno", completion("hola ficticio"))
    llm = FallbackLLMProvider(chain_of(rejected.provider, good.provider))

    with capture_fallbacks() as events:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "hola ficticio"
    assert [e.reason for e in events] == ["error"]


# --- RNF-02 · errores al llamante sin datos internos ---------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404, 408, 409, 413, 422, 500, 502, 503])
def test_status_errors_are_spanish_and_hide_body_key_and_url(status: int) -> None:
    """RNF-02 · §8: cualquier estado HTTP da un error en español sin cuerpo, clave ni URL."""
    built = build("p1", error_response(status))

    with pytest.raises(ExternalServiceError) as info:
        built.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    text = str(info.value)
    assert text.startswith("El proveedor p1")
    assert_safe(text)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__ is True
    assert info.value.service == "p1"
    if status in (401, 403):
        assert isinstance(info.value, AuthenticationError)


def test_connection_error_hides_url_with_credentials() -> None:
    """RNF-02: un fallo de conexión con la URL (con credenciales) en el texto no la muestra."""
    built = build("p1", httpx.ConnectError(f"no conecta con {CRED_URL} {BODY_MARKER}"))

    with capture_logs() as logs, pytest.raises(ExternalServiceError) as info:
        built.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert str(info.value) == "No se pudo conectar con el proveedor p1."
    assert_safe(json.dumps(logs, default=str))


def test_chain_logs_never_contain_prompt_key_url_or_body_when_everything_fails() -> None:
    """RNF-02 · CLAUDE.md: los logs de una cadena que falla entera no llevan datos internos."""
    limited = build("p1", error_response(429, headers={"retry-after": "1"}))
    slow = build("p2", timeout_error())
    rejected = build("p3", schema_rejected(), error_response(500))
    llm = FallbackLLMProvider(chain_of(limited.provider, slow.provider, rejected.provider))

    with capture_logs() as logs, pytest.raises(ExternalServiceError) as info:
        llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert {"llm_rate_limited", "llm_provider_failed", "llm_json_schema_unsupported"} <= {
        e["event"] for e in logs
    }
    assert_safe(json.dumps(logs, default=str))
    assert_safe(str(info.value))


def test_create_keeps_key_out_of_repr_errors_and_logs() -> None:
    """RNF-02: la clave llega como `SecretStr` y no aparece en repr, errores ni logs."""
    server = FakeServer([error_response(401)])
    provider = OpenAICompatibleProvider.create(
        "groq",
        "modelo-ficticio",
        "https://llm.example/v1",
        SecretStr(FAKE_KEY),
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        prompts=TEST_PROMPTS,
        sleep=lambda _s: None,
    )

    with capture_logs() as logs, pytest.raises(AuthenticationError) as info:
        provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert server.requests[0].headers["authorization"] == f"Bearer {FAKE_KEY}"
    assert FAKE_KEY not in repr(provider)
    assert FAKE_KEY not in str(info.value)
    assert FAKE_KEY not in json.dumps(logs, default=str)


# --- RF-43 · registro de uso ---------------------------------------------------------------


def test_usage_record_and_table_have_no_prompt_or_content_fields() -> None:
    """RF-43 · RNF-02: ni `UsageRecord` ni `llm_usage` guardan prompts ni respuestas."""
    names = {f.name for f in fields(UsageRecord)} | set(LLM_USAGE_TABLE.c.keys())
    for forbidden in ("prompt", "messages", "content", "response", "text", "body"):
        assert not any(forbidden in name for name in names), forbidden


def test_chain_records_summed_tokens_of_answering_provider_when_retried() -> None:
    """RF-43: tras un reintento se registra una fila con la suma de las dos peticiones."""
    recorder = InMemoryUsageRecorder()
    built = build(
        "p1",
        completion("{no json", tokens=(40, 4)),
        completion(VALID_ANSWER, tokens=(50, 6)),
    )
    llm = FallbackLLMProvider(chain_of(built.provider), recorder)
    artifact = uuid4()

    with usage_scope(artifact_id=artifact):
        llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_TESTS)

    [record] = recorder.records
    assert (record.provider, record.model, record.task) == (
        "p1",
        "modelo-ficticio",
        TaskType.GENERATE_TESTS,
    )
    assert (record.input_tokens, record.output_tokens) == (90, 10)
    assert record.artifact_id == artifact


def test_chain_records_only_answering_provider_when_first_rate_limited() -> None:
    """RF-43 · RF-44: un 429 no consume tokens; solo se registra el proveedor que responde."""
    recorder = InMemoryUsageRecorder()
    first = build("p1", error_response(429, headers={"retry-after": "999"}))
    second = build("p2", completion("hola ficticio", tokens=(7, 3)))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider), recorder)

    llm.generate(MESSAGES, TaskType.CLASSIFY_SOURCE)

    assert [(r.provider, r.total_tokens) for r in recorder.records] == [("p2", 10)]


def test_chain_records_consumed_tokens_when_structured_output_fails() -> None:
    """RF-43 · RNF-27: las peticiones que acaban en `StructuredOutputError` se registran."""
    recorder = InMemoryUsageRecorder()
    built = build("p1", completion("{no json", tokens=(40, 4)), completion("{no", tokens=(50, 6)))
    llm = FallbackLLMProvider(chain_of(built.provider), recorder)

    with pytest.raises(StructuredOutputError):
        llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert sum(r.total_tokens for r in recorder.records) == 100


def test_chain_records_tokens_of_failed_provider_when_its_retry_times_out() -> None:
    """RF-43 · RNF-27: los tokens ya consumidos por un proveedor que luego falla se registran."""
    recorder = InMemoryUsageRecorder()
    first = build("p1", completion("{no json", tokens=(40, 4)), timeout_error())
    second = build("p2", completion(VALID_ANSWER, tokens=(7, 3)))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider), recorder)

    llm.generate_structured(MESSAGES, Answer, TaskType.GENERATE_STORY)

    assert sum(r.total_tokens for r in recorder.records) == 54


def test_generate_estimates_tokens_when_usage_is_null() -> None:
    """RF-43 (límite): `usage: null` → tokens estimados y la respuesta se conserva."""
    built = build("p1", completion("hola ficticio", usage=None))

    result = built.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "hola ficticio"
    assert result.input_tokens >= 1
    assert result.output_tokens >= 1


@pytest.mark.parametrize(
    "usage",
    [
        {"total_tokens": 15},
        {"prompt_tokens": None, "completion_tokens": None, "total_tokens": 15},
    ],
)
def test_generate_keeps_answer_and_estimates_tokens_when_usage_incomplete(
    usage: dict[str, Any],
) -> None:
    """RNF-12 · RF-43: una respuesta correcta no se pierde por un `usage` incompleto."""
    built = build("p1", completion("hola ficticio", usage=usage))

    result = built.provider.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.content == "hola ficticio"
    assert result.input_tokens >= 1


def test_chain_uses_next_provider_with_safe_error_when_usage_is_negative() -> None:
    """RNF-02 · RF-44: un `usage` incoherente es fallo del proveedor, con error seguro."""
    first = build("p1", completion("hola ficticio", tokens=(-4, 2)))
    second = build("p2", completion("hola ficticio", tokens=(3, 1)))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    with capture_fallbacks() as events:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.provider == "p2"
    assert [e.reason for e in events] == ["error"]


def test_llm_call_log_includes_artifact_id_when_inside_usage_scope() -> None:
    """CLAUDE.md (logs) · RF-43: el log de cada llamada lleva el `artifact_id` del ámbito."""
    built = build("p1", completion("hola ficticio"))
    llm = FallbackLLMProvider(chain_of(built.provider), InMemoryUsageRecorder())
    artifact = uuid4()

    with capture_logs() as logs, usage_scope(artifact_id=artifact):
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    [call] = [e for e in logs if e["event"] == "llm_call"]
    assert call["artifact_id"] == str(artifact) or call["artifact_id"] == artifact


# --- RF-42 · override del selector sobre la cadena -----------------------------------------


@dataclass
class StubProvider:
    """Proveedor mínimo: responde o lanza el error indicado; cuenta sus llamadas."""

    provider: str
    model: str
    error: Exception | None = None
    calls: int = 0

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResult(
            content=f"respuesta de {self.model}",
            provider=self.provider,
            model=self.model,
            input_tokens=1,
            output_tokens=1,
            latency_ms=0,
        )

    def generate_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        raise NotImplementedError


CONFIGURED = ModelChoice("nube", "modelo-configurado")
CHOSEN = ModelChoice("local", "modelo-elegido")


def router_with(errors: dict[ModelChoice, Exception]) -> tuple[ModelRouter, dict[str, Any]]:
    built: dict[str, StubProvider] = {}

    def factory(choice: ModelChoice) -> LLMProvider:
        stub = StubProvider(choice.provider, choice.model, errors.get(choice))
        built[choice.model] = stub
        return stub

    router = ModelRouter(
        {TaskType.GENERATE_STORY: [CONFIGURED], TaskType.NL_TO_JQL: [CONFIGURED]},
        factory,
        providers={"nube": True, "local": True, "sin-clave": False},
    )
    return router, built


def test_override_falls_back_to_configured_chain_when_chosen_model_rate_limited() -> None:
    """RF-42 · RF-44: si el modelo elegido en el selector falla, se usa la cadena configurada."""
    router, built = router_with({CHOSEN: RateLimitError("límite ficticio", service="local")})
    router.set_override(TaskType.GENERATE_STORY, CHOSEN)
    llm = FallbackLLMProvider(router.chain)

    with capture_fallbacks() as events:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.model == "modelo-configurado"
    assert built["modelo-elegido"].calls == 1
    assert [(e.provider, e.model, e.reason) for e in events] == [
        ("local", "modelo-elegido", "limite")
    ]


def test_override_affects_only_its_task_and_clear_restores_chain_in_fallback() -> None:
    """RF-42: el override solo cambia su tarea y `clear_override` vuelve a la configurada."""
    router, _ = router_with({})
    router.set_override(TaskType.GENERATE_STORY, CHOSEN)
    llm = FallbackLLMProvider(router.chain)

    assert llm.generate(MESSAGES, TaskType.GENERATE_STORY).model == "modelo-elegido"
    assert llm.generate(MESSAGES, TaskType.NL_TO_JQL).model == "modelo-configurado"
    router.clear_override(TaskType.GENERATE_STORY)
    assert llm.generate(MESSAGES, TaskType.GENERATE_STORY).model == "modelo-configurado"


def test_override_rejects_provider_without_key_and_keeps_previous_choice() -> None:
    """RF-42 (negativa): un proveedor sin clave se rechaza en español y no cambia la cadena."""
    router, _ = router_with({})
    router.set_override(TaskType.GENERATE_STORY, CHOSEN)

    with pytest.raises(ValueError, match="no está disponible"):
        router.set_override(TaskType.GENERATE_STORY, ModelChoice("sin-clave", "m"))

    assert router.models_for(TaskType.GENERATE_STORY) == [CHOSEN, CONFIGURED]


def test_override_reuses_cached_provider_so_json_mode_memory_survives() -> None:
    """RF-42 · PA-16: el proveedor elegido se reutiliza entre llamadas (no se recrea)."""
    router, built = router_with({})
    router.set_override(TaskType.GENERATE_STORY, CHOSEN)

    first = router.chain(TaskType.GENERATE_STORY)[0]
    router.clear_override(TaskType.GENERATE_STORY)
    router.set_override(TaskType.GENERATE_STORY, CHOSEN)

    assert router.chain(TaskType.GENERATE_STORY)[0] is first
    assert first is built["modelo-elegido"]


def test_provider_failed_log_includes_artifact_id_when_inside_usage_scope() -> None:
    """PA-194 · CLAUDE.md (logs): también `llm_provider_failed` lleva el `artifact_id`."""
    first = build("p1", timeout_error())
    second = build("p2", completion("hola ficticio"))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider), InMemoryUsageRecorder())
    artifact = uuid4()

    with capture_logs() as logs, usage_scope(artifact_id=artifact):
        llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    [failed] = [e for e in logs if e["event"] == "llm_provider_failed"]
    assert failed["artifact_id"] in (artifact, str(artifact))


@pytest.mark.parametrize("bad", [1.5, "3", True], ids=["decimal", "texto", "bool"])
def test_chain_uses_next_provider_when_usage_count_is_not_an_integer(bad: Any) -> None:
    """PA-193: un recuento de `usage` que no es un entero es fallo del proveedor."""
    first = build(
        "p1",
        completion("hola ficticio", usage={"prompt_tokens": bad, "completion_tokens": 2}),
    )
    second = build("p2", completion("hola ficticio", tokens=(3, 1)))
    llm = FallbackLLMProvider(chain_of(first.provider, second.provider))

    with capture_fallbacks() as events:
        result = llm.generate(MESSAGES, TaskType.GENERATE_STORY)

    assert result.provider == "p2"
    assert [e.reason for e in events] == ["error"]
