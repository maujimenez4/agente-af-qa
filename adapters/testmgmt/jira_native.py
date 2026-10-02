"""`TestManagement` en Jira nativo (T-30: RF-30, RNF-13, D-09 §6.2, PA-05).

Cada CP es una subtarea de la HU con la etiqueta `caso-prueba`, etiquetas de trazabilidad
(`CA-01`, `RN-02`, `tipo-positivo`) y el título `[CP-XX] …` (R-05). La estrategia y la matriz de
cobertura van como adjuntos `.md` de la HU.

- **Publicación parcial (RNF-13):** los elementos se crean uno a uno; `PublishResult` devuelve
  las claves (`created`) y los CP o adjuntos que fallaron (`failed`).
- **Idempotencia (PA-05):** antes de publicar se buscan las subtareas CP de la HU
  (`list_cases`) y no se vuelve a crear un `[CP-XX]` que ya exista (su clave cuenta como
  publicada); un adjunto con el mismo nombre tampoco se vuelve a subir. Si la búsqueda falla, no
  se publica nada.
- Ante un 401/403 o un 429 se deja de escribir: el resto se marca como fallido sin intentarlo.
- Escrituras de un solo intento (`adapters/jira/http.py`); solo las llama el nodo `publish`.
"""

import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog
from pydantic import SecretStr

from adapters.base import IssueSummary, PublishResult
from adapters.errors import (
    AgentError,
    AuthenticationError,
    NotFoundError,
    PublishError,
    RateLimitError,
)
from adapters.jira.adf import Node, bullet_list, code_block, doc, heading, paragraph, table, text
from adapters.jira.http import SERVICE, JiraHttp
from adapters.jira.jql import CASE_LABEL, cases_jql
from adapters.jira.story_template import prefixed_summary
from adapters.jira.tracker import JIRA_KEY_RE, SEARCH_FIELDS, to_issue_summary
from schemas.test_case import TestCase, TestSuite

log = structlog.get_logger(__name__)

PAGE_SIZE = 100
MAX_CASES = 500  # tope de subtareas CP por HU en la búsqueda
_CASE_PREFIX = re.compile(r"^\[(CP-\d+)\]")
_MAX_KEY_IN_MESSAGE = 50
_MAX_SUBTASK_TYPE = 60
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")  # incluye `\r` y `\n`


