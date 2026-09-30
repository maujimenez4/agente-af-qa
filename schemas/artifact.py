"""Artefacto versionado que recorre el flujo de revisión y publicación (RF-34)."""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, PositiveInt, model_validator

from schemas.common import ArtifactStatus, ArtifactType
from schemas.impact import ImpactAnalysis
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

_CONTENT_BY_TYPE: dict[ArtifactType, type[BaseModel]] = {
    ArtifactType.USER_STORY: UserStory,
    ArtifactType.TEST_SUITE: TestSuite,
}


class Artifact(BaseModel):
    id: UUID
    type: ArtifactType
    status: ArtifactStatus
    version: PositiveInt
    origin_key: str | None
    content: UserStory | TestSuite
    impact: ImpactAnalysis | None = None
    created_by: str
    model_used: str | None = None
    prompt_version: str | None = None

    @model_validator(mode="after")
    def _content_matches_type(self) -> Self:
        expected = _CONTENT_BY_TYPE[self.type]
        if not isinstance(self.content, expected):
            raise ValueError(
                f"el contenido de un artefacto '{self.type.value}' debe ser {expected.__name__}"
            )
        return self
