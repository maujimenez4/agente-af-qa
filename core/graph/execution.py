"""Registrar la ejecución de las pruebas (T-47 · RF-28, R-01 opción A; UI.md §6.6).

Un grafo propio y pequeño, separado del de HU y suites:

    load_cases → review ⟲ (guardar borrador) → publish → END
                       └→ END (descartar)

- `load_cases` lee de Jira las subtareas CP de la HU (`TestManagement.list_cases`).
- `review` pausa con el **recibo**: una operación por caso (resultado y evidencia), y una huella del
  registro exacto. La persona guarda borradores (`save`), aprueba con la huella (`approve`) o
  descarta (`discard`). El resultado lo elige la persona, nunca la IA.
- `publish` es el **único nodo que escribe en Jira** (principio 1): solo con la decisión `approve` y
  una aprobación vigente guardada en el servidor (`state_store`) para esa misma huella. Cada caso es
  una escritura independiente; los que fallan quedan en `failed` (publicación parcial, RNF-13).
"""

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from adapters.errors import AgentError, ExternalServiceError, NotFoundError, PublishError
from core.audit import AuditEntry
from core.container import Container
from core.conversations import NOT_YOURS, THREAD_ID
from core.logging import get_logger
from core.projects import normalize_issue_key, project_of
from core.qa import validation as suite_validation
from schemas.test_case import MAX_EVIDENCE_CHARS, ExecutionStatus

log = get_logger("core.graph.execution")

KIND = "execution"
MAX_ENVIRONMENT_CHARS = 100
STATUS_TEXT = {
    ExecutionStatus.PASSED: "Pasó",
    ExecutionStatus.FAILED: "Falló",
    ExecutionStatus.BLOCKED: "Bloqueado",
    ExecutionStatus.NOT_RUN: "Sin ejecutar",
}
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# En la evidencia (varias líneas) se conservan el salto de línea y el tabulador.
_EVIDENCE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
# PA-178: formas habituales de secretos que no deben llegar a Jira como evidencia.
_EVIDENCE_SECRET = re.compile(
    r"(?i)\bauthorization\s*:"
    r"|\bbearer\s+[\w.~+/-]{12,}"
    r"|(?<![\w-])eyJ[\w-]{8,}\.[\w-]{8,}\."  # solo al inicio de un token: lineal
    r"|\b(?:sk|gsk|ghp|xox[bp])[-_][\w-]{16,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\b[a-z][\w+.-]{0,30}://[^\s:/@]{1,200}:[^\s@]{1,200}@"  # acotado: sin coste
    # cuadrático con evidencia no fiable (revisión de seguridad)
    r"|\b(?:api[_ -]?key|token|password|contraseña|secret)\s*[:=]\s*\S{6,}"
)
NO_CASES = "La HU {key} no tiene casos de prueba publicados en Jira: publica antes su suite."
MISMATCH = "La aprobación no corresponde al registro revisado; vuelve a revisarlo."
ExecutionDecision = Literal["save", "approve", "discard"]


class CaseRow(TypedDict):
    key: str
    summary: str
    status: str  # estado de la subtarea en Jira


class ResultRow(TypedDict):
    case_key: str
    status: str  # `ExecutionStatus`
    evidence_md: str


class ExecutionState(TypedDict):
    kind: Literal["execution"]
    user: str
    story_key: str
    project: str
    environment: str
    cases: list[CaseRow]
    results: list[ResultRow]
    decision: ExecutionDecision | None
    review_error: str | None
    recorded: list[str]
    failed: list[str]
    errors: list[str]
    approved_at: NotRequired[str | None]
    simulated: NotRequired[bool]  # T-25: en `simulation` no se escribe nada


class ExecutionRejectedError(ValueError):
    """Respuesta de la persona que no se puede aplicar; la revisión sigue con el motivo."""


def initial_execution_state(user: str, story_key: str) -> ExecutionState:
    key = normalize_issue_key(story_key)
    return ExecutionState(
        kind=KIND,
        user=user,
        story_key=key,
        project=project_of(key),
        environment="",
        cases=[],
        results=[],
        decision=None,
        review_error=None,
        recorded=[],
        failed=[],
        errors=[],
        approved_at=None,
        simulated=False,
    )


def _thread(config: RunnableConfig | None, state: ExecutionState) -> str:
    """`thread_id` de la config; la persona que actúa tiene que ser la dueña (como en T-52)."""
    configurable = (config or {}).get("configurable") or {}
    thread_id = str(configurable.get("thread_id") or "")
    if not THREAD_ID.fullmatch(thread_id) or configurable.get("user") != state["user"]:
        raise NotFoundError(NOT_YOURS, service="ejecuciones")
    return thread_id


