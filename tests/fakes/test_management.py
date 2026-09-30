"""Fake de TestManagement (Jira nativo: subtareas + adjuntos), con fallos configurables."""

from dataclasses import dataclass, field

from adapters.base import IssueSummary, PublishResult
from schemas.test_case import TestSuite


@dataclass
class FakeTestManagement:
    """`fail_case_ids` simula fallos parciales (RNF-13); `attachments` guarda los adjuntos."""

    __test__ = False  # evita que pytest lo tome por una clase de pruebas

    fail_case_ids: set[str] = field(default_factory=set)
    cases: dict[str, list[IssueSummary]] = field(default_factory=dict)
    attachments: dict[str, dict[str, str]] = field(default_factory=dict)
    publish_calls: int = 0
    _next_number: int = 500

    def publish_suite(self, suite: TestSuite) -> PublishResult:
        self.publish_calls += 1
        result = PublishResult()
        story_cases = self.cases.setdefault(suite.story_jira_key, [])
        for case in suite.cases:
            if case.internal_id in self.fail_case_ids:
                result.failed.append(case.internal_id)
                continue
            self._next_number += 1
            key = f"DEMO-{self._next_number}"
            story_cases.append(
                IssueSummary(
                    key=key,
                    summary=f"[{case.internal_id}] {case.title}",
                    issue_type="Subtarea",
                    status="Por hacer",
                )
            )
            result.created.append(key)
        self.attachments[suite.story_jira_key] = {
            f"estrategia-{suite.story_jira_key}.md": suite.strategy_md,
            f"matriz-{suite.story_jira_key}.md": suite.coverage_md(),
        }
        return result

    def list_cases(self, story_key: str) -> list[IssueSummary]:
        return list(self.cases.get(story_key, []))
