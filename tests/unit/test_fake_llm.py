"""Comportamiento de FakeLLMProvider (CA-00-03)."""

import pytest
from pydantic import BaseModel, ValidationError

from adapters import base
from adapters.base import Message, TaskType
from adapters.errors import RateLimitError
from schemas import test_case as tc
from schemas.impact import ImpactAnalysis
from schemas.memory import Memory
from schemas.user_story import UserStory
from tests.fakes import FakeLLMProvider

MESSAGES = [
    Message(role="system", content="Eres un analista funcional ficticio."),
    Message(role="user", content="Genera la HU de renovación de préstamos."),
]


class _Note(BaseModel):
    text: str


def test_generate_returns_llm_result_with_tokens() -> None:
    """CA-00-03: generate devuelve LLMResult con texto, tokens > 0 y proveedor/modelo."""
    fake = FakeLLMProvider()
    result = fake.generate(MESSAGES, TaskType.REVIEW_STORY)
    assert isinstance(result, base.LLMResult)
    assert "review_story" in result.content
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert (result.provider, result.model) == ("fake", "fake-model")


def test_generate_records_call_with_task() -> None:
    """CA-00-03: cada llamada queda registrada en `calls` con su task."""
    fake = FakeLLMProvider()
    fake.generate(MESSAGES, TaskType.NL_TO_JQL)
    assert fake.calls == [{"task": TaskType.NL_TO_JQL, "schema": None, "messages": MESSAGES}]


@pytest.mark.parametrize(
    ("schema", "task"),
    [
        (UserStory, TaskType.GENERATE_STORY),
        (tc.TestSuite, TaskType.GENERATE_TESTS),
        (ImpactAnalysis, TaskType.ANALYZE_IMPACT),
        (Memory, TaskType.SYNTHESIZE_MEMORY),
    ],
    ids=["UserStory", "TestSuite", "ImpactAnalysis", "Memory"],
)
def test_generate_structured_returns_content_of_requested_type(
    schema: type[BaseModel], task: TaskType
) -> None:
    """CA-00-03: generate_structured devuelve StructuredResult con content del tipo pedido."""
    fake = FakeLLMProvider()
    result = fake.generate_structured(MESSAGES, schema, task)
    assert isinstance(result, base.StructuredResult)
    assert type(result.content) is schema
    assert result.input_tokens > 0
    assert result.output_tokens > 0
    assert fake.calls[-1]["task"] is task
    assert fake.calls[-1]["schema"] is schema


def test_generate_structured_story_has_no_jira_key() -> None:
    """CA-00-03: la HU generada aún no está publicada (sin clave de Jira)."""
    result = FakeLLMProvider().generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)
    assert result.content.jira_key is None


@pytest.mark.parametrize("structured", [False, True], ids=["generate", "generate_structured"])
def test_configured_error_is_raised_and_call_recorded(structured: bool) -> None:
    """CA-00-03 (error): `error` configurado (RateLimitError) se lanza en cada llamada."""
    fake = FakeLLMProvider(error=RateLimitError("Límite alcanzado (fake).", "groq", 1.5))
    with pytest.raises(RateLimitError) as info:
        if structured:
            fake.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)
        else:
            fake.generate(MESSAGES, TaskType.GENERATE_STORY)
    assert info.value.retry_after == 1.5
    assert len(fake.calls) == 1


def test_generate_structured_without_builder_raises_not_implemented() -> None:
    """CA-00-03 (error): esquema sin builder → NotImplementedError."""
    with pytest.raises(NotImplementedError, match="_Note"):
        FakeLLMProvider().generate_structured(MESSAGES, _Note, TaskType.CLASSIFY_SOURCE)


def test_generate_structured_uses_custom_builder() -> None:
    """CA-00-03: un builder personalizado sustituye la respuesta y recibe los mensajes."""
    received: list[list[Message]] = []

    def build(messages: list[Message]) -> _Note:
        received.append(messages)
        return _Note(text="Nota ficticia")

    fake = FakeLLMProvider(builders={_Note: build})
    result = fake.generate_structured(MESSAGES, _Note, TaskType.CLASSIFY_SOURCE)
    assert result.content == _Note(text="Nota ficticia")
    assert received == [MESSAGES]


def test_generate_structured_validates_builder_output_against_schema() -> None:
    """CA-00-03 (negativa): si el builder devuelve algo incompatible, falla la validación."""
    fake = FakeLLMProvider(builders={UserStory: lambda _m: _Note(text="no es una HU")})
    with pytest.raises(ValidationError):
        fake.generate_structured(MESSAGES, UserStory, TaskType.GENERATE_STORY)


def test_generate_structured_with_empty_messages_has_zero_input_tokens() -> None:
    """CA-00-03 (límite): sin mensajes, input_tokens = 0 y output_tokens > 0."""
    result = FakeLLMProvider().generate_structured([], Memory, TaskType.SYNTHESIZE_MEMORY)
    assert result.input_tokens == 0
    assert result.output_tokens > 0