def execution_fingerprint(state: ExecutionState, thread_id: str) -> str:
    """Huella de lo que se aprueba: HU, persona, conversación, entorno y cada resultado."""
    payload = {
        "story": state["story_key"],
        "project": state["project"],
        "user": state["user"],
        "thread": thread_id,
        "environment": state["environment"],
        "results": [dict(r) for r in state["results"]],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def execution_plan(state: ExecutionState) -> list[dict[str, str]]:
    """Recibo (RF-31): una operación por caso, sin el texto de la evidencia."""
    return [
        {
            "op": "record_execution",
            "key": r["case_key"],
            "status": r["status"],
            "label": STATUS_TEXT[ExecutionStatus(r["status"])],
            "evidence": "sí" if r["evidence_md"].strip() else "no",
        }
        for r in state["results"]
    ]


def validate_results(raw: object, cases: list[CaseRow]) -> list[ResultRow]:
    """Resultados de la persona, limpios; `ExecutionRejectedError` con el motivo si no valen."""
    if not isinstance(raw, list):
        raise ExecutionRejectedError("Los resultados deben ser una lista, uno por caso.")
    known = {c["key"] for c in cases}
    seen: set[str] = set()
    rows: list[ResultRow] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ExecutionRejectedError(
                "Cada resultado necesita el caso, el estado y la evidencia."
            )
        key = str(item.get("case_key") or "").strip().upper()
        if key not in known:
            raise ExecutionRejectedError(f"{key[:20] or 'El caso'} no es un caso de esta HU.")
        if key in seen:
            raise ExecutionRejectedError(f"El caso {key} aparece dos veces.")
        seen.add(key)
        try:
            status = ExecutionStatus(str(item.get("status") or ""))
        except ValueError:
            raise ExecutionRejectedError(f"El resultado de {key} no es válido.") from None
        evidence = _EVIDENCE_CONTROL.sub("", str(item.get("evidence_md") or "")).strip()
        if status is ExecutionStatus.FAILED and not evidence:
            raise ExecutionRejectedError(f"Un caso fallido necesita evidencia ({key}).")
        if len(evidence) > MAX_EVIDENCE_CHARS:
            raise ExecutionRejectedError(
                f"La evidencia de {key} supera los {MAX_EVIDENCE_CHARS} caracteres."
            )
        _reject_sensitive_evidence(key, evidence)
        rows.append(ResultRow(case_key=key, status=status.value, evidence_md=evidence))
    order = {c["key"]: i for i, c in enumerate(cases)}
    return sorted(rows, key=lambda r: order[r["case_key"]])


def _reject_sensitive_evidence(key: str, evidence: str) -> None:
    """PA-178 (RF-25, CLAUDE.md principios 2 y 3): como en la suite, la evidencia que irá a
    Jira no puede parecer un dato personal ni un secreto. El valor nunca se repite."""
    if _EVIDENCE_SECRET.search(evidence):
        raise ExecutionRejectedError(
            f"La evidencia de {key} parece contener una credencial o un token; quítala antes "
            "de registrarla."
        )
    if kind := _personal_data_kind(evidence):
        raise ExecutionRejectedError(
            f"La evidencia de {key} parece contener un dato personal ({kind}); usa datos ficticios."
        )


_EMAIL_BEFORE = 64  # parte local de un email realista
_EMAIL_AFTER = 255  # dominio


def _personal_data_kind(text: str) -> str | None:
    """Mismos patrones y mismo orden que la validación de la suite, en tiempo lineal.

    La evidencia la escribe la persona (hasta `MAX_EVIDENCE_CHARS` por caso) y el patrón de
    email de la suite tiene coste cuadrático con tramos largos sin `@` (PA-142): aquí solo se
    busca en tramos acotados alrededor de cada `@`. DNI, NIE, IBAN y teléfono son lineales y se
    buscan en el texto completo, así que la cobertura es la misma que en la suite.
    """
    for span in _around_at(text):
        for match in suite_validation._EMAIL.finditer(span):
            if not suite_validation._FICTITIOUS_DOMAIN.search(match.group(1)):
                return "email"
    if suite_validation._DNI.search(text) or suite_validation._NIE.search(text):
        return "documento de identidad"
    if suite_validation._IBAN.search(text):
        return "IBAN"
    if suite_validation._PHONE.search(text):
        return "teléfono"
    return None


def _around_at(text: str) -> Iterator[str]:
    """Tramos alrededor de cada `@`, unidos si se solapan (sin tramos largos sin `@`)."""
    begin = end = -1
    for match in re.finditer("@", text):
        lo, hi = max(0, match.start() - _EMAIL_BEFORE), match.end() + _EMAIL_AFTER
        if lo > end:
            if end >= 0:
                yield text[begin:end]
            begin = lo
        end = max(end, hi)
    if end >= 0:
        yield text[begin:end]


def _case_error(case_key: str, exc: Exception) -> str:
    """Mensaje del fallo de un caso: el de los errores del dominio (escritos para la persona,
    en español) o uno genérico; nunca el texto de otras excepciones."""
    if isinstance(exc, AgentError) and str(exc):
        return str(exc)
    return f"No se pudo registrar el resultado en {case_key}."


def evidence_for_jira(environment: str, evidence: str) -> str:
    """Comentario que llega a Jira: el entorno, si lo hay, delante de la evidencia."""
    if not environment:
        return evidence
    return f"Entorno: {environment}\n\n{evidence}".strip()


def clean_environment(raw: object) -> str:
    text = _CONTROL.sub(" ", str(raw or "")).strip()
    if len(text) > MAX_ENVIRONMENT_CHARS:
        raise ExecutionRejectedError(
            f"El entorno admite como mucho {MAX_ENVIRONMENT_CHARS} caracteres."
        )
    return text


class ExecutionNodes:
    def __init__(self, container: Container) -> None:
        self.c = container

    # --- 1 · load_cases ---------------------------------------------------------------------

    def load_cases(
        self, state: ExecutionState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        _thread(config, state)
        key = state["story_key"]
        cases = [
            CaseRow(key=c.key, summary=c.summary, status=c.status)
            for c in self.c.test_management.list_cases(key)
        ]
        if not cases:
            raise PublishError(NO_CASES.format(key=key))
        return {"cases": cases}

    # --- 2 · review (recibo con huella) -------------------------------------------------------

    def review(self, state: ExecutionState, config: RunnableConfig | None = None) -> dict[str, Any]:
        thread_id = _thread(config, state)
        fingerprint = execution_fingerprint(state, thread_id)
        payload = {
            "kind": KIND,
            "story_key": state["story_key"],
            "cases": [dict(c) for c in state["cases"]],
            "results": [dict(r) for r in state["results"]],
            "environment": state["environment"],
            "plan": execution_plan(state),
            "fingerprint": fingerprint,
            "error": state.get("review_error"),
        }
        answer = interrupt(payload)
        try:
            return self._apply(state, thread_id, fingerprint, answer)
        except ExecutionRejectedError as exc:
            return {"decision": "save", "review_error": str(exc)}

    def _apply(
        self, state: ExecutionState, thread_id: str, fingerprint: str, answer: object
    ) -> dict[str, Any]:
        if not isinstance(answer, dict):
            answer = {}
        decision = answer.get("decision")
        if decision == "save":
            results = validate_results(answer.get("results"), state["cases"])
            environment = clean_environment(answer.get("environment"))
            for row in results:  # lo que llegará a Jira, con el entorno delante
                if len(evidence_for_jira(environment, row["evidence_md"])) > MAX_EVIDENCE_CHARS:
                    raise ExecutionRejectedError(
                        f"La evidencia de {row['case_key']} con el entorno supera los "
                        f"{MAX_EVIDENCE_CHARS} caracteres."
                    )
            return {
                "decision": "save",
                "results": results,
                "environment": environment,
                "review_error": None,
            }
        if decision == "discard":
            self._audit("discard", state, detail={"cases": len(state["results"])})
            return {"decision": "discard", "review_error": None}
        if decision == "approve":
            if not state["results"]:
                raise ExecutionRejectedError("Elige el resultado de al menos un caso.")
            # La huella se recalcula del estado: se aprueba exactamente lo que se mostró.
            if answer.get("fingerprint") != fingerprint:
                raise ExecutionRejectedError(MISMATCH)
            at = datetime.now(UTC).isoformat()
            self._save(
                thread_id,
                {"approved": fingerprint, "approved_by": state["user"], "at": at, "used": False},
            )
            self._audit("approve", state, detail={"cases": len(state["results"])})
            return {"decision": "approve", "review_error": None, "approved_at": at}
        raise ExecutionRejectedError("Decisión no válida: usa guardar, aprobar o descartar.")

    # --- 3 · publish: ÚNICO nodo de este grafo que escribe en Jira ----------------------------

    def publish(
        self, state: ExecutionState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        thread_id = _thread(config, state)
        if state["decision"] != "approve":
            raise PublishError("Falta la confirmación explícita del usuario para registrar.")
        # El estado del grafo puede alterarse: la aprobación vigente sale del servidor.
        stored = self._load(thread_id)
        fingerprint = execution_fingerprint(state, thread_id)
        if stored.get("approved") != fingerprint or stored.get("used"):
            raise PublishError("No consta una aprobación humana vigente para este registro exacto.")
        if self.c.publish_mode != "live":
            # T-25: modo simulación. Nada se escribe en Jira; el recibo queda en la auditoría.
            self._save(thread_id, stored | {"used": True, "simulated": True})
            self._audit(
                "publish",
                state,
                detail={"simulated": True, "plan": execution_plan(state)},
            )
            log.info(
                "registro de ejecución simulado",
                user=state["user"],
                action="record_execution",
                operations=len(state["results"]),
            )
            return {"simulated": True}
        # Un solo uso, marcado ANTES de escribir: aunque algo corte el bucle a medias, esta
        # aprobación no vuelve a servir y nada se repite.
        self._save(thread_id, stored | {"used": True})
        recorded: list[str] = []
        failed: list[str] = []
        errors: list[str] = []
        try:
            for row in state["results"]:
                evidence = evidence_for_jira(state["environment"], row["evidence_md"])
                try:
                    self.c.test_management.record_execution(
                        row["case_key"], ExecutionStatus(row["status"]), evidence
                    )
                except Exception as exc:  # cada caso es independiente (RNF-13)
                    failed.append(row["case_key"])
                    errors.append(_case_error(row["case_key"], exc))
                else:
                    recorded.append(row["case_key"])
        finally:
            # PA-179: primero la auditoría de lo ya escrito en Jira (RF-35, RNF-13), como el
            # grafo de HU; si después falla el guardado, lo escrito ya consta.
            audit_failed = False
            try:
                self._audit(
                    "publish",
                    state,
                    jira_keys=recorded,
                    detail={"execution": True, "recorded": len(recorded), "failed": failed},
                )
            except AgentError:
                audit_failed = True  # se guarda igualmente lo escrito y se avisa (abajo)
            try:
                # `recorded` deja constancia en el servidor de lo ya escrito (RNF-13).
                self._save(
                    thread_id, stored | {"used": True, "recorded": recorded, "failed": failed}
                )
            except AgentError:
                # PA-179: la persona debe saber que Jira ya se escribió y no repetir el registro.
                raise ExternalServiceError(
                    f"Se registraron {len(recorded)} resultados en Jira, pero no se pudo guardar "
                    "el estado del registro. No lo repitas: revisa la auditoría y Jira.",
                    service="artifact_state",
                ) from None
            if audit_failed:
                raise ExternalServiceError(
                    f"Se registraron {len(recorded)} resultados en Jira, pero no se pudo "
                    "auditar el registro. No lo repitas: revisa Jira.",
                    service="audit",
                ) from None
        log.info(
            "ejecución registrada",
            user=state["user"],
            action="record_execution",
            recorded=len(recorded),
            failed=len(failed),
        )
        return {"recorded": recorded, "failed": failed, "errors": errors}

    # --- utilidades ---------------------------------------------------------------------------

    def _load(self, thread_id: str) -> dict[str, Any]:
        return dict((self.c.state_store.load(thread_id) or {}).get("execution") or {})

    def _save(self, thread_id: str, approval: dict[str, Any]) -> None:
        current = self.c.state_store.load(thread_id) or {}
        current["execution"] = approval
        self.c.state_store.save(thread_id, current)

    def _audit(
        self,
        action: Literal["approve", "publish", "discard"],
        state: ExecutionState,
        *,
        jira_keys: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        # Sin la evidencia: la auditoría guarda claves y recuentos, nunca el texto.
        self.c.audit.record(
            AuditEntry(
                artifact_id=None,
                action=action,
                user=state["user"],
                jira_keys=jira_keys or [],
                detail={"execution": True, "story": state["story_key"]} | (detail or {}),
            )
        )


def _after_review(state: ExecutionState) -> str:
    return {"save": "review", "approve": "publish"}.get(state["decision"] or "", END)


def build_execution_graph(
    container: Container, checkpointer: BaseCheckpointSaver | None = None
) -> CompiledStateGraph:
    """Grafo del registro de la ejecución; comparte el checkpointer de la app (T-52)."""
    from core.graph.builder import memory_checkpointer

    nodes = ExecutionNodes(container)
    graph = StateGraph(ExecutionState)
    graph.add_node("load_cases", nodes.load_cases)
    graph.add_node("review", nodes.review)
    graph.add_node("publish", nodes.publish)
    graph.add_edge(START, "load_cases")
    graph.add_edge("load_cases", "review")
    graph.add_conditional_edges(
        "review", _after_review, {"review": "review", "publish": "publish", END: END}
    )
    graph.add_edge("publish", END)
    return graph.compile(checkpointer=checkpointer or memory_checkpointer())
