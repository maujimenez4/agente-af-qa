"""Arranque guiado sin IA (T-53, RF-14, RF-19): de lo que escribe la persona a un origen fijado.

Antes de arrancar el grafo, la UI propone con qué empezar:
- si el texto trae claves de Jira que existen, la HU o la épica (y su proyecto, que cambia el de
  la conversación si es otro, T-50);
- si no, HU parecidas del proyecto por búsqueda de texto en Jira, para evolucionar una de ellas o
  crear una HU nueva.

Además da la vista previa de las fuentes del panel «Antes de generar», con el mismo `gather` que
usará `retrieve_context`, para que la persona desmarque las que no quiere (`excluded_sources`).
Nada de este módulo llama al LLM; la vista previa solo usa los embeddings del RAG.
"""

import re
from typing import Literal

from pydantic import BaseModel

from adapters.base import IssueDetail, IssueSummary
from adapters.errors import AuthenticationError, ExternalServiceError
from core.container import Container
from core.context.budget import BudgetReport
from core.context.service import EPIC_TYPES, NOT_STORIES, build_context_service, type_key
from core.graph.state import Origin, normalize_excluded_sources
from core.projects import ISSUE_KEY, normalize_project_key, project_of

MAX_KEYS = 5
# Mayúsculas o minúsculas («demo-3»): solo cuenta si la incidencia existe en Jira (decisión del
# usuario), así «covid-19» no se toma por una clave.
_KEY_IN_TEXT = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_]+-\d+)(?![A-Za-z0-9_-])")
Mode = Literal["functional", "qa"]
OptionKind = Literal["evolve", "new_story_in_epic", "tests", "new_need"]


class StartOption(BaseModel):
    """Una forma de empezar; `origin` va tal cual a `initial_state`."""

    kind: OptionKind
    label: str  # texto del botón, p. ej. «Evolucionar DEMO-3»
    origin: Origin
    issue: IssueSummary | None = None


class StartProposal(BaseModel):
    project: str  # el de la conversación tras aplicar las claves encontradas
    project_changed: bool  # una clave de otro proyecto lo ha cambiado (avisar en la UI)
    ignored_projects: list[str] = []  # claves de otros proyectos sin opción (avisar en la UI)
    recognized: list[IssueSummary]  # claves del texto que existen en Jira
    similar: list[IssueSummary]  # HU parecidas por texto (solo si no hay claves)
    options: list[StartOption]


class SourcePreview(BaseModel):
    """Una fila del panel de fuentes; `ref` es lo que se pasa en `excluded_sources`."""

    ref: str
    kind: Literal["jira", "rag", "memory"]
    title: str
    category: str | None = None
    required: bool = False  # la incidencia de origen no se puede desmarcar (T-51)


def find_issue_keys(text: str, limit: int = MAX_KEYS) -> list[str]:
    """Claves con forma `PROYECTO-123` en el texto, en mayúsculas, sin repetir y en orden."""
    keys: list[str] = []
    for match in _KEY_IN_TEXT.finditer(text or ""):
        if len(keys) >= limit:
            break
        key = match.group(1).upper()
        if ISSUE_KEY.fullmatch(key) and key not in keys:
            keys.append(key)
    return keys