class JiraNativeTests:
    """Implementa `TestManagement` con subtareas, etiquetas y adjuntos de Jira (D-09)."""

    def __init__(
        self,
        base_url: str,
        email: SecretStr,
        api_token: SecretStr,
        *,
        subtask_type: str,
        cloud_id: SecretStr | None = None,
        http_client: httpx.Client | None = None,
        max_retries: int = 2,
        max_wait_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        subtask_type = subtask_type.strip()  # los espacios de los extremos (`.env`) se quitan
        if (
            not subtask_type
            or len(subtask_type) > _MAX_SUBTASK_TYPE
            or _CONTROL.search(subtask_type)
        ):
            raise ValueError("JIRA_TEST_SUBTASK_TYPE debe ser el nombre de un tipo de subtarea.")
        self._subtask_type = subtask_type
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

    # --- Lectura -----------------------------------------------------------------------------

    def list_cases(self, story_key: str) -> list[IssueSummary]:
        """Subtareas CP de la HU (etiqueta `caso-prueba`), paginadas con `nextPageToken`."""
        if not JIRA_KEY_RE.fullmatch(story_key):
            shown = story_key[:_MAX_KEY_IN_MESSAGE]
            raise NotFoundError(f"«{shown}» no es una clave de Jira válida.", service=SERVICE)
        jql = cases_jql(story_key)
        cases: list[IssueSummary] = []
        token: str | None = None
        while len(cases) < MAX_CASES:
            params = {
                "jql": jql,
                "maxResults": str(min(PAGE_SIZE, MAX_CASES - len(cases))),
                "fields": SEARCH_FIELDS,
            }
            if token:
                params["nextPageToken"] = token
            page = self._http.get("/rest/api/3/search/jql", params=params, invalid="La consulta")
            issues = page.get("issues") or []
            cases += [to_issue_summary(issue) for issue in issues]
            token = page.get("nextPageToken")
            if not issues or not token or page.get("isLast", False):
                break
        return cases[:MAX_CASES]

    # --- ESCRITURA: solo desde el nodo publish -----------------------------------------------

    def publish_suite(self, suite: TestSuite) -> PublishResult:
        started = time.perf_counter()
        story = _checked_key(suite.story_jira_key)
        project = story.rsplit("-", 1)[0]
        existing = self._existing_cases(story)  # PA-05; si falla, no se escribe nada
        result = PublishResult()
        stopped = False
        for case in suite.cases:
            if case.internal_id in existing:
                result.created.append(existing[case.internal_id])
            elif stopped:
                result.failed.append(case.internal_id)
            else:
                try:
                    result.created.append(self._create_case(case, story, project))
                except (AuthenticationError, RateLimitError):
                    stopped = True
                    result.failed.append(case.internal_id)
                except AgentError:
                    result.failed.append(case.internal_id)
        self._attach_files(suite, story, result, stopped)
        log.info(
            "suite publicada en Jira",
            action="publish_suite",
            jira_key=story,
            created=len(result.created),
            reused=sum(1 for case in suite.cases if case.internal_id in existing),
            failed=len(result.failed),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return result

    def _existing_cases(self, story: str) -> dict[str, str]:
        existing: dict[str, str] = {}
        for issue in self.list_cases(story):
            match = _CASE_PREFIX.match(issue.summary)
            if match:
                existing.setdefault(match.group(1), issue.key)  # la primera, por orden de clave
        return existing

    def _create_case(self, case: TestCase, story: str, project: str) -> str:
        fields: dict[str, Any] = {
            "project": {"key": project},
            "parent": {"key": story},
            "issuetype": {"name": self._subtask_type},
            "summary": prefixed_summary(case.internal_id, case.title),
            "labels": case_labels(case),
            "description": case_to_adf(case, story),
        }
        data = self._http.send("POST", "/rest/api/3/issue", {"fields": fields}, PublishError)
        key = data.get("key")
        if not isinstance(key, str) or not JIRA_KEY_RE.fullmatch(key):
            raise PublishError(f"Jira no ha devuelto la clave de la subtarea {case.internal_id}.")
        if key.rsplit("-", 1)[0] != project:
            log.warning(
                "subtarea creada fuera del proyecto",
                action="publish_suite",
                jira_key=key,
                project=project,
            )
            raise PublishError(f"Jira ha creado {case.internal_id} ({key}) fuera de {project}.")
        return key

    def _attach_files(
        self, suite: TestSuite, story: str, result: PublishResult, stopped: bool
    ) -> None:
        files = attachment_files(suite)
        if stopped:
            result.failed += list(files)
            return
        try:
            present = self._attachment_names(story)
        except AgentError:  # sin saber qué hay, no se sube nada (PA-05)
            result.failed += list(files)
            return
        for name, content in files.items():
            if name in present:
                continue
            if stopped:
                result.failed.append(name)
                continue
            try:
                self._http.upload(
                    f"/rest/api/3/issue/{story}/attachments", name, content, PublishError, story
                )
            except (AuthenticationError, RateLimitError):
                stopped = True
                result.failed.append(name)
            except AgentError:
                result.failed.append(name)

    def _attachment_names(self, story: str) -> set[str]:
        data = self._http.get(
            f"/rest/api/3/issue/{story}", params={"fields": "attachment"}, key=story
        )
        attachments = (data.get("fields") or {}).get("attachment") or []
        return {str(a.get("filename")) for a in attachments if isinstance(a, dict)}


# --- Plantillas --------------------------------------------------------------------------------


def attachment_files(suite: TestSuite) -> dict[str, str]:
    """Adjuntos de la HU (§6.2): estrategia y matriz de cobertura."""
    key = _checked_key(suite.story_jira_key)  # el nombre del archivo sale de la clave
    return {
        f"estrategia-{key}.md": suite.strategy_md,
        f"matriz-{key}.md": suite.coverage_md(),
    }


def case_labels(case: TestCase) -> list[str]:
    """`caso-prueba`, los CA y RN cubiertos y `tipo-<tipo>` (§6.2), sin repetir."""
    labels = [CASE_LABEL, *case.criterion_ids, *case.rule_ids, f"tipo-{case.type.value}"]
    return list(dict.fromkeys(labels))


def case_to_adf(case: TestCase, story: str) -> Node:
    """Descripción de la subtarea CP (§6.2): tipo, trazabilidad, precondiciones, pasos y Gherkin."""
    content: list[Node] = [
        paragraph(
            [
                *text("Tipo: ", strong=True),
                *text(case.type.value),
                *text(" · Prioridad: ", strong=True),
                *text(case.priority.value),
            ]
        ),
        paragraph(
            [
                *text("HU: ", strong=True),
                *text(story),
                *text(" · Cubre: ", strong=True),
                *text(", ".join([*case.criterion_ids, *case.rule_ids])),
            ]
        ),
    ]
    preconditions = [p.strip() for p in case.preconditions if p.strip()]
    if preconditions:
        content += [heading("Precondiciones", 2), bullet_list([text(p) for p in preconditions])]
    content.append(heading("Pasos", 2))
    content.append(
        table(
            ["#", "Acción", "Datos", "Resultado esperado"],
            [
                [str(i), step.action, step.data or "—", step.expected]
                for i, step in enumerate(case.steps, start=1)
            ],
        )
    )
    if case.gherkin and case.gherkin.strip():
        content += [heading("Escenario Gherkin", 2), code_block(case.gherkin.strip(), "gherkin")]
    return doc(content)


def _checked_key(key: str) -> str:
    if not JIRA_KEY_RE.fullmatch(key):
        raise PublishError(f"«{key[:_MAX_KEY_IN_MESSAGE]}» no es una clave de Jira válida.")
    return key
