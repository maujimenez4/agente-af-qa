"""Fake de MemoryGenerator: construye la memoria a partir del artefacto, sin LLM."""

from dataclasses import dataclass, field

from schemas.artifact import Artifact
from schemas.memory import Memory
from schemas.test_case import TestSuite
from schemas.user_story import UserStory


@dataclass
class FakeMemoryGenerator:
    generated: list[Memory] = field(default_factory=list)

    def generate(self, artifact: Artifact) -> Memory:
        content = artifact.content
        if isinstance(content, UserStory):
            memory = self._from_story(artifact, content)
        elif isinstance(content, TestSuite):
            memory = self._from_suite(artifact, content)
        else:  # pragma: no cover - Artifact solo admite estos dos tipos
            raise TypeError(type(content).__name__)
        self.generated.append(memory)
        return memory

    @staticmethod
    def _jira_key(artifact: Artifact, fallback: str | None) -> str:
        key = fallback or artifact.origin_key
        if not key:
            raise ValueError("La memoria requiere la clave de Jira del artefacto publicado.")
        return key

    def _from_story(self, artifact: Artifact, story: UserStory) -> Memory:
        return Memory(
            artifact_type=artifact.type,
            jira_key=self._jira_key(artifact, story.jira_key),
            version=artifact.version,
            objective=story.business_goal,
            scope="; ".join(story.scope_includes),
            business_rules=[f"{r.id}: {r.description}" for r in story.business_rules],
            decisions=list(story.assumptions),
            dependencies=list(story.dependencies),
            changes=list(story.changes_from_previous),
            acceptance_criteria=[f"{c.id}: {c.title}" for c in story.acceptance_criteria],
            references=[s.ref for s in story.sources],
        )

    def _from_suite(self, artifact: Artifact, suite: TestSuite) -> Memory:
        return Memory(
            artifact_type=artifact.type,
            jira_key=self._jira_key(artifact, suite.story_jira_key),
            version=artifact.version,
            objective=f"Artefactos de QA de {suite.story_jira_key}",
            scope=f"{len(suite.cases)} casos de prueba",
            decisions=[],
            dependencies=list(suite.dependencies),
            changes=[],
            acceptance_criteria=[ref for ref in suite.coverage() if ref.startswith("CA-")],
            business_rules=[ref for ref in suite.coverage() if ref.startswith("RN-")],
            references=[s.ref for s in suite.sources],
        )