class GuidedStart:
    def __init__(self, container: Container) -> None:
        self.c = container

    def propose(self, text: str, project: str, mode: Mode = "functional") -> StartProposal:
        """Propuestas de arranque para el texto escrito en el proyecto de la conversación."""
        current = normalize_project_key(project)
        recognized = [issue for key in find_issue_keys(text) if (issue := self._existing(key))]
        if recognized:
            candidates = [option for issue in recognized if (option := _option_for(issue, mode))]
            # Manda la primera clave que da una opción; sin ninguna, el proyecto no cambia.
            new_project = candidates[0].origin["project"] if candidates else current
            # Solo opciones de ese proyecto: nadie arranca en otro sin que la UI lo avise.
            options = [o for o in candidates if o.origin["project"] == new_project]
            ignored = sorted({o.origin["project"] for o in candidates} - {new_project})
            if not options and mode == "functional" and text.strip():
                # Solo subtareas o tareas: no se deja a la persona sin acción.
                options.append(_new_need(text, new_project))
            return StartProposal(
                project=new_project,
                project_changed=new_project != current,
                ignored_projects=ignored,
                recognized=[_summary(i) for i in recognized],
                similar=[],
                options=options,
            )

        similar = (
            build_context_service(self.c, current).similar_stories(text, current)
            if text.strip()
            else []
        )
        options = [
            StartOption(
                kind="tests" if mode == "qa" else "evolve",
                label=f"{'Preparar pruebas de' if mode == 'qa' else 'Evolucionar'} {issue.key}",
                origin=Origin(kind="story", key=issue.key, project=current),
                issue=issue,
            )
            for issue in similar
        ]
        if mode == "functional" and text.strip():
            options.append(_new_need(text, current))
        return StartProposal(
            project=current, project_changed=False, recognized=[], similar=similar, options=options
        )

    def preview_sources(
        self, origin: Origin, excluded: list[str] | None = None
    ) -> list[SourcePreview]:
        """Fuentes que usaría la propuesta (las mismas que reunirá `retrieve_context`)."""
        return self.preview_sources_with_budget(origin, excluded)[0]

    def preview_sources_with_budget(
        self, origin: Origin, excluded: list[str] | None = None
    ) -> tuple[list[SourcePreview], BudgetReport]:
        """Fuentes y presupuesto de tokens del contexto (PA-102, panel «Antes de generar»)."""
        key = origin.get("key")
        if key and project_of(key) != origin.get("project"):
            raise ValueError(
                f"La incidencia {key} no pertenece al proyecto {origin.get('project')}."
            )
        # PA-223: mismas reglas que el grafo (limpieza, tope, formato y origen no excluible).
        cleaned = normalize_excluded_sources(excluded, key)
        origin_issue = self.c.issue_tracker.get_issue(key) if key else None
        gathered = build_context_service(self.c, origin.get("project")).gather(
            origin, origin_issue, excluded=cleaned
        )
        rows: dict[str, SourcePreview] = {}
        for issue in gathered.jira:
            rows.setdefault(
                issue.key,
                SourcePreview(
                    ref=issue.key,
                    kind="jira",
                    title=issue.summary,
                    category=issue.issue_type or None,
                    required=issue.key == key,
                ),
            )
        for hit in gathered.rag:
            meta = hit.chunk.metadata
            rows.setdefault(
                hit.source.ref,
                SourcePreview(
                    ref=hit.source.ref,
                    kind=hit.source.kind,
                    title=meta.get("title") or hit.chunk.section or hit.source.ref,
                    category=meta.get("category"),
                ),
            )
        return list(rows.values()), gathered.budget

    def _existing(self, key: str) -> IssueDetail | None:
        """La incidencia si existe; un 429 o 5xx en una clave no corta la propuesta (401/403 sí)."""
        try:
            return self.c.issue_tracker.get_issue(key)
        except AuthenticationError:
            raise
        except ExternalServiceError:  # NotFoundError, RateLimitError, errores de Jira
            return None


def _new_need(text: str, project: str) -> StartOption:
    return StartOption(
        kind="new_need",
        label="Crear HU nueva",
        origin=Origin(kind="need", text=text.strip(), project=project),
    )


def _summary(issue: IssueDetail) -> IssueSummary:
    return IssueSummary(
        key=issue.key, summary=issue.summary, issue_type=issue.issue_type, status=issue.status
    )


def _option_for(issue: IssueDetail, mode: Mode) -> StartOption | None:
    """Opción para una clave reconocida; las subtareas y tareas no son origen."""
    kind = type_key(issue.issue_type)  # PA-223: también «Épica» en NFD
    project = project_of(issue.key)
    if kind in EPIC_TYPES:
        if mode == "qa":
            return None  # «El modo QA parte siempre de una HU existente.»
        return StartOption(
            kind="new_story_in_epic",
            label=f"Nueva HU en {issue.key}",
            origin=Origin(kind="epic", key=issue.key, project=project),
            issue=_summary(issue),
        )
    if kind in NOT_STORIES:
        return None
    if mode == "qa":
        return StartOption(
            kind="tests",
            label=f"Preparar pruebas de {issue.key}",
            origin=Origin(kind="story", key=issue.key, project=project),
            issue=_summary(issue),
        )
    return StartOption(
        kind="evolve",
        label=f"Evolucionar {issue.key}",
        origin=Origin(kind="story", key=issue.key, project=project),
        issue=_summary(issue),
    )
