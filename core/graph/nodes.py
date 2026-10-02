"""Nodos del grafo (SPEC-00 §5.2). Solo `publish` escribe en Jira, y solo artefactos APPROVED.

Esqueleto del día 1: la lógica de contexto (T-18), los prompts (T-20/T-26), la auditoría
(T-25) y la memoria real (T-33) se completan en sus tareas.
"""

import time
from dataclasses import replace
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from pydantic import BaseModel, ValidationError

from adapters.base import Chunk
from adapters.errors import ExternalServiceError, NotFoundError, PublishError
from core.approvals import Approval, PublishTarget, review_fingerprint
from core.audit import AuditAction, AuditEntry
from core.container import Container
from core.context.service import ContextService, build_context_service
from core.conversations import NOT_YOURS, THREAD_ID, ConversationStatus, new_summary
from core.functional.context import StoryContext
from core.functional.writer import StoryDraft, StoryWriter
from core.graph.state import AgentState, Decision
from core.handoff import HandoffStore, load_taken_handoff
from core.impact.analysis import ImpactAnalyzer
from core.impact.diff import diff_stories
from core.logging import get_logger
from core.projects import ISSUE_KEY, PROJECT_KEY, project_of
from core.qa.writer import SuiteDraft, TestWriter
from core.state_machine import transition
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from schemas.impact import ImpactAnalysis, ImpactItem
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

DECISIONS: tuple[Decision, ...] = ("iterate", "edit", "approve", "discard")
# Respuestas rechazadas que una misma pausa de revisión admite antes de fallar (T-51).
MAX_REVIEW_REJECTIONS = 20
# Campos que la edición manual no puede cambiar: atan el artefacto a su origen (trazabilidad).
FIXED_ON_EDIT: dict[ArtifactType, tuple[str, ...]] = {
    ArtifactType.USER_STORY: ("jira_key", "internal_id"),
    ArtifactType.TEST_SUITE: ("story_jira_key",),
}
_CONTENT_MODEL: dict[ArtifactType, type[BaseModel]] = {
    ArtifactType.USER_STORY: UserStory,
    ArtifactType.TEST_SUITE: TestSuite,
}
LINK_TYPE_IMPACT = "relates to"  # D-09
# Clave de Jira: evita rutas o JQL inyectadas a través del origen (p. ej. "../x").
JIRA_KEY = ISSUE_KEY

log = get_logger("core.graph")


class ReviewRejectedError(ValueError):
    """La respuesta de la persona no es válida; se le muestra el motivo y puede corregirla.

    Solo se lanza al validar la propia respuesta (decisión, huella, contenido editado), antes
    de cualquier efecto: al repetirse en la reanudación vuelve a fallar igual.
    """


# T-54: en simulación la HU encadenada no tiene clave; sus casos no se pueden publicar.
UNPUBLISHED_STORY = (
    "No se pueden publicar los casos: la HU de origen no está publicada en Jira (se aprobó en "
    "simulación). Publica antes la HU y vuelve a pasarla a QA."
)


