"""Validaciones de los tipos auxiliares de adapters/base.py (SPEC-00 §4, CA-00-03)."""

import pytest
from pydantic import ValidationError

from adapters import base
from adapters.base import (
    Chunk,
    IssueDetail,
    LLMResult,
    Message,
    PublishResult,
    StructuredResult,
    TaskType,
    User,
)
from schemas.user_story import UserStory
from tests.fakes import dataset

USAGE = {"provider": "fake", "model": "fake-model", "latency_ms": 0}


@pytest.mark.parametrize("role", ["system", "user", "assistant"])
def test_message_accepts_valid_roles(role: str) -> None:
    """CA-00-03: Message.role admite system, user y assistant."""
    assert Message(role=role, content="Hola (ficticio)").role == role


def test_message_rejects_unknown_role() -> None:
    """CA-00-03 (negativa): Message.role es un Literal cerrado."""
    with pytest.raises(ValidationError):
        Message(role="tool", content="x")


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "latency_ms"])
def test_llm_result_rejects_negative_usage(field: str) -> None:
    """CA-00-03 (negativa): tokens y latencia no pueden ser negativos."""
    data = {**USAGE, "input_tokens": 0, "output_tokens": 0, "content": "x", field: -1}
    with pytest.raises(ValidationError):
        LLMResult(**data)


def test_llm_result_accepts_zero_usage() -> None:
    """CA-00-03 (límite): 0 tokens es válido."""
    result = LLMResult(**USAGE, input_tokens=0, output_tokens=0, content="")
    assert result.input_tokens == result.output_tokens == 0


def test_structured_result_keeps_generic_type() -> None:
    """CA-00-03: StructuredResult[UserStory] valida y conserva el tipo del contenido."""
    story = dataset.renewal_story()
    result = StructuredResult[UserStory](
        **USAGE, input_tokens=1, output_tokens=1, content=story.model_dump()
    )
    assert isinstance(result.content, UserStory)
    assert result.content == story


def test_structured_result_rejects_content_of_wrong_type() -> None:
    """CA-00-03 (negativa): un contenido que no cumple el esquema falla."""
    with pytest.raises(ValidationError):
        StructuredResult[UserStory](
            **USAGE, input_tokens=1, output_tokens=1, content={"title": "incompleta"}
        )


def test_publish_result_defaults_to_empty_lists() -> None:
    """CA-00-03: PublishResult por defecto vacío y sin compartir listas entre instancias."""
    first, second = PublishResult(), PublishResult()
    assert first.created == [] and first.failed == []
    first.created.append("DEMO-501")
    assert second.created == []


@pytest.mark.parametrize("role", ["functional", "qa", "admin"])
def test_user_accepts_valid_roles(role: str) -> None:
    """CA-00-03: User.role admite functional, qa y admin."""
    assert User(username="demo", role=role).role == role


def test_user_rejects_unknown_role() -> None:
    """CA-00-03 (negativa): User.role es un Literal cerrado."""
    with pytest.raises(ValidationError):
        User(username="demo", role="superuser")


def test_chunk_rejects_negative_ordinal() -> None:
    """CA-00-03 (negativa): Chunk.ordinal >= 0."""
    with pytest.raises(ValidationError):
        Chunk(id="c", document_id="d", ordinal=-1, content="x")


def test_issue_detail_defaults_are_empty() -> None:
    """CA-00-03: IssueDetail tiene relaciones vacías por defecto."""
    issue = IssueDetail(key="DEMO-9", summary="Ficticia", issue_type="Story", status="Por hacer")
    assert issue.parent_key is None
    assert issue.links == issue.subtasks == issue.comments == issue.labels == []
    assert isinstance(issue, base.IssueSummary)


def test_task_type_values_are_snake_case_strings() -> None:
    """CA-00-03: TaskType es un StrEnum con las 8 tareas de config/models.yaml."""
    assert len(TaskType) == 8
    assert TaskType.GENERATE_STORY == "generate_story"
    assert all(t.value == t.value.lower() for t in TaskType)
