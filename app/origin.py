"""Del arranque guiado al estado inicial del grafo (Mixta 1, 1b y 2; `docs/specs/UI.md` §4).

Las claves escritas y las HU parecidas las reconoce `core/guided_start.GuidedStart` (T-53, sin
IA); aquí solo se decide qué opción se propone y se construyen el `Origin`, las restricciones
(`origin.text` en una necesidad nueva, `feedback` en una evolución, T-51) y las fuentes
excluidas. Funciones puras.
"""

import re
from dataclasses import dataclass, field, replace
from typing import Literal

from app.flows import FlowId
from core.graph import Origin, initial_state
from core.graph.state import AgentState
from core.guided_start import StartOption, StartProposal
from core.projects import normalize_issue_key, normalize_project_key, project_of

Mode = Literal["functional", "qa"]
OriginKind = Literal["epic", "story", "need"]

NEED_TEXT_REQUIRED = "Describe la necesidad antes de continuar."
KEY_REQUIRED = "Escribe la clave de la HU de Jira, por ejemplo DEMO-3."
EPIC_NOT_ALLOWED = "Para este flujo elige una HU, no una épica."
QA_NEEDS_STORY = "El modo QA parte siempre de una HU existente."
# Opciones de `GuidedStart` que admite cada flujo de la pantalla de inicio.
_OPTION_KINDS: dict[FlowId, tuple[str, ...]] = {
    "need": ("evolve", "new_story_in_epic", "new_need"),
    "evolve": ("evolve",),
    "review": ("evolve",),
    "tests": ("tests",),
}


def mode_of(flow: FlowId) -> Mode:
    return "qa" if flow == "tests" else "functional"


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
        return mode_of(self.flow)

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
    """Fija el origen elegido en Jira (Mixta 1b, recientes); `ValueError` con mensaje para la UI.

    Una clave de otro proyecto cambia el proyecto de la conversación (decisión del día 6). La
    clave escrita en el texto la reconoce `GuidedStart` (`request_from_option`), no esta función.
    """
    project = normalize_project_key(project)
    text = text.strip()
    if key is None and flow in ("evolve", "review", "tests"):
        raise ValueError(KEY_REQUIRED)
    if key is not None:
        key = normalize_issue_key(key)
        project = project_of(key)
    if flow == "need":
        if key is not None and kind in (None, "story"):
            kind = "story"  # una HU: se propone evolucionarla
        elif key is not None:
            kind = "epic"
        else:
            kind = "need"
            if not text:
                raise ValueError(NEED_TEXT_REQUIRED)
    elif kind == "epic":
        raise ValueError(EPIC_NOT_ALLOWED)
    else:
        kind = "story"
    effective_flow: FlowId = "evolve" if flow == "need" and kind == "story" else flow
    return StartRequest(flow=effective_flow, kind=kind, project=project, key=key, text=text)


def request_from_option(flow: FlowId, option: StartOption, text: str = "") -> StartRequest:
    """`StartRequest` de una opción de `GuidedStart.propose` (su `origin` manda)."""
    origin = option.origin
    if option.kind == "new_need":
        return fix_origin("need", origin.get("project", ""), text=origin.get("text") or text)
    kind: OriginKind = "epic" if origin["kind"] == "epic" else "story"
    return fix_origin(
        "tests" if flow == "tests" else "need" if kind == "epic" else "evolve",
        origin.get("project", ""),
        key=origin.get("key"),
        kind=kind,
        text=text,
    )


@dataclass(frozen=True)
class StartPlan:
    """Qué hace la UI con la propuesta de `GuidedStart` para el flujo elegido."""

    chosen: StartOption | None  # opción que fija el origen y abre Mixta 2
    alternatives: list[StartOption]  # HU parecidas que se ofrecen en Mixta 2 (o para elegir)
    notices: list[str]  # avisos de cambio de proyecto y claves de otros proyectos
    error: str | None = None


def plan_start(flow: FlowId, proposal: StartProposal, previous_project: str) -> StartPlan:
    """Decide la opción por defecto, las alternativas y los avisos (UI.md §4.1 y §4.3)."""
    notices: list[str] = []
    if proposal.project_changed:
        notices.append(
            f"La clave que has escrito es del proyecto {proposal.project}: la conversación "
            f"pasa de {previous_project} a {proposal.project}."
        )
    if proposal.ignored_projects:
        notices.append(
            "Hay claves de otros proyectos que no se usan: "
            + ", ".join(proposal.ignored_projects)
            + ". Una conversación trabaja en un solo proyecto."
        )
    options = [o for o in proposal.options if o.kind in _OPTION_KINDS[flow]]
    if proposal.recognized:
        if not options:
            return StartPlan(None, [], notices, _no_option_error(flow))
        return StartPlan(options[0], options[1:], notices)
    if flow == "need":
        new = next((o for o in options if o.kind == "new_need"), None)
        if new is None:
            return StartPlan(None, [], notices, NEED_TEXT_REQUIRED)
        return StartPlan(new, [o for o in options if o is not new], notices)
    # Evolucionar o preparar pruebas sin clave: la persona elige entre las HU parecidas.
    return StartPlan(None, options, notices, None if options else KEY_REQUIRED)


def _no_option_error(flow: FlowId) -> str:
    if flow == "tests":
        return QA_NEEDS_STORY
    if flow in ("evolve", "review"):
        return EPIC_NOT_ALLOWED
    return KEY_REQUIRED


def with_restrictions(request: StartRequest, restrictions: str) -> StartRequest:
    return replace(request, restrictions=restrictions.strip())


def with_excluded(request: StartRequest, excluded: list[str]) -> StartRequest:
    return replace(request, excluded_sources=tuple(sorted({ref for ref in excluded if ref})))


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


def preview_origin(request: StartRequest) -> Origin:
    """`Origin` para la vista previa de fuentes, antes de escribir las restricciones.

    En una necesidad, las restricciones se añaden después a `origin.text` (la consulta al RAG):
    las fuentes que reúna el grafo pueden variar algo respecto a la vista previa.
    """
    return build_origin(replace(request, restrictions=""))


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


def request_from_state(origin: Origin, mode: Mode, excluded: list[str]) -> StartRequest:
    """`StartRequest` de una conversación retomada, a partir del estado del grafo (T-52)."""
    kind = origin["kind"]
    flow: FlowId = "tests" if mode == "qa" else "evolve" if kind == "story" else "need"
    return StartRequest(
        flow=flow,
        kind=kind,
        project=origin.get("project", ""),
        key=origin.get("key"),
        text=origin.get("text", "") if kind == "need" else "",
        excluded_sources=tuple(excluded),
    )
