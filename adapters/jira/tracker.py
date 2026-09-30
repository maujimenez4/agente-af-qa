"""Adaptador de Jira Cloud con httpx sobre la API REST v3 (RF-01, RF-03, D-09).

T-11 implementa `test_connection` y `get_issue` (descripción ADF → texto y relaciones); T-14,
la búsqueda JQL paginada con `nextPageToken` (`/search/jql`), las épicas y las HU hijas. La
escritura, solo desde el nodo `publish`, llega en T-27.

Con tokens con scopes (RNF-04), las peticiones van a `api.atlassian.com/ex/jira/{cloudId}`.
Las lecturas se reintentan con backoff ante 429 y 5xx (SPEC-00 §8).
"""

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from adapters.base import IssueDetail, IssueLink, IssueSummary, ProjectSummary
from adapters.errors import (
    AuthenticationError,
    ExternalServiceError,
    NotFoundError,
    RateLimitError,
)
from adapters.jira.adf import adf_to_text
from adapters.jira.jql import PROJECT_KEY_RE, children_jql, epics_jql
from schemas.user_story import UserStory

JIRA_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
ISSUE_FIELDS = "summary,issuetype,status,description,parent,subtasks,issuelinks,comment,labels"
_GATEWAY = "https://api.atlassian.com/ex/jira"
_CLOUD_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
_MAX_KEY_IN_MESSAGE = 50
SEARCH_FIELDS = "summary,issuetype,status"
PAGE_SIZE = 100
MAX_RESULTS = 1000  # tope por búsqueda: el MVP trabaja con un proyecto pequeño
_SERVICE = "jira"


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
        if cloud_id is not None and cloud_id.get_secret_value():
            if not _CLOUD_ID_RE.fullmatch(cloud_id.get_secret_value()):
                raise AuthenticationError(
                    "JIRA_CLOUD_ID no tiene un formato válido.", service=_SERVICE
                )
            self._api_root = f"{_GATEWAY}/{cloud_id.get_secret_value()}"
        else:
            # Basic auth: las credenciales solo pueden viajar cifradas.
            if not base_url.lower().startswith("https://"):
                raise AuthenticationError(
                    "JIRA_BASE_URL debe empezar por https://.", service=_SERVICE
                )
            self._api_root = base_url.rstrip("/")
        self._auth = httpx.BasicAuth(email.get_secret_value(), api_token.get_secret_value())
        self._client = http_client or httpx.Client(timeout=timeout)
        self._timeout = timeout
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._sleep = sleep

    @property
    def api_root(self) -> str:
        return self._api_root

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
            results += [_to_summary(issue) for issue in issues[:remaining]]
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

    def create_story(self, story: UserStory, epic_key: str | None) -> str:
        raise NotImplementedError("La creación de HU se implementa en T-27.")

    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
        raise NotImplementedError("La actualización de HU se implementa en T-27.")

    def link(
        self, from_key: str, to_key: str, link_type: str, comment_md: str | None = None
    ) -> None:
        raise NotImplementedError("Los vínculos se implementan en T-27.")

    # --- HTTP --------------------------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        key: str | None = None,
        invalid: str | None = None,
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = self._client.get(
                    f"{self._api_root}{path}",
                    params=params,
                    auth=self._auth,
                    headers={"Accept": "application/json"},
                    timeout=self._timeout,
                )
            except httpx.HTTPError:
                if attempt < self._max_retries:
                    self._sleep(min(float(2**attempt), self._max_wait_s))
                    attempt += 1
                    continue
                raise ExternalServiceError(
                    "No se pudo conectar con Jira. Revisa la URL del sitio y la red.",
                    service=_SERVICE,
                ) from None

            status = response.status_code
            if status < 400:
                if not response.content:
                    return {}
                try:
                    return response.json()
                except ValueError:
                    raise ExternalServiceError(
                        "Jira ha devuelto una respuesta no válida.", service=_SERVICE
                    ) from None
            if status in (401, 403):
                raise AuthenticationError(
                    f"Jira ha rechazado las credenciales (HTTP {status}). Revisa el email, "
                    "el token y sus scopes.",
                    service=_SERVICE,
                )
            if status == 400 and invalid:
                raise ExternalServiceError(
                    f"{invalid} no es válida para Jira (HTTP 400).", service=_SERVICE
                )
            if status == 404:
                target = f"La incidencia {key}" if key else "El recurso solicitado"
                raise NotFoundError(
                    f"{target} no existe o no tienes permiso para verla.", service=_SERVICE
                )
            if status == 429:
                retry_after = _retry_after(response)
                wait = retry_after if retry_after is not None else float(2**attempt)
                if attempt >= self._max_retries or wait > self._max_wait_s:
                    raise RateLimitError(
                        "Jira ha alcanzado su límite de peticiones. Inténtalo más tarde.",
                        service=_SERVICE,
                        retry_after=retry_after,
                    )
                self._sleep(wait)
                attempt += 1
                continue
            if status >= 500 and attempt < self._max_retries:
                self._sleep(min(float(2**attempt), self._max_wait_s))
                attempt += 1
                continue
            raise ExternalServiceError(
                f"Jira ha respondido con un error (HTTP {status}).", service=_SERVICE
            )


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _name(field: Any) -> str:
    return str(field.get("name", "")) if isinstance(field, dict) else ""


def _to_summary(issue: dict[str, Any]) -> IssueSummary:
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
        **_to_summary(data).model_dump(),
        description_text=adf_to_text(fields.get("description")),
        parent_key=str(parent["key"]) if isinstance(parent, dict) and "key" in parent else None,
        subtasks=[_to_summary(s) for s in fields.get("subtasks") or []],
        links=[link for link in links if link is not None],
        comments=[adf_to_text(c.get("body")) for c in comments if isinstance(c, dict)],
        labels=[str(label) for label in fields.get("labels") or []],
    )
