"""Pausa de `human_review` y respuestas de la UI (`docs/specs/UI.md` §5, anexo §11 de la SPEC).

La pausa se detecta por las interrupciones pendientes del hilo, no por `next`: tras una
respuesta rechazada la revisión vuelve a pausar con `error`. La UI devuelve siempre la huella
del último payload recibido; nunca la guarda ni la reconstruye.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from schemas.artifact import Artifact
from schemas.impact import ImpactAnalysis


@dataclass(frozen=True)
class ReviewView:
    """Lo que la UI necesita de la pausa de `human_review`."""

    artifact: Artifact
    version: int
    fingerprint: str
    target: str
    plan: list[dict[str, str]]
    impact: ImpactAnalysis | None
    decisions: list[str]
    error: str | None


def parse_payload(payload: Mapping[str, Any]) -> ReviewView:
    impact = payload.get("impact")
    return ReviewView(
        artifact=Artifact.model_validate(payload["artifact"]),
        version=int(payload["version"]),
        fingerprint=str(payload["fingerprint"]),
        target=str(payload.get("target") or ""),
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
    """Pausa a partir de `graph.get_state(config)`: interrupciones de sus tareas."""
    values = [v for task in getattr(snapshot, "tasks", ()) for v in _values(task.interrupts)]
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


def summarize(view: ReviewView) -> str:
    """Mensaje del asistente al llegar una versión (Mixta 2b y 3)."""
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
    if kind == "link":
        return f"Vincular {op.get('from', '')} con {op.get('to', '')} ({op.get('type', '')})"
    if kind == "publish_suite":
        return f"Publicar {op.get('cases', '')} casos de prueba en {op.get('story', '')}"
    return kind
