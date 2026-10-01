"""Flujos de trabajo de la pantalla de inicio (Mixta 1, `docs/specs/UI.md` §4.1 y §3).

Cada tarjeta exige un permiso de `core/permissions.py`. La UI solo arranca los flujos cuyo
backend ya existe; el resto se muestra desactivado con la tarea que lo traerá.
"""

from dataclasses import dataclass
from typing import Literal

from adapters.base import User
from core.permissions import Permission, can

FlowId = Literal["need", "evolve", "review", "tests"]


@dataclass(frozen=True)
class Flow:
    id: FlowId
    label: str
    hint: str
    placeholder: str
    permission: Permission
    pending_task: str | None = None  # tarea que lo habilitará; None = disponible


FLOWS: tuple[Flow, ...] = (
    Flow(
        id="need",
        label="Nueva necesidad",
        hint="Describe lo que hace falta y propongo una HU nueva.",
        placeholder=(
            "Describe la necesidad. Si escribes una clave de Jira, por ejemplo DEMO-3, "
            "la reconozco."
        ),
        permission=Permission.GENERATE_STORY,
    ),
    Flow(
        id="evolve",
        label="Evolucionar una HU",
        hint="Parte de una HU de Jira y propón su nueva versión con el diff.",
        placeholder="Escribe la clave de la HU, por ejemplo DEMO-3, y qué quieres cambiar.",
        permission=Permission.GENERATE_STORY,
    ),
    Flow(
        id="review",
        label="Revisar la calidad de una HU",
        hint="Informe con INVEST, ambigüedades y huecos. No cambia nada en Jira.",
        placeholder="Escribe la clave de la HU que quieres revisar, por ejemplo DEMO-4.",
        permission=Permission.GENERATE_STORY,  # provisional: lo fija T-48
        pending_task="T-48",
    ),
    Flow(
        id="tests",
        label="Preparar pruebas",
        hint="Casos, cobertura, datos y estrategia de una HU.",
        placeholder="Escribe la clave de la HU para la que quieres pruebas, por ejemplo DEMO-3.",
        permission=Permission.GENERATE_TESTS,
        pending_task="T-28",
    ),
)

_OTHER_ROLE_HINT = {
    Permission.GENERATE_STORY: "Disponible para el rol de analista funcional.",
    Permission.GENERATE_TESTS: "Disponible para el rol QA.",
}


@dataclass(frozen=True)
class FlowCard:
    flow: Flow
    allowed: bool  # el rol tiene el permiso
    enabled: bool  # se puede elegir ahora (permiso y backend disponible)
    hint: str


def flow_by_id(flow_id: FlowId) -> Flow:
    return next(flow for flow in FLOWS if flow.id == flow_id)


def shows_flows(user: User | None) -> bool:
    """El administrador configura pero no genera (D-01): no ve las tarjetas de flujo."""
    return any(can(user, flow.permission) for flow in FLOWS)


def flow_cards(user: User | None) -> list[FlowCard]:
    """Las cuatro tarjetas, con su estado para el rol de la persona."""
    cards: list[FlowCard] = []
    for flow in FLOWS:
        allowed = can(user, flow.permission)
        if not allowed:
            hint = _OTHER_ROLE_HINT[flow.permission]
        elif flow.pending_task:
            hint = f"{flow.hint} Disponible pronto ({flow.pending_task})."
        else:
            hint = flow.hint
        enabled = allowed and flow.pending_task is None
        cards.append(FlowCard(flow=flow, allowed=allowed, enabled=enabled, hint=hint))
    return cards


def default_flow(user: User | None) -> FlowId | None:
    """Primer flujo que la persona puede usar ahora; None si ninguno."""
    return next((card.flow.id for card in flow_cards(user) if card.enabled), None)
