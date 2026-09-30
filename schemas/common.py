"""Tipos comunes a todos los artefactos (SPEC-00 §3)."""

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Priority(StrEnum):
    MUST = "Must"
    SHOULD = "Should"
    COULD = "Could"
    WONT = "Won't"


class ArtifactStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    DISCARDED = "discarded"


class ArtifactType(StrEnum):
    USER_STORY = "user_story"
    TEST_SUITE = "test_suite"


class SourceRef(BaseModel):
    """Fuente citada por un artefacto (RF-21, RNF-14)."""

    kind: Literal["jira", "rag", "memory"]
    ref: str = Field(min_length=1)  # clave de Jira, id de documento o id de memoria
    excerpt: str | None = None  # breve, para mostrar la cita (RF-21)


def duplicated_ids(ids: list[str]) -> list[str]:
    """IDs que aparecen más de una vez, ordenados."""
    return sorted(i for i, n in Counter(ids).items() if n > 1)
