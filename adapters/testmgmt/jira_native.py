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
- **Ejecución (T-47, RF-28):** `record_execution` registra el resultado de un CP en su subtarea
  (transición, etiqueta `ejecucion-<estado>` y comentario con la evidencia).
- Escrituras de un solo intento (`adapters/jira/http.py`); solo las llama el nodo `publish`.
"""

import hashlib
import re
import time
from collections.abc import Callable, Mapping, Sequence
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
from adapters.jira.adf import (
    Node,
    adf_to_text,
    bullet_list,
    code_block,
    doc,
    heading,
    markdown_to_adf,
    paragraph,
    table,
    text,
)
from adapters.jira.http import SERVICE, JiraHttp
from adapters.jira.jql import CASE_LABEL, cases_jql
from adapters.jira.story_template import prefixed_summary
from adapters.jira.tracker import (
    JIRA_KEY_RE,
    MAPPING_ERRORS,
    SEARCH_FIELDS,
    list_field,
    to_issue_summary,
    unexpected_format,
)

# PA-206: el resultado y el límite de la evidencia son del dominio (`schemas/`); se
# reexportan aquí para quien los importaba de este módulo.
from schemas.test_case import MAX_EVIDENCE_CHARS, ExecutionStatus, TestCase, TestSuite

log = structlog.get_logger(__name__)

PAGE_SIZE = 100
MAX_CASES = 500  # tope de subtareas CP por HU en la búsqueda
_CASE_PREFIX = re.compile(r"^\[(CP-\d+)\]")
_MAX_KEY_IN_MESSAGE = 50
_MAX_SUBTASK_TYPE = 60
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")  # incluye `\r` y `\n`
COMMENTS_TO_CHECK = 20  # PA-208: comentarios recientes en los que se busca el último registro
FINGERPRINT_CHARS = 12
_RESULT_HEADING = "Resultado de la ejecución:"
_FINGERPRINT_LABEL = "Huella:"
_FINGERPRINT_LINE = re.compile(r"Huella: ([0-9a-f]{12})")  # solo en la última línea
_NUMERIC_ID = re.compile(r"[0-9]{1,18}")  # ASCII: `isdigit` admite «²» o «١»


STATUS_TEXT = {
    ExecutionStatus.PASSED: "Pasó",
    ExecutionStatus.FAILED: "Falló",
    ExecutionStatus.BLOCKED: "Bloqueado",
    ExecutionStatus.NOT_RUN: "Sin ejecutar",
}
_EXECUTION_PREFIX = "ejecucion-"
EXECUTION_LABELS = {status: f"{_EXECUTION_PREFIX}{status.value}" for status in ExecutionStatus}
# Nombres de la transición o del estado de destino que se buscan para cada resultado, sin
# distinguir mayúsculas. Configurable en el constructor (`execution_transitions`, PA-207). Si el
# flujo de trabajo no tiene ninguno (p. ej. no hay estado «Falló»), el estado no cambia y el
# resultado queda en la etiqueta `ejecucion-<estado>` y en el comentario.
DEFAULT_EXECUTION_TRANSITIONS: dict[ExecutionStatus, tuple[str, ...]] = {
    ExecutionStatus.PASSED: ("Pasó", "Passed", "Done", "Hecho", "Finalizada", "Listo"),
    ExecutionStatus.FAILED: ("Falló", "Failed"),
    ExecutionStatus.BLOCKED: ("Bloqueado", "Blocked"),
    ExecutionStatus.NOT_RUN: ("Sin ejecutar", "To Do", "Por hacer", "Tareas por hacer"),
}


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
        execution_transitions: Mapping[ExecutionStatus, Sequence[str]] | None = None,
    ) -> None:
        self._transitions = _transition_names(execution_transitions)
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
            issues = list_field(page, "issues")  # PA-189
            try:
                cases += [to_issue_summary(issue) for issue in issues]
            except MAPPING_ERRORS:
                raise unexpected_format() from None
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
        handled: set[str] = set()  # PA-190: un CP repetido en la suite se trata una sola vez
        for case in suite.cases:
            if case.internal_id in handled:
                continue
            handled.add(case.internal_id)
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

    def record_execution(
        self, case_key: str, status: ExecutionStatus | str, evidence_md: str
    ) -> None:
        """Registra el resultado de un CP en su subtarea (T-47, RF-28, R-01 opción A).

        Transición al estado configurado (si el flujo de trabajo la tiene), etiqueta
        `ejecucion-<estado>` y comentario con el resultado y la evidencia, por este orden: el
        comentario, lo único que no es idempotente por sí mismo, va el último.

        PA-208: el comentario lleva una huella del resultado y la evidencia; si el comentario de
        ejecución más reciente ya tiene la misma huella, no se vuelve a comentar.
        """
        started = time.perf_counter()
        key = _checked_key(case_key)
        try:
            status = ExecutionStatus(status)
        except ValueError:
            shown = _CONTROL.sub("", str(status))[:30]
            raise PublishError(f"«{shown}» no es un resultado de ejecución.") from None
        evidence = evidence_md.strip()
        if status is ExecutionStatus.FAILED and not evidence:
            raise PublishError("Un caso fallido necesita evidencia.")
        if len(evidence) > MAX_EVIDENCE_CHARS:
            raise PublishError(f"La evidencia supera los {MAX_EVIDENCE_CHARS} caracteres.")

        fields = _fields(
            self._http.get(
                f"/rest/api/3/issue/{key}", params={"fields": "labels,status,issuetype"}, key=key
            )
        )
        labels = [str(label) for label in list_field(fields, "labels")]
        issue_type = fields.get("issuetype")
        # Nunca se escribe en una incidencia que no sea una subtarea CP.
        if not isinstance(issue_type, dict) or issue_type.get("subtask") is not True:
            raise PublishError(f"{key} no es una subtarea: solo se registra la ejecución de un CP.")
        if CASE_LABEL not in labels:
            raise PublishError(
                f"{key} no es un caso de prueba (le falta la etiqueta «{CASE_LABEL}»)."
            )

        fingerprint = execution_fingerprint(status, evidence)
        repeated = self._latest_execution_fingerprint(key) == fingerprint  # PA-208, lectura
        current = _name_of(fields.get("status"))
        transitioned = self._transition(key, status, current)  # si falla, no se ha escrito nada
        label = EXECUTION_LABELS[status]
        changes = [{"remove": old} for old in labels if _is_execution_label(old) and old != label]
        try:
            self._http.send(
                "PUT",
                f"/rest/api/3/issue/{key}",
                {"update": {"labels": [*changes, {"add": label}]}},
                PublishError,
                key,
            )
            if not repeated:
                self._http.send(
                    "POST",
                    f"/rest/api/3/issue/{key}/comment",
                    {"body": execution_comment(status, evidence)},
                    PublishError,
                    key,
                )
        except AgentError as exc:
            state = "con el estado ya cambiado" if transitioned else "sin cambiar el estado"
            raise PublishError(
                f"Registro incompleto de la ejecución en {key} ({state}): {exc}"
            ) from None
        log.info(
            "ejecución registrada en Jira",
            action="record_execution",
            jira_key=key,
            status=status.value,
            transitioned=transitioned,
            commented=not repeated,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )

    def _latest_execution_fingerprint(self, key: str) -> str | None:
        """Huella del comentario de ejecución más reciente (entre los últimos), o `None`."""
        params = {"orderBy": "-created", "maxResults": str(COMMENTS_TO_CHECK)}
        data = self._http.get(f"/rest/api/3/issue/{key}/comment", params=params, key=key)
        for comment in data.get("comments") or []:
            body = comment.get("body") if isinstance(comment, dict) else None
            content = adf_to_text(body) if isinstance(body, dict) else ""
            if content.startswith(_RESULT_HEADING):
                match = _FINGERPRINT_LINE.fullmatch(content.splitlines()[-1].strip())
                return match.group(1) if match else ""
        return None

    def _transition(self, key: str, status: ExecutionStatus, current: str) -> bool:
        """Aplica la transición configurada; `False` si ya está en ese estado o no existe."""
        names = self._transitions[status]
        if current.casefold() in names:
            return False
        data = self._http.get(f"/rest/api/3/issue/{key}/transitions", key=key)
        for transition in data.get("transitions") or []:
            if not isinstance(transition, dict):
                continue
            target = _name_of(transition.get("to"))
            if {str(transition.get("name") or "").casefold(), target.casefold()} & names:
                transition_id = str(transition.get("id") or "")
                if not _NUMERIC_ID.fullmatch(transition_id):
                    continue
                body = {"transition": {"id": transition_id}}
                self._http.send(
                    "POST",
                    f"/rest/api/3/issue/{key}/transitions",
                    body,
                    PublishError,
                    key,
                    bad_request=(  # PA-195: mensaje propio, no el de creación
                        f"Jira ha rechazado la transición de {key} (HTTP 400): puede que pida "
                        "campos obligatorios o que el flujo de trabajo no la permita."
                    ),
                )
                return True
        # Sin transición en el flujo (p. ej. no hay estado «Falló»): manda la etiqueta.
        log.info(
            "sin transición para el resultado",
            action="record_execution",
            jira_key=key,
            status=status.value,
        )
        return False

    def _attachment_names(self, story: str) -> set[str]:
        data = self._http.get(
            f"/rest/api/3/issue/{story}", params={"fields": "attachment"}, key=story
        )
        attachments = list_field(
            _fields(data), "attachment"
        )  # PA-188: forma inesperada → AgentError
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


def execution_comment(status: ExecutionStatus, evidence: str) -> Node:
    """Comentario del registro: resultado (texto literal) y evidencia (Markdown → ADF)."""
    content: list[Node] = [
        paragraph([*text(f"{_RESULT_HEADING} ", strong=True), *text(STATUS_TEXT[status])])
    ]
    if evidence:
        content += [
            paragraph(text("Evidencia:", strong=True)),
            *markdown_to_adf(evidence)["content"],
        ]
    else:
        content.append(paragraph(text("Sin evidencia.")))
    fingerprint = execution_fingerprint(status, evidence)
    content.append(paragraph(text(f"{_FINGERPRINT_LABEL} {fingerprint}")))
    return doc(content)


def execution_fingerprint(status: ExecutionStatus, evidence: str) -> str:
    """Huella corta del resultado y la evidencia (PA-208); no es un secreto ni identifica datos."""
    normalized = " ".join(evidence.split())  # los espacios y saltos de línea no cuentan
    digest = hashlib.sha256(f"{status.value}|{normalized}".encode()).hexdigest()
    return digest[:FINGERPRINT_CHARS]


def _name_of(field: Any) -> str:
    """`name` de un objeto de Jira; cadena vacía si la respuesta no tiene la forma esperada."""
    return str(field.get("name") or "") if isinstance(field, dict) else ""


def _is_execution_label(label: str) -> bool:
    return label.startswith(_EXECUTION_PREFIX)


def _transition_names(
    overrides: Mapping[ExecutionStatus, Sequence[str]] | None,
) -> dict[ExecutionStatus, frozenset[str]]:
    """Mapeo resultado → nombres de transición o de estado de destino (sin mayúsculas)."""
    mapping = {**DEFAULT_EXECUTION_TRANSITIONS, **(overrides or {})}
    if any(isinstance(value, str) for value in mapping.values()):
        raise ValueError("Cada resultado necesita una lista de nombres de transición, no un texto.")
    names: dict[ExecutionStatus, frozenset[str]] = {}
    for status in ExecutionStatus:
        cleaned = {n.strip().casefold() for n in mapping[status] if n.strip()}
        if not cleaned or any(len(n) > _MAX_SUBTASK_TYPE or _CONTROL.search(n) for n in cleaned):
            raise ValueError(f"Las transiciones de «{STATUS_TEXT[status]}» no son válidas.")
        names[status] = frozenset(cleaned)
    return names


def _fields(issue: dict[str, Any]) -> dict[str, Any]:
    """`fields` de una incidencia leída; otra forma es un error de Jira (PA-188, PA-189)."""
    fields = issue.get("fields") or {}
    if not isinstance(fields, dict):
        raise unexpected_format()
    return fields


def _checked_key(key: str) -> str:
    if not JIRA_KEY_RE.fullmatch(key):
        raise PublishError(f"«{key[:_MAX_KEY_IN_MESSAGE]}» no es una clave de Jira válida.")
    return key
