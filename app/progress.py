"""Fase de la Q y progreso de la generación (Mixta 2b; `docs/specs/UI.md` §2 y §8).

`graph.stream` solo distingue nodos (`load_origin`, `retrieve_context`, `generate`): escribir,
validar citas y analizar el impacto ocurren dentro de `generate` (PA-66, sesión A).
"""

from dataclasses import dataclass

from schemas.common import ArtifactStatus

PHASES: tuple[str, ...] = ("Contexto", "Generar", "Revisión", "Publicado")


@dataclass(frozen=True)
class Step:
    node: str
    label: str


STEPS: tuple[Step, ...] = (
    Step("load_origin", "Leer el origen en Jira"),
    Step("retrieve_context", "Recuperar el contexto (Jira, documentos y memoria)"),
    Step("generate", "Generar la propuesta, validar las citas y analizar el impacto"),
)
_NODES = [step.node for step in STEPS]


def phase_of(status: ArtifactStatus | None) -> int:
    """Fase de la conversación (1 a 4) según el estado del artefacto."""
    if status is None:
        return 1
    if status == ArtifactStatus.APPROVED:
        return 3
    if status == ArtifactStatus.PUBLISHED:
        return 4
    return 2


def phase_label(phase: int) -> str:
    return f"Fase {phase} de {len(PHASES)} · {PHASES[phase - 1]}"


def completed_steps(nodes_done: list[str]) -> int:
    """Pasos terminados a partir de los nodos que ya ha emitido `graph.stream`."""
    return max((_NODES.index(n) + 1 for n in nodes_done if n in _NODES), default=0)


def nodes_in_update(update: object) -> list[str]:
    """Nodos de un evento de `graph.stream(..., stream_mode="updates")`."""
    if not isinstance(update, dict):
        return []
    return [str(name) for name in update if not str(name).startswith("__")]