class GraphNodes:
    def __init__(self, container: Container, handoffs: HandoffStore | None = None) -> None:
        self.c = container
        self.handoffs = handoffs  # T-54: entregas a QA (sin él, la QA encadenada falla cerrada)

    # --- 1 · load_origin -------------------------------------------------------------------

    def load_origin(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        validate_origin(state)
        origin = state["origin"]
        key = origin.get("key")
        thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
        update: dict[str, Any]
        if (story := self._chained_story(state, config)) is not None:
            # T-54: la HU aprobada sale del servidor, sin releer Jira ni volver a estructurarla.
            update = {"jira_context": [], "source_story": story}
        else:
            update = {"jira_context": [self.c.issue_tracker.get_issue(key)] if key else []}
        # T-52: la conversación entra en la lista de su dueño (solo flujo y clave, sin texto).
        if thread_id:
            if not THREAD_ID.fullmatch(str(thread_id)):
                raise NotFoundError(NOT_YOURS, service="conversaciones")
            _check_actor(state, config, self.c.require_actor)
            existing = self.c.conversations.get(str(thread_id))
            if existing is not None and existing.username != state["user"]:
                raise NotFoundError(NOT_YOURS, service="conversaciones")
            self.c.conversations.start(
                new_summary(
                    thread_id=str(thread_id),
                    username=state["user"],
                    project=origin.get("project") or "",
                    mode=state["mode"],
                    origin_kind=origin["kind"],
                    origin_key=key,
                )
            )
        return update

    # --- 2–3 · retrieve_context ------------------------------------------------------------

    def retrieve_context(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        """Jira + RAG ajustados al presupuesto de tokens (T-18)."""
        started = time.perf_counter()
        origin_issue = state["jira_context"][0] if state["jira_context"] else None
        origin: dict[str, Any] = dict(state["origin"])
        if (story := self._chained_story(state, config)) is not None:
            # T-54: sin incidencia de Jira, el RAG se consulta con el texto de la HU encadenada.
            origin["text"] = f"{story.title}. {story.description}"
        gathered = self._context_service(state).gather(
            origin, origin_issue, excluded=state.get("excluded_sources") or []
        )
        log.info(
            "contexto reunido",
            user=state["user"],
            action="retrieve_context",
            jira=len(gathered.jira),
            rag=len(gathered.rag),
            tokens=gathered.budget.used,
            dropped=gathered.budget.dropped_issues + gathered.budget.dropped_chunks,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return {"jira_context": gathered.jira, "rag_context": gathered.rag}

    def _context_service(self, state: AgentState) -> ContextService:
        # El proyecto es el de la conversación (T-50).
        return build_context_service(self.c, state["origin"].get("project"))

    # --- 4 · generate ----------------------------------------------------------------------

    def generate(self, state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        validate_origin(state)  # el estado puede haber cambiado al iterar
        origin = state["origin"]
        previous = state["artifact"]
        artifact_id = previous.id if previous is not None else uuid4()
        impact: ImpactAnalysis | None = None
        prompt_version: str | None = None

        content: UserStory | TestSuite
        try:
            if state["mode"] == "qa":
                suite_draft = self._write_suite(state, str(artifact_id), config)
                content, artifact_type = suite_draft.suite, ArtifactType.TEST_SUITE
                model_used = f"{suite_draft.provider}/{suite_draft.model}"
                prompt_version = suite_draft.prompt_version
            else:
                draft, impact = self._write_story(state, str(artifact_id))
                content, artifact_type = draft.story, ArtifactType.USER_STORY
                model_used = f"{draft.provider}/{draft.model}"
                prompt_version = draft.prompt_version
        except Exception:
            # Sin primera versión no hay artefacto: no queda una versión de partida huérfana
            # (cada reintento usa un id nuevo). Si la limpieza falla, sube el error original.
            if previous is None:
                try:
                    self._forget_baseline(str(artifact_id))
                except Exception:
                    log.warning(
                        "versión de partida sin limpiar",
                        action="forget_baseline",
                        artifact_id=str(artifact_id),
                    )
            raise

        if previous is None:
            artifact = Artifact(
                id=artifact_id,
                type=artifact_type,
                status=ArtifactStatus.DRAFT,
                version=1,
                origin_key=origin.get("key"),
                content=content,
                impact=impact,
                created_by=state["user"],
                model_used=model_used,
                prompt_version=prompt_version,
            )
        else:  # iteración: misma identidad, nueva versión (RF-20)
            artifact = previous.model_copy(
                update={
                    "version": previous.version + 1,
                    "content": content,
                    "impact": impact,
                    "model_used": model_used,
                    "prompt_version": prompt_version,
                }
            )
        artifact = transition(artifact, ArtifactStatus.IN_REVIEW)
        # Solo la versión ofrecida aquí podrá aprobarse en human_review.
        self.c.approvals.offer(artifact, _target(state, config, self.c.require_actor))
        detail: dict[str, Any] = {"prompt_version": artifact.prompt_version}
        if previous is None and (excluded := state.get("excluded_sources")):
            detail["excluded_sources"] = list(excluded)  # solo referencias (T-51)
        if previous is None and (handoff_id := state.get("handoff_id")):
            detail |= self._handoff_trace(handoff_id)  # T-54: HU de origen de la suite
        self._record("create" if previous is None else "iterate", state, artifact, detail=detail)
        log.info(
            "propuesta generada",
            user=state["user"],
            action="create" if previous is None else "iterate",
            artifact_id=str(artifact.id),
            model=model_used,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        self._track(_target(state, config, self.c.require_actor), "in_review", artifact)
        return {"artifact": artifact, "decision": None}

    def _track(
        self,
        target: PublishTarget,
        status: ConversationStatus,
        artifact: Artifact | None = None,
    ) -> None:
        """Actualiza la fila de la conversación en la lista, solo si es del dueño (T-52).

        Es un índice secundario: si falla, no tumba el nodo (se repetiría al reanudar después de
        efectos que no se repiten, como registrar la aprobación o escribir en Jira).
        """
        try:
            self.c.conversations.update(
                target.thread_id,
                username=target.user,
                status=status,
                artifact_id=str(artifact.id) if artifact else None,
                version=artifact.version if artifact else None,
            )
        except ExternalServiceError:
            log.warning(
                "lista de conversaciones sin actualizar",
                user=target.user,
                action="track_conversation",
                artifact_id=str(artifact.id) if artifact else None,
            )

    def _write_story(
        self, state: AgentState, artifact_id: str
    ) -> tuple[StoryDraft, ImpactAnalysis | None]:
        """HU con los prompts de T-20; en una evolución, diff frente a la versión de Jira."""
        origin, previous = state["origin"], state["artifact"]
        writer = StoryWriter(self.c.llm)
        ctx = StoryContext(
            origin_kind=origin["kind"],
            origin_key=origin.get("key"),
            need=origin.get("text") or "",
            jira=list(state["jira_context"]),
            rag=list(state["rag_context"]),
            feedback=list(state["feedback"]),
        )
        current = previous.content if previous and isinstance(previous.content, UserStory) else None
        analyzer = ImpactAnalyzer(self.c.llm)
        jira = list(state["jira_context"])
        if origin["kind"] != "story":
            # HU nueva; al iterar, se evoluciona el borrador anterior con el feedback (RF-20).
            draft = (
                writer.generate(ctx)
                if current is None
                else writer.evolve(replace(ctx, previous=current))
            )
            # §6.1: una HU nueva también puede afectar a las HU relacionadas (sin diff).
            epic = origin.get("key") if origin["kind"] == "epic" else None
            return draft, analyzer.analyze(draft.story, jira, parent_key=epic)

        baseline = self._baseline(writer, ctx, artifact_id)
        draft = writer.evolve(replace(ctx, previous=current or baseline))
        # T-21: diff determinista frente a Jira + HU afectadas y regresión validadas.
        impact = analyzer.analyze(
            draft.story, jira, baseline=baseline, origin_key=origin.get("key")
        )
        return draft, impact

    def _chained_story(self, state: AgentState, config: RunnableConfig | None) -> UserStory | None:
        """HU de la entrega a QA, recargada del almacén en cada uso (T-54).

        Nunca se usa `source_story` del estado: un estado manipulado no inyecta una HU. Sin
        `handoff_id` no hay QA encadenada.
        """
        handoff_id = state.get("handoff_id")
        if handoff_id is None:
            return None
        thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
        if not thread_id or not THREAD_ID.fullmatch(str(thread_id)):
            raise NotFoundError(NOT_YOURS, service="conversaciones")
        _check_actor(state, config, self.c.require_actor)
        handoff = load_taken_handoff(self.handoffs, handoff_id, state["user"], str(thread_id))
        # El destino que se aprobará (proyecto y clave del origen) es el de la entrega, también
        # al iterar: el estado guardado puede alterarse.
        origin = state["origin"]
        if handoff.project_key != origin.get("project") or handoff.story_key != origin.get("key"):
            raise NotFoundError(NOT_YOURS, service="conversaciones")
        return handoff.story

    def _write_suite(
        self, state: AgentState, artifact_id: str, config: RunnableConfig | None = None
    ) -> SuiteDraft:
        """Suite de QA con los prompts de T-26 sobre la HU de Jira estructurada (PA-61).

        La HU se estructura una sola vez por artefacto (versión de partida); al iterar, la suite
        se regenera con todo el feedback acumulado (RF-20).
        """
        origin = state["origin"]
        ctx = StoryContext(
            origin_kind="story",
            origin_key=origin.get("key"),
            need=origin.get("text") or "",
            jira=list(state["jira_context"]),
            rag=list(state["rag_context"]),
            feedback=list(state["feedback"]),
        )
        if (chained := self._chained_story(state, config)) is not None:
            # T-54: la HU aprobada tal cual, sin `structure` (una llamada menos al LLM). Sin clave
            # de origen, esa versión no está en Jira aunque la HU de partida tuviera clave.
            unpublished = not origin.get("key")
            if unpublished:
                chained = chained.model_copy(update={"jira_key": None})
            return TestWriter(self.c.llm).generate(chained, ctx, unpublished=unpublished)
        story = self._baseline(StoryWriter(self.c.llm), ctx, artifact_id)
        return TestWriter(self.c.llm).generate(story, ctx)

    def _handoff_trace(self, handoff_id: str) -> dict[str, Any]:
        """Referencias de la HU de origen para la auditoría (solo ids, nunca contenido)."""
        handoff = self.handoffs.get(handoff_id) if self.handoffs is not None else None
        if handoff is None:
            return {"handoff_id": handoff_id}
        return {
            "handoff_id": handoff_id,
            "source_artifact_id": str(handoff.artifact_id),
            "source_version": handoff.version,
            "source_story_key": handoff.story_key,
        }

    def _baseline(self, writer: StoryWriter, ctx: StoryContext, artifact_id: str) -> UserStory:
        """Versión de partida: la HU de Jira pasada a la plantilla una sola vez (PA-30, PA-37)."""
        state = self.c.state_store.load(artifact_id) or {}
        if saved := state.get("baseline"):
            return UserStory.model_validate(saved)
        origin_issue = [i for i in ctx.jira if i.key == ctx.origin_key][:1]
        origin_only = replace(ctx, jira=origin_issue, rag=[], feedback=[], need="")
        baseline = writer.structure(origin_only).story
        state["baseline"] = baseline.model_dump(mode="json")
        self.c.state_store.save(artifact_id, state)
        return baseline

    def _forget_baseline(self, artifact_id: str) -> None:
        state = self.c.state_store.load(artifact_id)
        if state and state.pop("baseline", None) is not None:
            self.c.state_store.save(artifact_id, state)

    def _record(
        self,
        action: AuditAction,
        state: AgentState,
        artifact: Artifact,
        *,
        jira_keys: list[str] | None = None,
        detail: dict[str, Any] | None = None,
        save_version: bool = True,
    ) -> None:
        """Guarda la versión (T-19) y audita la acción (RF-35). Nunca guarda prompts."""
        if save_version and self.c.versions is not None:
            self.c.versions.save(artifact)
        self.c.audit.record(
            AuditEntry(
                artifact_id=artifact.id,
                action=action,
                user=state["user"],
                jira_keys=jira_keys or [],
                model=artifact.model_used,
                detail={"version": artifact.version, "status": artifact.status.value}
                | (detail or {}),
            )
        )

    # --- 5–6 · human_review ----------------------------------------------------------------

    def human_review(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        artifact = state["artifact"]
        if artifact is None:
            raise ValueError("No hay ningún artefacto que revisar.")
        target = _target(state, config, self.c.require_actor)
        fingerprint = review_fingerprint(artifact, target)
        payload: dict[str, Any] = {
            "artifact": artifact.model_dump(mode="json"),
            "version": artifact.version,
            # Operación que se ejecutará en Jira si se aprueba (se muestra a la persona).
            "target": target.describe(),
            # La UI devuelve esta huella al aprobar: se aprueba exactamente lo que se vio.
            "fingerprint": fingerprint,
            "impact": artifact.impact.model_dump(mode="json") if artifact.impact else None,
            # T-51: operaciones que publish ejecutará en Jira, para el recibo (RF-31).
            "plan": self._plan(target, artifact, _parent_of(state, target.origin_key)),
            "decisions": list(DECISIONS),
            "error": None,
        }
        # T-51: una respuesta rechazada vuelve a pausar con el motivo, sin bloquear el hilo. Al
        # reanudar, LangGraph repite las respuestas anteriores en orden; las rechazadas vuelven a
        # fallar sin efectos (se validan antes de registrar nada) y se llega a la nueva.
        # El registro de aprobaciones (ApprovalError) y cualquier otro fallo no se reintentan:
        # fallan cerrados.
        for _ in range(MAX_REVIEW_REJECTIONS + 1):
            answer = interrupt(payload)
            try:
                return self._apply_review(state, artifact, target, fingerprint, answer)
            except ReviewRejectedError as exc:
                payload = payload | {"error": str(exc)}
                log.info(
                    "revisión rechazada",
                    user=state["user"],
                    action="review_rejected",
                    artifact_id=str(artifact.id),
                )
        raise ValueError(
            "Demasiadas respuestas rechazadas en esta revisión; descarta la conversación y "
            "empieza de nuevo."
        )

    def _apply_review(
        self,
        state: AgentState,
        artifact: Artifact,
        target: PublishTarget,
        fingerprint: str,
        answer: object,
    ) -> dict[str, Any]:
        """Aplica la decisión de la persona; `ValueError` si no es válida (se le muestra)."""
        if not isinstance(answer, dict):
            answer = {}
        decision = answer.get("decision")
        if decision not in DECISIONS:
            raise ReviewRejectedError(
                f"Decisión no válida: {str(decision)[:50]!r}. Usa iterate, edit, approve o discard."
            )
        feedback = (answer.get("feedback") or "").strip()
        if decision == "approve" and answer.get("fingerprint") != fingerprint:
            raise ReviewRejectedError(
                "La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto."
            )
        if decision == "approve" and target.mode == "qa" and not target.origin_key:
            raise ReviewRejectedError(UNPUBLISHED_STORY)  # T-54: nada se registra
        if decision == "edit":
            if answer.get("fingerprint") != fingerprint:
                raise ReviewRejectedError(
                    "La edición no parte de la versión revisada; vuelve a revisar el artefacto."
                )
            edited = self._edit(state, artifact, answer.get("content"), target)
            update_edit: dict[str, Any] = {"artifact": edited, "decision": "edit"}
            if feedback:
                update_edit["feedback"] = [*state["feedback"], feedback]
            log.info(
                "edición manual", user=state["user"], action="edit", artifact_id=str(edited.id)
            )
            self._track(target, "in_review", edited)
            return update_edit

        status = {
            "iterate": ArtifactStatus.DRAFT,
            "approve": ArtifactStatus.APPROVED,
            "discard": ArtifactStatus.DISCARDED,
        }[decision]
        reviewed = transition(artifact, status)
        if decision == "discard":
            self._forget_baseline(str(artifact.id))
            self._record("discard", state, reviewed)
        if decision == "approve":
            # Falla si no es la versión y la operación ofrecidas por generate (ApprovalError).
            self.c.approvals.record(reviewed, target)
            self._record("approve", state, reviewed, detail={"operation": target.describe()})
        update: dict[str, Any] = {"artifact": reviewed, "decision": decision}
        if feedback:
            update["feedback"] = [*state["feedback"], feedback]
        log.info(
            "revisión humana", user=state["user"], action=decision, artifact_id=str(artifact.id)
        )
        if decision in ("approve", "discard"):
            tracked: ConversationStatus = "approved" if decision == "approve" else "discarded"
            self._track(target, tracked, reviewed)
        return update

    def _edit(
        self, state: AgentState, artifact: Artifact, raw: object, target: PublishTarget
    ) -> Artifact:
        """Edición manual (RF-32): versión nueva con su huella, sin llamar al modelo (T-51)."""
        if not isinstance(raw, dict):
            raise ReviewRejectedError("La edición necesita el contenido completo del artefacto.")
        try:
            content = _CONTENT_MODEL[artifact.type].model_validate(raw)
        except ValidationError as exc:
            fields = sorted(
                {".".join(str(p) for p in e["loc"]) or "contenido" for e in exc.errors()}
            )
            raise ReviewRejectedError(
                "El contenido editado no es válido; revisa: " + ", ".join(fields[:8]) + "."
            ) from None
        for name in FIXED_ON_EDIT[artifact.type]:
            if getattr(content, name) != getattr(artifact.content, name):
                raise ReviewRejectedError(f"El campo {name} no se puede cambiar al editar.")
        if content == artifact.content:
            raise ReviewRejectedError("La edición no cambia nada respecto a la versión revisada.")
        impact = artifact.impact
        if isinstance(content, UserStory) and target.origin_kind == "story":
            # El diff frente a Jira se recalcula sin LLM; las HU afectadas se conservan.
            saved = (self.c.state_store.load(str(artifact.id)) or {}).get("baseline")
            if saved:
                diffs = diff_stories(UserStory.model_validate(saved), content)
                base = impact or ImpactAnalysis(diffs=[], affected=[], regression_notes=[])
                impact = base.model_copy(update={"diffs": diffs})
        # Mismo modelo y versión de prompt que la versión base: la auditoría marca la edición.
        edited = transition(artifact, ArtifactStatus.DRAFT).model_copy(
            update={"version": artifact.version + 1, "content": content, "impact": impact}
        )
        edited = transition(edited, ArtifactStatus.IN_REVIEW)
        self.c.approvals.offer(edited, target)
        self._record(
            "iterate",
            state,
            edited,
            detail={"edited": True, "prompt_version": edited.prompt_version},
        )
        return edited

    # --- 7 · publish: ÚNICO nodo que escribe en Jira -------------------------------------------

    def publish(self, state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
        artifact = state["artifact"]
        if artifact is None or artifact.status is not ArtifactStatus.APPROVED:
            status = artifact.status.value if artifact else "sin artefacto"
            raise PublishError(
                f"Solo se publican artefactos aprobados por una persona (estado: {status})."
            )
        if state["decision"] != "approve":
            raise PublishError("Falta la confirmación explícita del usuario para publicar.")
        try:
            validate_origin(state)
        except ValueError as exc:
            raise PublishError(str(exc)) from None
        if state["mode"] == "qa" and not state["origin"].get("key"):
            raise PublishError(UNPUBLISHED_STORY)  # T-54: sin clave, nada se escribe
        # El estado del grafo puede alterarse: la aprobación y la operación salen del registro.
        approval = self.c.approvals.find(artifact, _target(state, config, self.c.require_actor))
        if approval is None:
            raise PublishError(
                "No consta una aprobación humana vigente para esta versión exacta del artefacto."
            )

        epic_key = _parent_of(state, approval.target.origin_key)
        plan = self._plan(approval.target, artifact, epic_key)
        if self.c.publish_mode != "live":
            # T-25: modo simulación. Nada se escribe en Jira; el plan queda en la auditoría y la
            # aprobación sigue vigente para publicar de verdad cuando se active `live`.
            self._record(
                "publish",
                state,
                artifact,
                detail={"simulated": True, "plan": plan},
                save_version=False,
            )
            log.info(
                "publicación simulada",
                user=state["user"],
                action="publish",
                artifact_id=str(artifact.id),
                operations=len(plan),
            )
            self._track(approval.target, "simulated", artifact)
            return {}

        if isinstance(artifact.content, TestSuite):
            result = self.c.test_management.publish_suite(artifact.content)
            errors = [f"No se pudo publicar {case_id}." for case_id in result.failed]
            failed_ids = list(result.failed)
            published = transition(artifact, ArtifactStatus.PUBLISHED) if not errors else artifact
            keys = result.created
        else:
            story, keys, errors = self._publish_story(approval, artifact, epic_key)
            failed_ids = []
            artifact = artifact.model_copy(update={"content": story})
            published = transition(artifact, ArtifactStatus.PUBLISHED)
        if published.status is ArtifactStatus.PUBLISHED:
            self.c.approvals.consume(approval, published)  # un solo uso
            self._forget_baseline(str(artifact.id))
        # Primero la auditoría de lo que ya se escribió en Jira (RF-35, RNF-13).
        self._record(
            "publish",
            state,
            published,
            jira_keys=keys,
            detail={
                "simulated": False,
                "plan": plan,
                "failed": len(errors),
                "failed_ids": failed_ids,
            },
            save_version=False,
        )
        # La versión aprobada ya está guardada; aquí solo cambia el estado (y la clave de Jira).
        if self.c.versions is not None:
            jira_key = getattr(published.content, "jira_key", None)
            self.c.versions.update_status(published.id, published.status.value, jira_key)

        log.info(
            "publicación en Jira",
            user=state["user"],
            action="publish",
            artifact_id=str(artifact.id),
            jira_keys=keys,
            failed=len(errors),
        )
        if published.status is ArtifactStatus.PUBLISHED:
            self._track(approval.target, "published", published)
        return {
            "artifact": published,
            "published_keys": [*state["published_keys"], *keys],
            "errors": [*state["errors"], *errors],
        }

    def _plan(
        self, target: PublishTarget, artifact: Artifact, parent_key: str | None = None
    ) -> list[dict[str, str]]:
        """Operaciones que la publicación haría en Jira para esta operación (RF-31).

        En `human_review` se muestran a la persona; en `publish`, con la operación aprobada.
        """
        _check_project(target)
        project = target.project_key
        if isinstance(artifact.content, TestSuite):
            if target.mode == "qa" and not target.origin_key:
                return []  # T-54: HU sin publicar, no hay operación posible (UNPUBLISHED_STORY)
            if (
                target.mode != "qa"
                or target.origin_kind != "story"
                or artifact.content.story_jira_key != target.origin_key
            ):
                raise PublishError("La operación aprobada no corresponde a estos casos de prueba.")
            return [
                {
                    "op": "publish_suite",
                    "project": project,
                    "story": target.origin_key or "",
                    "cases": str(len(artifact.content.cases)),
                }
            ]
        if not isinstance(artifact.content, UserStory) or target.mode != "functional":
            raise PublishError("La operación aprobada no corresponde a una HU.")
        if target.origin_kind == "story" and target.origin_key:
            source, epic = target.origin_key, parent_key  # PA-38: nunca vincular a su épica
            plan = [{"op": "update_story", "project": project, "key": source}]
        else:
            source = "(HU nueva)"
            epic = target.origin_key if target.origin_kind == "epic" else None
            plan = [{"op": "create_story", "project": project, "epic": epic or ""}]
        plan += [
            {"op": "link", "from": source, "to": item.jira_key, "type": LINK_TYPE_IMPACT}
            for item in _one_per_key(artifact.impact)
            if item.jira_key != epic
        ]
        return plan

    def _publish_story(
        self, approval: Approval, artifact: Artifact, parent_key: str | None = None
    ) -> tuple[UserStory, list[str], list[str]]:
        story = artifact.content
        target, impact = approval.target, artifact.impact
        if not isinstance(story, UserStory) or target.mode != "functional":
            raise PublishError("La operación aprobada no corresponde a una HU.")
        _check_project(target)
        if target.origin_kind == "story" and target.origin_key:
            key = target.origin_key
            epic_key = parent_key
            self.c.issue_tracker.update_story(key, story, _diff_comment_md(impact))
        else:
            epic_key = target.origin_key if target.origin_kind == "epic" else None
            key = self.c.issue_tracker.create_story(story, epic_key, target.project_key)
        # RF-06: vínculos a las HU afectadas (T-21), nunca a la épica (PA-38). Un vínculo que
        # falla no pierde lo ya publicado: se informa como error y se audita (RNF-13).
        errors: list[str] = []
        for item in _one_per_key(impact):
            if item.jira_key == epic_key:
                continue
            try:
                self.c.issue_tracker.link(key, item.jira_key, LINK_TYPE_IMPACT, item.reason)
            except ExternalServiceError:
                errors.append(f"No se pudo vincular {key} con {item.jira_key}.")
        return story.model_copy(update={"jira_key": key}), [key], errors

    # --- 8 · memorize ------------------------------------------------------------------------

    def memorize(self, state: AgentState) -> dict[str, Any]:
        artifact = state["artifact"]
        # D-07: en el MVP solo las HU publicadas generan memoria.
        if (
            artifact is None
            or artifact.type is not ArtifactType.USER_STORY
            or artifact.status is not ArtifactStatus.PUBLISHED
        ):
            return {}
        if not self.c.approvals.was_published(artifact):
            raise PublishError("No consta la publicación de esta versión; no se genera memoria.")
        memory = self.c.memory_generator.generate(artifact)
        markdown = memory.to_markdown()
        self.c.memory_dir.mkdir(parents=True, exist_ok=True)
        target = (self.c.memory_dir / f"{memory.jira_key}.md").resolve()
        if not JIRA_KEY.fullmatch(memory.jira_key) or not target.is_relative_to(
            self.c.memory_dir.resolve()
        ):
            raise ValueError(f"Clave de Jira no válida para la memoria: {memory.jira_key!r}.")
        target.write_text(markdown, encoding="utf-8")

        # Reindexado sin duplicados (RF-38): se sustituye la memoria anterior de la misma HU.
        document_id = f"memoria-{memory.jira_key}"
        (embedding,) = self.c.embeddings.embed([markdown])
        self.c.vector_store.delete_by_document(document_id)
        self.c.vector_store.upsert(
            [
                Chunk(
                    id=f"{document_id}-0",
                    document_id=document_id,
                    ordinal=0,
                    content=markdown,
                    embedding=embedding,
                    metadata={"category": "memoria", "related_key": memory.jira_key},
                )
            ]
        )
        log.info(
            "memoria actualizada",
            user=state["user"],
            action="memorize",
            artifact_id=str(artifact.id),
        )
        return {}


def _check_project(target: PublishTarget) -> None:
    """Nada se publica fuera del proyecto aprobado: la clave de origen tiene que ser suya (T-50)."""
    if not PROJECT_KEY.fullmatch(target.project_key):
        raise PublishError("La operación aprobada no indica un proyecto de Jira válido.")
    key = target.origin_key
    if key is not None and (not JIRA_KEY.fullmatch(key) or project_of(key) != target.project_key):
        raise PublishError(
            f"La incidencia {key} no pertenece al proyecto aprobado ({target.project_key})."
        )


def _parent_of(state: AgentState, key: str | None) -> str | None:
    """Épica de la incidencia `key` según el contexto de Jira del estado."""
    return next((i.parent_key for i in state["jira_context"] if i.key == key), None)


def _one_per_key(impact: ImpactAnalysis | None) -> list[ImpactItem]:
    """Un vínculo por HU afectada; su comentario reúne todos los motivos (§6.2)."""
    merged: dict[str, ImpactItem] = {}
    for item in impact.affected if impact else []:
        first = merged.get(item.jira_key)
        if first is None:
            merged[item.jira_key] = item
        elif item.reason not in first.reason:
            merged[item.jira_key] = first.model_copy(
                update={"reason": f"{first.reason} · {item.reason}"}
            )
    return list(merged.values())


def validate_origin(state: AgentState) -> None:
    """Valida modo y origen; se llama al cargar, al generar y al publicar."""
    origin = state["origin"]
    kind, key, text = origin.get("kind"), origin.get("key"), origin.get("text")
    project = origin.get("project")
    if kind not in ("epic", "story", "need"):
        raise ValueError(f"Tipo de origen no válido: {kind!r}.")
    handoff_id = state.get("handoff_id")
    if handoff_id is not None and (state["mode"] != "qa" or kind != "story"):
        raise ValueError("Solo una conversación de QA parte de una HU entregada a QA.")
    # T-54: una HU aprobada en simulación llega a QA sin clave de Jira.
    if kind in ("epic", "story") and not key and handoff_id is None:
        raise ValueError(f"El origen '{kind}' necesita una clave de Jira.")
    if key is not None and not JIRA_KEY.fullmatch(key):
        raise ValueError(f"Clave de Jira no válida: {key!r} (formato esperado: PROYECTO-123).")
    # T-50: cada conversación trabaja en un proyecto de Jira, y el origen pertenece a él.
    if not project:
        raise ValueError("Elige el proyecto de Jira de la conversación.")
    if not PROJECT_KEY.fullmatch(project):
        raise ValueError(
            f"Clave de proyecto no válida: {project[:50]!r} (formato esperado: PROYECTO)."
        )
    if key is not None and project_of(key) != project:
        raise ValueError(f"La incidencia {key} no pertenece al proyecto {project}.")
    if kind == "need" and not (text and text.strip()):
        raise ValueError("Una necesidad nueva necesita un texto descriptivo.")
    if state["mode"] not in ("functional", "qa"):
        raise ValueError(f"Modo no válido: {state['mode']!r}.")
    if state["mode"] == "qa" and kind != "story":
        raise ValueError("El modo QA parte siempre de una HU existente.")


def _check_actor(state: AgentState, config: RunnableConfig | None, required: bool = False) -> None:
    """Quien actúa (`configurable.user`, T-52) tiene que ser la dueña de la conversación.

    `new_conversation_config` y `resume_config` lo ponen siempre. Con `required`
    (`Container.require_actor`, activo en la app), una config sin `user` falla cerrada; sin él
    (pruebas y scripts con fakes) solo se compara si viene.
    """
    actor = ((config or {}).get("configurable") or {}).get("user")
    if (actor is None and required) or (actor is not None and actor != state["user"]):
        raise NotFoundError(NOT_YOURS, service="conversaciones")


def _target(
    state: AgentState, config: RunnableConfig | None, require_actor: bool = False
) -> PublishTarget:
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not thread_id:
        raise PublishError("Falta el identificador de la conversación (thread_id).")
    _check_actor(state, config, require_actor)
    origin = state["origin"]
    return PublishTarget(
        mode=state["mode"],
        origin_kind=origin["kind"],
        origin_key=origin.get("key"),
        project_key=origin.get("project") or "",
        user=state["user"],
        thread_id=str(thread_id),
    )


def _diff_comment_md(impact: ImpactAnalysis | None) -> str:
    lines = [
        "**Cambios propuestos por el agente y aprobados**",
        "",
        "| Campo | Antes | Después |",
        "|---|---|---|",
    ]
    for diff in impact.diffs if impact else []:
        cells = (diff.field, diff.before or "—", diff.after or "—")
        lines.append("| " + " | ".join(_table_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def _table_cell(value: str) -> str:
    """PA-201: un valor de la tabla del diff no añade columnas ni parte la fila."""
    return " ".join(value.split()).replace("|", "\\|")
