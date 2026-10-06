"""Pausa de `human_review` y respuestas de la UI (`docs/specs/UI.md` §5, anexo §11 de la SPEC).

La pausa se detecta por las interrupciones pendientes del hilo, no por `next`: tras una
respuesta rechazada la revisión vuelve a pausar con `error`. La UI devuelve siempre la huella
del último payload recibido; nunca la guarda ni la reconstruye.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.qa import suite_summary
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType
from schemas.impact import ImpactAnalysis
from schemas.test_case import TestSuite


@dataclass(frozen=True)
class ReviewView:
    """Lo que la UI necesita de la pausa de `human_review`."""

    artifact: Artifact
    version: int
    fingerprint: str
    target: str  # operación descrita en texto (`describe_target`)
    plan: list[dict[str, str]]
    impact: ImpactAnalysis | None
    decisions: list[str]
    error: str | None
    target_info: Mapping[str, str | None] | None = None  # `PublishTarget.describe()`


_OPERATIONS = {
    "actualizar HU": "Actualizar {jira_key}",
    "crear HU": "Crear una HU nueva",
    "publicar casos de prueba": "Publicar los casos de prueba de {jira_key}",
}


def describe_target(target: Mapping[str, str | None]) -> str:
    """«Actualizar DEMO-3 · proyecto DEMO» a partir de `PublishTarget.describe()`."""
    operation = str(target.get("operation") or "")
    text = _OPERATIONS.get(operation, operation).replace(
        "{jira_key}", str(target.get("jira_key") or "")
    )
    if target.get("epic_key"):
        text += f" en la épica {target['epic_key']}"
    if target.get("project"):
        text += f" · proyecto {target['project']}"
    return text.strip()


def parse_payload(payload: Mapping[str, Any]) -> ReviewView:
    impact = payload.get("impact")
    raw_target = payload.get("target")
    info = dict(raw_target) if isinstance(raw_target, Mapping) else None
    return ReviewView(
        artifact=Artifact.model_validate(payload["artifact"]),
        version=int(payload["version"]),
        fingerprint=str(payload["fingerprint"]),
        target=describe_target(info) if info is not None else str(raw_target or ""),
        target_info=info,
        plan=[dict(op) for op in payload.get("plan") or []],
        impact=ImpactAnalysis.model_validate(impact) if impact else None,
        decisions=[str(d) for d in payload.get("decisions") or []],
        error=payload.get("error") or None,
    )


def _values(interrupts: Iterable[Any]) -> list[Mapping[str, Any]]:
    return [i.value for i in interrupts if isinstance(getattr(i, "value", None), Mapping)]


def pending_from_result(result: Mapping[str, Any]) -> ReviewView | None:
    """Pausa a partir del resultado de `invoke` (`__interrupt__`); None si el grafo terminó."""
    values = _values(result.get("__interrupt__") or ())
    return parse_payload(values[-1]) if values else None


def pending_from_state(snapshot: Any) -> ReviewView | None:
    """Pausa a partir de `graph.get_state(config)`: interrupciones de sus tareas.

    Una tarea que falló (p. ej. `ApprovalError` en `human_review`, que falla cerrado) conserva
    su interrupción en LangGraph, pero ya no es una revisión abierta: se ignora.
    """
    values = [
        v
        for task in getattr(snapshot, "tasks", ())
        if getattr(task, "error", None) is None
        for v in _values(task.interrupts)
    ]
    return parse_payload(values[-1]) if values else None


def iterate_answer(feedback: str) -> dict[str, Any]:
    """Pedir un cambio (RF-20). `ValueError` si el mensaje está vacío."""
    text = feedback.strip()
    if not text:
        raise ValueError("Escribe qué quieres cambiar de la propuesta.")
    return {"decision": "iterate", "feedback": text}


def edit_answer(view: ReviewView, content: Mapping[str, Any]) -> dict[str, Any]:
    """Editar a mano (RF-32): contenido completo y la huella de la versión revisada."""
    return {"decision": "edit", "content": dict(content), "fingerprint": view.fingerprint}


def discard_answer() -> dict[str, Any]:
    return {"decision": "discard"}


def approve_answer(view: ReviewView) -> dict[str, Any]:
    """Aprobar (UI.md §5): la huella exacta del último payload, nunca guardada ni rehecha."""
    return {"decision": "approve", "fingerprint": view.fingerprint}


def summarize(view: ReviewView) -> str:
    """Mensaje del asistente al llegar una versión (Mixta 2b y 3; QA 2 y QA 3)."""
    if isinstance(view.artifact.content, TestSuite):
        return suite_summary(view.artifact.content, view.version)
    impact = view.impact
    changes = len(impact.diffs) if impact else 0
    affected = sorted({item.jira_key for item in impact.affected}) if impact else []
    text = f"Versión {view.version} lista"
    if changes:
        text += f": {changes} cambios frente a la versión de partida"
    if affected:
        text += f". Afecta también a {', '.join(affected)}"
    return text + ". Revisa la propuesta en el panel y pídeme los cambios que quieras."


def describe_operation(op: Mapping[str, str]) -> str:
    """Texto de una operación del `plan` para mostrarla (el recibo completo es T-31)."""
    kind = op.get("op", "")
    if kind == "update_story":
        return f"Actualizar {op.get('key', '')} con la versión revisada"
    if kind == "create_story":
        epic = op.get("epic")
        where = f"en la épica {epic}" if epic else f"en el proyecto {op.get('project', '')}"
        return f"Crear una HU nueva {where}"
    if kind == "comment":
        return f"Añadir a {op.get('key', '')} un comentario con los cambios"
    if kind == "link":
        return f"Vincular {op.get('from', '')} con {op.get('to', '')} ({op.get('type', '')})"
    if kind == "publish_suite":
        return f"Publicar {op.get('cases', '')} casos de prueba en {op.get('story', '')}"
    return kind


# --- Recibo de aprobación (UI.md §4.6 y §6.4, RF-31) ---------------------------------------------


@dataclass(frozen=True)
class ReceiptItem:
    """Una casilla del recibo: lo que `publish` hará en Jira si se aprueba."""

    id: str  # estable dentro de la versión (clave de la casilla)
    text: str
    detail: str = ""


_FIELD_LABELS = {
    "title": "título",
    "role": "como",
    "action": "quiero",
    "benefit": "para",
    "description": "descripción",
    "business_goal": "objetivo de negocio",
    "priority": "prioridad",
    "scope_includes": "alcance (incluye)",
    "scope_excludes": "alcance (excluye)",
    "assumptions": "supuestos",
    "constraints": "restricciones",
    "dependencies": "dependencias",
    "alternate_flows": "flujos alternos",
    "exceptions": "excepciones",
    "related_features": "funcionalidades relacionadas",
    "open_questions": "preguntas abiertas",
    "sources": "fuentes",
}
_INDEXED_FIELD = re.compile(r"^(\w+)\[([^\]]+)\]$")


def field_label(field: str) -> str:
    """Nombre legible de un campo del diff: «CA-03», «fuentes», «descripción»…"""
    if match := _INDEXED_FIELD.match(field):
        name, item = match.groups()
        return (
            item
            if name in ("acceptance_criteria", "business_rules")
            else _FIELD_LABELS.get(name, name)
        )
    return _FIELD_LABELS.get(field, field)


def _changed_fields(impact: ImpactAnalysis | None) -> str:
    if impact is None or not impact.diffs:
        return ""
    fields = list(dict.fromkeys(field_label(diff.field) for diff in impact.diffs))
    shown = ", ".join(fields[:8]) + (f" y {len(fields) - 8} más" if len(fields) > 8 else "")
    return f"Cambia: {shown}."


def _link_reason(impact: ImpactAnalysis | None, key: str) -> str:
    if impact is None:
        return ""
    return " ".join(item.reason for item in impact.affected if item.jira_key == key)


def receipt_items(view: ReviewView) -> list[ReceiptItem]:
    """Una casilla por operación del `plan`.

    `publish_suite` se desglosa como lo publica T-30 (D-09): las subtareas de los casos y los
    adjuntos de estrategia y matriz.
    """
    items: list[ReceiptItem] = []
    for index, op in enumerate(view.plan):
        kind = op.get("op", "")
        if kind == "update_story":
            text = f"Actualizar {op.get('key', '')} con la versión {view.version}"
            items.append(ReceiptItem(f"{index}-update", text, _changed_fields(view.impact)))
        elif kind == "comment":
            items.append(
                ReceiptItem(f"{index}-comment", describe_operation(op), "Tabla antes / después.")
            )
        elif kind == "create_story":
            items.append(
                ReceiptItem(f"{index}-create", describe_operation(op), "Con la versión revisada.")
            )
        elif kind == "link":
            to = op.get("to", "")
            text = f"Vincular con {to} ({op.get('type', '')})"
            items.append(ReceiptItem(f"{index}-link-{to}", text, _link_reason(view.impact, to)))
        elif kind == "publish_suite":
            story = op.get("story", "")
            items += [
                ReceiptItem(
                    f"{index}-cases",
                    f"Crear {op.get('cases', '')} subtareas en {story} con la etiqueta "
                    "«caso-prueba»",
                    "Pasos, datos, resultado esperado y prioridad de cada caso.",
                ),
                ReceiptItem(f"{index}-strategy", f"Adjuntar estrategia-{story}.md"),
                ReceiptItem(
                    f"{index}-matrix", f"Adjuntar matriz-{story}.md", "Cobertura CA/RN ↔ CP."
                ),
            ]
        else:
            items.append(ReceiptItem(f"{index}-{kind}", describe_operation(op)))
    return items


def receipt_progress(items: list[ReceiptItem], checked: Mapping[str, bool]) -> tuple[int, bool]:
    """(Revisadas, todas revisadas). Sin operaciones no se puede aprobar."""
    done = sum(1 for item in items if checked.get(item.id))
    return done, bool(items) and done == len(items)


def source_count(view: ReviewView) -> int:
    return len(getattr(view.artifact.content, "sources", None) or [])


# --- Marcas «Cambiado en vN» / «Nueva» (PA-73) -----------------------------------------------

_ITEM_FIELD = re.compile(r"^(acceptance_criteria|business_rules)\[([A-Z]{2}-\d+)\]$")


def change_marks(view: ReviewView) -> dict[str, str]:
    """Marca de cada CA y RN cambiado frente a la versión de partida (`impact.diffs`)."""
    marks: dict[str, str] = {}
    for diff in view.impact.diffs if view.impact else []:
        match = _ITEM_FIELD.match(diff.field)
        if match is None or diff.after is None:  # eliminados: ya no están en la propuesta
            continue
        marks[match.group(2)] = "Nueva" if diff.before is None else f"Cambiado en v{view.version}"
    return marks


# --- Resultado tras aprobar (UI.md §4.7 y §6.5) ----------------------------------------------

OutcomeKind = Literal["simulated", "published", "partial", "published_without_memory"]


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    version: int
    approved_by: str
    operations: list[str]  # lo que se hizo (o se habría hecho, en simulación)
    published_keys: list[str]
    errors: list[str]
    message: str | None = None  # p. ej. el motivo del fallo de la memoria
    story: bool = True  # HU (genera memoria, D-07) o suite de pruebas


def outcome_from_state(
    values: Mapping[str, Any],
    approved: ReviewView,
    user: str,
    *,
    failure: str | None = None,
) -> Outcome | None:
    """Resultado de la publicación a partir del estado del grafo; None si no se aprobó.

    Simulado: el artefacto sigue `APPROVED` sin claves y la aprobación queda gastada (PA-41).
    Real: `PUBLISHED` con `published_keys`. Parcial: hay `errors` (RNF-13); una suite con
    fallos no pasa a publicada (T-30). Si algo falla después de publicar (la memoria, PA-251),
    se informa sin decir que no se escribió nada.
    """
    artifact = values.get("artifact")
    if not isinstance(artifact, Artifact) or values.get("decision") != "approve":
        return None
    keys = [str(key) for key in values.get("published_keys") or []]
    errors = [str(error) for error in values.get("errors") or []]
    common: dict[str, Any] = {
        "version": artifact.version,
        "approved_by": user,
        "operations": [describe_operation(op) for op in approved.plan],
        "published_keys": keys,
        "errors": errors,
        "story": artifact.type is ArtifactType.USER_STORY,
    }
    if artifact.status is ArtifactStatus.PUBLISHED:
        if failure is not None:
            return Outcome("published_without_memory", message=failure, **common)
        return Outcome("partial" if errors else "published", **common)
    if errors or keys:
        return Outcome("partial", **common)
    if artifact.status is ArtifactStatus.APPROVED:
        return Outcome("simulated", **common)
    return None
