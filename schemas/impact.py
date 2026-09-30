"""Diff por campo y análisis de impacto de la evolución de una HU (RF-19)."""

from typing import Literal

from pydantic import BaseModel, Field


class StoryDiff(BaseModel):
    field: str = Field(min_length=1)
    before: str | None
    after: str | None


class ImpactItem(BaseModel):
    jira_key: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    kind: Literal["story", "rule", "dependency", "regression"]


class ImpactAnalysis(BaseModel):
    diffs: list[StoryDiff]
    affected: list[ImpactItem]
    regression_notes: list[str]
