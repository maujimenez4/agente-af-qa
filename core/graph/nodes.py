"""Nodos del grafo (SPEC-00 §5.2). Solo `publish` escribe en Jira, y solo artefactos APPROVED.

Esqueleto del día 1: la lógica de contexto (T-18), los prompts (T-20/T-26), la auditoría
(T-25) y la memoria real (T-33) se completan en sus tareas.
"""

import json
import re
import time
from typing import Any
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from adapters.base import Chunk, IssueDetail, Message, TaskType
from adapters.errors import PublishError
from core.approvals import Approval, PublishTarget, review_fingerprint
from core.container import Container
from core.graph.state import AgentState, Decision
from core.logging import get_logger
from core.state_machine import transition
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from schemas.impact import ImpactAnalysis
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

DECISIONS: tuple[Decision, ...] = ("iterate", "approve", "discard")
LINK_TYPE_IMPACT = "relates to"  # D-09
# Clave de Jira: evita rutas o JQL inyectadas a través del origen (p. ej. "../x").
JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")

log = get_logger("core.graph")


class GraphNodes:
    def __init__(self, container: Container) -> None:
        self.c = container

    # --- 1 · load_origin -------------------------------------------------------------------

    def load_origin(self, state: AgentState) -> dict[str, Any]:
        validate_origin(state)
        key = state["origin"].get("key")
        jira_context = [self.c.issue_tracker.get_issue(key)] if key else []
        return {"jira_context": jira_context}

    # --- 2–3 · retrieve_context ------------------------------------------------------------

    def retrieve_context(self, state: AgentState) -> dict[str, Any]:
        issues: dict[str, IssueDetail] = {i.key: i for i in state["jira_context"]}
        for issue in list(issues.values()):
            related = [link.key for link in issue.links]
            if issue.parent_key:
                related.append(issue.parent_key)
                related += [s.key for s in self.c.issue_tracker.list_children(issue.parent_key)]
            if state["origin"]["kind"] == "epic":
                # Las HU de la épica serán las hermanas de la HU nueva.
                related += [s.key for s in self.c.issue_tracker.list_children(issue.key)]
            for key in related:
                if key not in issues:
                    issues[key] = self.c.issue_tracker.get_issue(key)

        query = state["origin"].get("text") or " ".join(
            f"{i.summary} {i.description_text}" for i in state["jira_context"]
        )
        rag_context = []
        if query.strip():
            (vector,) = self.c.embeddings.embed([query])
            rag_context = self.c.vector_store.search(
                vector, query, k=self.c.top_k, memory_boost=self.c.memory_boost
            )
        return {"jira_context": list(issues.values()), "rag_context": rag_context}

    # --- 4 · generate ----------------------------------------------------------------------

    def generate(self, state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        validate_origin(state)  # el estado puede haber cambiado al iterar
        messages = [Message(role="user", content=_context_json(state))]
        origin = state["origin"]
        impact: ImpactAnalysis | None = None

        if state["mode"] == "qa":
            result = self.c.llm.generate_structured(messages, TestSuite, TaskType.GENERATE_TESTS)
            content: UserStory | TestSuite = result.content.model_copy(
                update={"story_jira_key": origin["key"]}
            )
            artifact_type = ArtifactType.TEST_SUITE
        else:
            evolving = origin["kind"] == "story"
            task = TaskType.EVOLVE_STORY if evolving else TaskType.GENERATE_STORY
            result = self.c.llm.generate_structured(messages, UserStory, task)
            content = result.content
            if evolving:
                content = content.model_copy(update={"jira_key": origin["key"]})
                impact = self.c.llm.generate_structured(
                    messages, ImpactAnalysis, TaskType.ANALYZE_IMPACT
                ).content
            artifact_type = ArtifactType.USER_STORY

        model_used = f"{result.provider}/{result.model}"
        previous = state["artifact"]
        if previous is None:
            artifact = Artifact(
                id=uuid4(),
                type=artifact_type,
                status=ArtifactStatus.DRAFT,
                version=1,
                origin_key=origin.get("key"),
                content=content,
                impact=impact,
                created_by=state["user"],
                model_used=model_used,
            )
        else:  # iteración: misma identidad, nueva versión (RF-20)
            artifact = previous.model_copy(
                update={
                    "version": previous.version + 1,
                    "content": content,
                    "impact": impact,
                    "model_used": model_used,
                }
            )
        artifact = transition(artifact, ArtifactStatus.IN_REVIEW)
        # Solo la versión ofrecida aquí podrá aprobarse en human_review.
        self.c.approvals.offer(artifact, _target(state, config))
        log.info(
            "propuesta generada",
            user=state["user"],
            action="create" if previous is None else "iterate",
            artifact_id=str(artifact.id),
            model=model_used,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return {"artifact": artifact, "decision": None}

    # --- 5–6 · human_review ----------------------------------------------------------------

    def human_review(
        self, state: AgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        artifact = state["artifact"]
        if artifact is None:
            raise ValueError("No hay ningún artefacto que revisar.")
        target = _target(state, config)
        fingerprint = review_fingerprint(artifact, target)
        answer = interrupt(
            {
                "artifact": artifact.model_dump(mode="json"),
                "version": artifact.version,
                # Operación que se ejecutará en Jira si se aprueba (se muestra a la persona).
                "target": target.describe(),
                # La UI devuelve esta huella al aprobar: se aprueba exactamente lo que se vio.
                "fingerprint": fingerprint,
                "impact": artifact.impact.model_dump(mode="json") if artifact.impact else None,
                "decisions": list(DECISIONS),
            }
        )
        decision = answer.get("decision") if isinstance(answer, dict) else None
        if decision not in DECISIONS:
            raise ValueError(f"Decisión no válida: {decision!r}. Usa iterate, approve o discard.")
        feedback = (answer.get("feedback") or "").strip()
        if decision == "approve" and answer.get("fingerprint") != fingerprint:
            raise ValueError(
                "La aprobación no corresponde a la versión revisada; vuelve a revisar el artefacto."
            )

        status = {
            "iterate": ArtifactStatus.DRAFT,
            "approve": ArtifactStatus.APPROVED,
            "discard": ArtifactStatus.DISCARDED,
        }[decision]
        reviewed = transition(artifact, status)
        if decision == "approve":
            # Falla si no es la versión y la operación ofrecidas por generate (ApprovalError).
            self.c.approvals.record(reviewed, target)
        update: dict[str, Any] = {"artifact": reviewed, "decision": decision}
        if feedback:
            update["feedback"] = [*state["feedback"], feedback]
        log.info(
            "revisión humana", user=state["user"], action=decision, artifact_id=str(artifact.id)
        )
        return update

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
        # El estado del grafo puede alterarse: la aprobación y la operación salen del registro.
        approval = self.c.approvals.find(artifact, _target(state, config))
        if approval is None:
            raise PublishError(
                "No consta una aprobación humana vigente para esta versión exacta del artefacto."
            )

        if isinstance(artifact.content, TestSuite):
            target = approval.target
            if (
                target.mode != "qa"
                or target.origin_kind != "story"
                or artifact.content.story_jira_key != target.origin_key
            ):
                raise PublishError("La operación aprobada no corresponde a estos casos de prueba.")
            result = self.c.test_management.publish_suite(artifact.content)
            errors = [f"No se pudo publicar {case_id}." for case_id in result.failed]
            published = transition(artifact, ArtifactStatus.PUBLISHED) if not errors else artifact
            keys = result.created
        else:
            story, keys, errors = self._publish_story(approval, artifact)
            artifact = artifact.model_copy(update={"content": story})
            published = transition(artifact, ArtifactStatus.PUBLISHED)
        if published.status is ArtifactStatus.PUBLISHED:
            self.c.approvals.consume(approval, published)  # un solo uso

        log.info(
            "publicación en Jira",
            user=state["user"],
            action="publish",
            artifact_id=str(artifact.id),
            jira_keys=keys,
            failed=len(errors),
        )
        return {
            "artifact": published,
            "published_keys": [*state["published_keys"], *keys],
            "errors": [*state["errors"], *errors],
        }

    def _publish_story(
        self, approval: Approval, artifact: Artifact
    ) -> tuple[UserStory, list[str], list[str]]:
        story = artifact.content
        target, impact = approval.target, artifact.impact
        if not isinstance(story, UserStory) or target.mode != "functional":
            raise PublishError("La operación aprobada no corresponde a una HU.")
        if target.origin_kind == "story" and target.origin_key:
            key = target.origin_key
            self.c.issue_tracker.update_story(key, story, _diff_comment_md(impact))
            for item in impact.affected if impact else []:
                self.c.issue_tracker.link(key, item.jira_key, LINK_TYPE_IMPACT, item.reason)
        else:
            epic_key = target.origin_key if target.origin_kind == "epic" else None
            key = self.c.issue_tracker.create_story(story, epic_key)
        return story.model_copy(update={"jira_key": key}), [key], []

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


def validate_origin(state: AgentState) -> None:
    """Valida modo y origen; se llama al cargar, al generar y al publicar."""
    origin = state["origin"]
    kind, key, text = origin.get("kind"), origin.get("key"), origin.get("text")
    if kind not in ("epic", "story", "need"):
        raise ValueError(f"Tipo de origen no válido: {kind!r}.")
    if kind in ("epic", "story") and not key:
        raise ValueError(f"El origen '{kind}' necesita una clave de Jira.")
    if key is not None and not JIRA_KEY.fullmatch(key):
        raise ValueError(f"Clave de Jira no válida: {key!r} (formato esperado: PROYECTO-123).")
    if kind == "need" and not (text and text.strip()):
        raise ValueError("Una necesidad nueva necesita un texto descriptivo.")
    if state["mode"] not in ("functional", "qa"):
        raise ValueError(f"Modo no válido: {state['mode']!r}.")
    if state["mode"] == "qa" and kind != "story":
        raise ValueError("El modo QA parte siempre de una HU existente.")


def _target(state: AgentState, config: RunnableConfig | None) -> PublishTarget:
    thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
    if not thread_id:
        raise PublishError("Falta el identificador de la conversación (thread_id).")
    origin = state["origin"]
    return PublishTarget(
        mode=state["mode"],
        origin_kind=origin["kind"],
        origin_key=origin.get("key"),
        user=state["user"],
        thread_id=str(thread_id),
    )


def _context_json(state: AgentState) -> str:
    """Contexto estructurado para el LLM; las instrucciones irán en prompts/ (T-20, T-26)."""
    payload = {
        "mode": state["mode"],
        "origin": dict(state["origin"]),
        "jira_context": [i.model_dump(mode="json") for i in state["jira_context"]],
        "rag_context": [
            {"source": r.source.model_dump(mode="json"), "content": r.chunk.content}
            for r in state["rag_context"]
        ],
        "previous": state["artifact"].content.model_dump(mode="json")
        if state["artifact"]
        else None,
        "feedback": state["feedback"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _diff_comment_md(impact: ImpactAnalysis | None) -> str:
    lines = [
        "**Cambios propuestos por el agente y aprobados**",
        "",
        "| Campo | Antes | Después |",
        "|---|---|---|",
    ]
    for diff in impact.diffs if impact else []:
        lines.append(f"| {diff.field} | {diff.before or '—'} | {diff.after or '—'} |")
    return "\n".join(lines)
