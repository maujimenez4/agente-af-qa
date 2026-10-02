"""Adaptador de Jira Cloud con httpx sobre la API REST v3 (RF-01, RF-03, D-09).

T-11 implementa `test_connection` y `get_issue` (descripción ADF → texto y relaciones); T-14,
la búsqueda JQL paginada con `nextPageToken` (`/search/jql`), las épicas y las HU hijas; T-27,
la escritura (`create_story`, `update_story`, `link`), solo desde el nodo `publish`.

Con tokens con scopes (RNF-04), las peticiones van a `api.atlassian.com/ex/jira/{cloudId}`.
El HTTP (lecturas con backoff, escrituras de un solo intento) está en `adapters/jira/http.py`.
"""

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from adapters.base import IssueDetail, IssueLink, IssueSummary, ProjectSummary
from adapters.errors import AgentError, ExternalServiceError, NotFoundError, PublishError
from adapters.jira.adf import adf_to_text, markdown_to_adf
from adapters.jira.http import SERVICE as _SERVICE
from adapters.jira.http import JiraHttp
from adapters.jira.jql import PROJECT_KEY_RE, children_jql, epics_jql
from adapters.jira.story_template import story_summary, story_to_adf
from schemas.user_story import UserStory

JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
ISSUE_FIELDS = "summary,issuetype,status,description,parent,subtasks,issuelinks,comment,labels"
_MAX_KEY_IN_MESSAGE = 50
SEARCH_FIELDS = "summary,issuetype,status"
PAGE_SIZE = 100
MAX_RESULTS = 1000  # tope por búsqueda: el MVP trabaja con un proyecto pequeño
# PA-200: el nombre del tipo depende del sitio («Story» / «Historia»); hasta que exista en
# `Settings`, constante.
STORY_ISSUE_TYPE = "Story"
LINK_TYPES = {"relates to": "Relates"}  # D-09: nombre del vínculo en la API de Jira


def _project_of(key: str) -> str:
    return key.rsplit("-", 1)[0]


