"""Historia de Usuario con criterios de aceptación y reglas de negocio (SPEC-00 §3)."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from schemas.common import Priority, SourceRef, duplicated_ids

CRITERION_ID = r"^CA-\d+$"
RULE_ID = r"^RN-\d+$"


class AcceptanceCriterion(BaseModel):
    """Criterio de aceptación en Gherkin (RF-16)."""

    id: str = Field(pattern=CRITERION_ID)  # "CA-01"
    title: str = Field(min_length=1)
    given: list[str] = Field(min_length=1)
    when: list[str] = Field(min_length=1)
    then: list[str] = Field(min_length=1)


class BusinessRule(BaseModel):
    """Regla de negocio identificada (RF-17)."""

    id: str = Field(pattern=RULE_ID)  # "RN-01"
    description: str = Field(min_length=1)


class UserStory(BaseModel):
    """Plantilla completa de HU del proyecto (RF-15)."""

    internal_id: str | None = None  # "HU-XX" (R-05: prefijo en el título)
    jira_key: str | None = None
    title: str = Field(min_length=1)
    role: str
    action: str
    benefit: str
    description: str
    business_goal: str
    scope_includes: list[str]
    scope_excludes: list[str]
    acceptance_criteria: list[AcceptanceCriterion] = Field(min_length=1)
    business_rules: list[BusinessRule]
    assumptions: list[str]
    constraints: list[str]
    dependencies: list[str]
    alternate_flows: list[str]
    exceptions: list[str]
    related_features: list[str]
    changes_from_previous: list[str] = []
    related_requirements: list[str] = []
    priority: Priority
    sources: list[SourceRef] = []
    open_questions: list[str] = []

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        repeated = duplicated_ids([c.id for c in self.acceptance_criteria])
        repeated += duplicated_ids([r.id for r in self.business_rules])
        if repeated:
            raise ValueError(f"IDs repetidos en la HU: {', '.join(repeated)}")
        return self
