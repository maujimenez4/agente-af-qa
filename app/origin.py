"""Del arranque guiado al estado inicial del grafo (Mixta 1, 1b y 2; `docs/specs/UI.md` §4).

Funciones puras: reconocen la clave escrita, construyen el `Origin` y reparten las
restricciones entre `origin.text` (necesidad nueva) y `feedback` (evolución), como fija T-51.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.flows import FlowId
from core.graph import Origin, initial_state
from core.graph.state import AgentState
from core.projects import normalize_issue_key, normalize_project_key, project_of

# Candidata a clave dentro de un texto libre (se valida después con `normalize_issue_key`).
_KEY_IN_TEXT = re.compile(r"\b[A-Za-z][A-Za-z0-9_]+-\d+\b")

Mode = Literal["functional", "qa"]
OriginKind = Literal["epic", "story", "need"]


def find_issue_key(text: str, prefer_project: str | None = None) -> str | None:
    """Clave de Jira escrita en el texto (sin IA, T-53 parcial).

    Prefiere las del proyecto de la conversación, para que fragmentos con forma de clave
    («UTF-8», «ISO-9001») no ganen a la clave real; si no hay ninguna, la primera válida.
    """
    keys: list[str] = []
    for candidate in _KEY_IN_TEXT.findall(text):
        try:
            keys.append(normalize_issue_key(candidate))
        except ValueError:
            continue
    if prefer_project:
        preferred = prefer_project.strip().upper()
        for key in keys:
            if project_of(key) == preferred:
                return key
    return keys[0] if keys else None


@dataclass(frozen=True)
class StartRequest:
    """Lo que la persona fija antes de generar; es la operación que se podrá aprobar."""

    flow: FlowId
    kind: OriginKind
    project: str
    key: str | None = None
    text: str = ""
    restrictions: str = ""
    excluded_sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def mode(self) -> Mode:
        return "qa" if self.flow == "tests" else "functional"

    def describe(self) -> str:
        """Texto de la tarjeta «Operación fijada»."""
        if self.flow == "tests" and self.key:
            return f"Suite de pruebas de {self.key}"
        if self.kind == "story" and self.key:
            return f"Evolucionar {self.key}"
        if self.kind == "epic" and self.key:
            return f"Crear una HU nueva en la épica {self.key}"
        return f"Crear una HU nueva en el proyecto {self.project}"


def change_request(request: StartRequest) -> str:
    """Lo que la persona pidió junto a la clave («DEMO-3 y qué cambiar»), sin la clave."""
    text = request.text
    if request.key:
        text = re.sub(rf"\b{re.escape(request.key)}\b", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip(" ,.;:")


def fix_origin(
    flow: FlowId,
    project: str,
    *,
    key: str | None = None,
    kind: OriginKind | None = None,
    text: str = "",
) -> StartRequest:
    """Fija el origen de la conversación; `ValueError` con mensaje para la UI si no es válido.

    Una clave de otro proyecto cambia el proyecto de la conversación (decisión del día 6).
    """
    project = normalize_project_key(project)
    text = text.strip()
    if key is None and flow in ("evolve", "review", "tests"):
        key = find_issue_key(text, prefer_project=project)
        if key is None:
            raise ValueError("Escribe la clave de la HU de Jira, por ejemplo DEMO-3.")
    if key is not None:
        key = normalize_issue_key(key)
        project = project_of(key)
    if flow == "need":
        if key is not None and kind in (None, "story"):
            kind = "story"  # una HU parecida: se propone evolucionarla
        elif key is not None:
            kind = "epic"
        else:
            kind = "need"
            if not text:
                raise ValueError("Describe la necesidad antes de continuar.")
    elif kind == "epic":
        raise ValueError("Para este flujo elige una HU, no una épica.")
    else:
        kind = "story"
    effective_flow: FlowId = "evolve" if flow == "need" and kind == "story" else flow
    return StartRequest(flow=effective_flow, kind=kind, project=project, key=key, text=text)


def with_restrictions(request: StartRequest, restrictions: str) -> StartRequest:
    return StartRequest(
        flow=request.flow,
        kind=request.kind,
        project=request.project,
        key=request.key,
        text=request.text,
        restrictions=restrictions.strip(),
        excluded_sources=request.excluded_sources,
    )


def with_excluded(request: StartRequest, excluded: list[str]) -> StartRequest:
    return StartRequest(
        flow=request.flow,
        kind=request.kind,
        project=request.project,
        key=request.key,
        text=request.text,
        restrictions=request.restrictions,
        excluded_sources=tuple(sorted({ref for ref in excluded if ref})),
    )


def build_origin(request: StartRequest) -> Origin:
    """`Origin` del grafo. En una necesidad, las restricciones se añaden al texto (UI.md §4.3)."""
    if request.kind == "need":
        text = request.text
        if request.restrictions:
            text = f"{text}\n\nRestricciones: {request.restrictions}"
        return {"kind": "need", "project": request.project, "text": text}
    if request.key is None:
        raise ValueError("Falta la clave de Jira del origen.")
    return {"kind": request.kind, "key": request.key, "project": request.project}


def build_feedback(request: StartRequest) -> list[str]:
    """Con una clave de origen, lo pedido junto a ella y las restricciones van como feedback
    previo a la primera versión (T-51); en `origin.text` sustituirían la consulta al RAG.
    """
    if request.kind == "need":
        return []
    return [part for part in (change_request(request), request.restrictions) if part]


def build_initial_state(user: str, request: StartRequest) -> AgentState:
    return initial_state(
        user,
        request.mode,
        build_origin(request),
        excluded_sources=list(request.excluded_sources),
        feedback=build_feedback(request),
    )