class JiraCloudTracker:
    """Implementa `IssueTracker` contra Jira Cloud."""

    def __init__(
        self,
        base_url: str,
        email: SecretStr,
        api_token: SecretStr,
        *,
        cloud_id: SecretStr | None = None,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        max_wait_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        self._http = JiraHttp(
            base_url,
            email,
            api_token,
            cloud_id=cloud_id,
            http_client=http_client,
            max_retries=max_retries,
            max_wait_s=max_wait_s,
            sleep=sleep,
            timeout=timeout,
        )
        self._get = self._http.get
        self._send = self._http.send

    @property
    def api_root(self) -> str:
        return self._http.api_root

    # --- Lectura ---------------------------------------------------------------------------

    def test_connection(self) -> None:
        """Valida URL y credenciales (RF-01) con un endpoint cubierto por `read:jira-work`.

        `/myself` exigiría además `read:jira-user`: se evita para mantener los scopes mínimos
        del token (RNF-04).
        """
        self._get("/rest/api/3/project/search")

    def get_issue(self, key: str) -> IssueDetail:
        if not JIRA_KEY_RE.fullmatch(key):
            shown = key[:_MAX_KEY_IN_MESSAGE]
            raise NotFoundError(f"«{shown}» no es una clave de Jira válida.", service=_SERVICE)
        data = self._get(f"/rest/api/3/issue/{key}", params={"fields": ISSUE_FIELDS}, key=key)
        return _to_issue_detail(data)

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        """JQL de solo lectura, paginada con `nextPageToken` hasta `limit` (RF-02)."""
        if not jql.strip():
            raise ValueError("La consulta JQL está vacía.")
        remaining = min(limit, MAX_RESULTS)
        results: list[IssueSummary] = []
        token: str | None = None
        while remaining > 0:
            params = {
                "jql": jql,
                "maxResults": str(min(PAGE_SIZE, remaining)),
                "fields": SEARCH_FIELDS,
            }
            if token:
                params["nextPageToken"] = token
            page = self._get("/rest/api/3/search/jql", params=params, invalid="La consulta JQL")
            issues = page.get("issues") or []
            results += [to_issue_summary(issue) for issue in issues[:remaining]]
            remaining = min(limit, MAX_RESULTS) - len(results)
            token = page.get("nextPageToken")
            if not issues or not token or page.get("isLast", False):
                break
        return results

    def list_projects(self) -> list[ProjectSummary]:
        """Proyectos visibles con el token (RF-02), paginados con `startAt`/`isLast`."""
        projects: list[ProjectSummary] = []
        start = 0
        while start < MAX_RESULTS and len(projects) < MAX_RESULTS:
            params = {"startAt": str(start), "maxResults": str(PAGE_SIZE), "orderBy": "key"}
            page = self._get("/rest/api/3/project/search", params=params)
            values = page.get("values") or []
            projects += [
                ProjectSummary(key=str(v.get("key", "")), name=str(v.get("name") or ""))
                for v in values
                if v.get("key")
            ]
            start += len(values)
            if not values or page.get("isLast", True):
                break
        return projects[:MAX_RESULTS]

    def list_epics(self, project: str) -> list[IssueSummary]:
        if not PROJECT_KEY_RE.fullmatch(project):
            raise NotFoundError(
                f"«{project[:_MAX_KEY_IN_MESSAGE]}» no es una clave de proyecto válida.",
                service=_SERVICE,
            )
        return self.search(epics_jql(project), limit=MAX_RESULTS)

    def list_children(self, epic_key: str) -> list[IssueSummary]:
        if not JIRA_KEY_RE.fullmatch(epic_key):
            shown = epic_key[:_MAX_KEY_IN_MESSAGE]
            raise NotFoundError(f"«{shown}» no es una clave de Jira válida.", service=_SERVICE)
        return self.search(children_jql(epic_key), limit=MAX_RESULTS)

    # --- ESCRITURA: solo desde el nodo publish (T-27) ---------------------------------------
    # Sin reintentos (SPEC-00 §8): una escritura repetida podría duplicar la HU o el comentario.

    def create_story(self, story: UserStory, epic_key: str | None, project: str) -> str:
        """Crea la HU en `project` con la épica como `parent` (RF-04, R-05)."""
        if not PROJECT_KEY_RE.fullmatch(project):
            raise PublishError(
                f"«{project[:_MAX_KEY_IN_MESSAGE]}» no es una clave de proyecto válida."
            )
        fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": STORY_ISSUE_TYPE},
            "summary": story_summary(story),
            "description": story_to_adf(story),
        }
        if epic_key is not None:
            if not JIRA_KEY_RE.fullmatch(epic_key) or _project_of(epic_key) != project:
                raise PublishError(
                    f"La épica «{epic_key[:_MAX_KEY_IN_MESSAGE]}» no es del proyecto {project}."
                )
            fields["parent"] = {"key": epic_key}
        data = self._send("POST", "/rest/api/3/issue", {"fields": fields}, failure=PublishError)
        key = data.get("key")
        if not isinstance(key, str) or not JIRA_KEY_RE.fullmatch(key):
            raise PublishError(
                "Jira no ha devuelto la clave de la HU creada. Comprueba en Jira si se ha creado "
                "antes de reintentar."
            )
        if _project_of(key) != project:  # PA-46
            raise PublishError(
                f"Jira ha creado la HU {key} fuera del proyecto {project}. Revísala en Jira."
            )
        return key

    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
        """Actualiza título y descripción y comenta el diff aprobado (RF-05)."""
        if not JIRA_KEY_RE.fullmatch(key):
            raise PublishError(f"«{key[:_MAX_KEY_IN_MESSAGE]}» no es una clave de Jira válida.")
        fields = {"summary": story_summary(story), "description": story_to_adf(story)}
        self._send("PUT", f"/rest/api/3/issue/{key}", {"fields": fields}, PublishError, key)
        if not diff_comment_md.strip():
            return
        body = {"body": markdown_to_adf(diff_comment_md)}
        try:
            self._send("POST", f"/rest/api/3/issue/{key}/comment", body, PublishError, key)
        except AgentError as exc:
            raise PublishError(
                f"La HU {key} se ha actualizado, pero no se pudo añadir el comentario con el "
                f"diff: {exc}"
            ) from None

    def link(
        self, from_key: str, to_key: str, link_type: str, comment_md: str | None = None
    ) -> None:
        """Vínculo «relates to» con comentario opcional (RF-06).

        Los fallos al vincular son `ExternalServiceError` (y sus subclases): el nodo `publish`
        los informa sin perder la HU ya publicada (RNF-13). Un `link_type` no permitido es un
        error de programación y lanza `PublishError` antes de cualquier petición.
        """
        jira_link = LINK_TYPES.get(link_type)
        if jira_link is None:
            raise PublishError(f"El tipo de vínculo «{link_type[:50]}» no está permitido.")
        for issue_key in (from_key, to_key):
            if not JIRA_KEY_RE.fullmatch(issue_key):
                shown = issue_key[:_MAX_KEY_IN_MESSAGE]
                raise NotFoundError(f"«{shown}» no es una clave de Jira válida.", service=_SERVICE)
        if from_key == to_key:
            raise ExternalServiceError(
                f"No se puede vincular {from_key} consigo misma.", service=_SERVICE
            )
        body: dict[str, Any] = {
            "type": {"name": jira_link},
            "outwardIssue": {"key": from_key},
            "inwardIssue": {"key": to_key},
        }
        if comment_md and comment_md.strip():
            body["comment"] = {"body": markdown_to_adf(comment_md)}
        self._send("POST", "/rest/api/3/issueLink", body, ExternalServiceError)


def _name(field: Any) -> str:
    return str(field.get("name", "")) if isinstance(field, dict) else ""


def to_issue_summary(issue: dict[str, Any]) -> IssueSummary:
    fields = issue.get("fields") or {}
    return IssueSummary(
        key=str(issue.get("key", "")),
        summary=str(fields.get("summary") or ""),
        issue_type=_name(fields.get("issuetype")),
        status=_name(fields.get("status")),
    )


def _to_link(link: dict[str, Any]) -> IssueLink | None:
    link_type = link.get("type") or {}
    if outward := link.get("outwardIssue"):
        return IssueLink(link_type=str(link_type.get("outward", "")), key=str(outward["key"]))
    if inward := link.get("inwardIssue"):
        return IssueLink(link_type=str(link_type.get("inward", "")), key=str(inward["key"]))
    return None


def _to_issue_detail(data: dict[str, Any]) -> IssueDetail:
    fields = data.get("fields") or {}
    parent = fields.get("parent")
    comments = (fields.get("comment") or {}).get("comments") or []
    links = [_to_link(link) for link in fields.get("issuelinks") or []]
    return IssueDetail(
        **to_issue_summary(data).model_dump(),
        description_text=adf_to_text(fields.get("description")),
        parent_key=str(parent["key"]) if isinstance(parent, dict) and "key" in parent else None,
        subtasks=[to_issue_summary(s) for s in fields.get("subtasks") or []],
        links=[link for link in links if link is not None],
        comments=[adf_to_text(c.get("body")) for c in comments if isinstance(c, dict)],
        labels=[str(label) for label in fields.get("labels") or []],
    )
