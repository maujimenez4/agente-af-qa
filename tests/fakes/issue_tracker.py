"""Fake de IssueTracker en memoria sobre el conjunto de datos sintético."""

import re
from dataclasses import dataclass, field
from typing import Any

from adapters.base import IssueDetail, IssueLink, IssueSummary, ProjectSummary
from adapters.errors import AuthenticationError, NotFoundError
from schemas.user_story import UserStory
from tests.fakes import dataset


@dataclass
class FakeIssueTracker:
    """Lectura sobre `dataset`; las escrituras se guardan en `writes` para poder comprobarlas."""

    issues: dict[str, IssueDetail] = field(
        default_factory=lambda: {
            dataset.EPIC_KEY: dataset.EPIC.model_copy(deep=True),
            **{k: v.model_copy(deep=True) for k, v in dataset.STORIES.items()},
        }
    )
    writes: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    connected: bool = True
    _next_number: int = 100

    def test_connection(self) -> None:
        if not self.connected:
            raise AuthenticationError("No se pudo conectar con Jira (fake).", service="jira")

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        """Admite `text ~ "…"`, `parent = CLAVE` y `key = CLAVE`; otra JQL devuelve todo."""
        issues = list(self.issues.values())
        if match := re.search(r'text\s*~\s*"([^"]+)"', jql):
            words = match.group(1).lower().split()
            issues = [
                i
                for i in issues
                if all(w in f"{i.summary} {i.description_text}".lower() for w in words)
            ]
        if match := re.search(r"parent\s*=\s*([A-Z]+-\d+)", jql):
            issues = [i for i in issues if i.parent_key == match.group(1)]
        if match := re.search(r"key\s*=\s*([A-Z]+-\d+)", jql):
            issues = [i for i in issues if i.key == match.group(1)]
        return [dataset.summary_of(i) for i in issues[:limit]]

    def get_issue(self, key: str) -> IssueDetail:
        try:
            return self.issues[key].model_copy(deep=True)
        except KeyError:
            raise NotFoundError(f"La incidencia {key} no existe.", service="jira") from None

    def list_projects(self) -> list[ProjectSummary]:
        return [ProjectSummary(key=dataset.PROJECT_KEY, name=dataset.PROJECT_NAME)]

    def list_epics(self, project: str) -> list[IssueSummary]:
        return [
            dataset.summary_of(i)
            for i in self.issues.values()
            if i.issue_type == "Epic" and i.key.startswith(f"{project}-")
        ]

    def list_children(self, epic_key: str) -> list[IssueSummary]:
        return [dataset.summary_of(i) for i in self.issues.values() if i.parent_key == epic_key]

    # --- ESCRITURA ---

    def create_story(self, story: UserStory, epic_key: str | None) -> str:
        self._next_number += 1
        key = f"{dataset.PROJECT_KEY}-{self._next_number}"
        prefix = f"[{story.internal_id}] " if story.internal_id else ""
        self.issues[key] = IssueDetail(
            key=key,
            summary=f"{prefix}{story.title}",
            issue_type="Story",
            status="Por hacer",
            parent_key=epic_key,
            description_text=story.description,
        )
        self.writes.append(("create_story", {"key": key, "epic_key": epic_key}))
        return key

    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
        issue = self.get_issue(key)
        issue.description_text = story.description
        issue.comments.append(diff_comment_md)
        self.issues[key] = issue
        self.writes.append(("update_story", {"key": key}))

    def link(
        self, from_key: str, to_key: str, link_type: str, comment_md: str | None = None
    ) -> None:
        issue = self.get_issue(from_key)
        self.get_issue(to_key)
        issue.links.append(IssueLink(link_type=link_type, key=to_key))
        if comment_md:
            issue.comments.append(comment_md)
        self.issues[from_key] = issue
        self.writes.append(("link", {"from": from_key, "to": to_key, "type": link_type}))
