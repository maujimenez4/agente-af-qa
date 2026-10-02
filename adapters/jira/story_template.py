"""Plantilla de la HU en Jira: título con prefijo `[HU-XX]` (R-05) y descripción en ADF (T-27).

La descripción se construye directamente en ADF a partir de los campos de `UserStory`, sin
pasar el texto por un intérprete de Markdown: lo que escribe el LLM o la persona revisora se
publica como texto literal y no puede inyectar estructura (PA-49).
"""

import re

from adapters.jira.adf import (
    Node,
    bullet_list,
    clean_text,
    code_block,
    doc,
    heading,
    paragraph,
    text,
)
from schemas.user_story import AcceptanceCriterion, UserStory

MAX_SUMMARY_CHARS = 255  # límite de Jira para `summary`
_INTERNAL_ID = re.compile(r"^HU-\d+$")
_WHITESPACE = re.compile(r"\s+")

# (campo de UserStory, título de la sección) para las listas simples, en orden de publicación.
_LIST_SECTIONS: tuple[tuple[str, str], ...] = (
    ("assumptions", "Supuestos"),
    ("constraints", "Restricciones"),
    ("dependencies", "Dependencias"),
    ("alternate_flows", "Flujos alternos"),
    ("exceptions", "Excepciones"),
    ("related_features", "Funcionalidades relacionadas"),
    ("related_requirements", "Requisitos relacionados"),
    ("changes_from_previous", "Cambios respecto a la versión anterior"),
    ("open_questions", "Preguntas abiertas"),
)


def story_summary(story: UserStory) -> str:
    """Título de la incidencia: `[HU-XX] título` (R-05), en una línea y dentro del límite."""
    internal_id = story.internal_id or ""
    valid_id = internal_id if _INTERNAL_ID.fullmatch(internal_id) else None
    return prefixed_summary(valid_id, story.title)


def prefixed_summary(internal_id: str | None, title: str) -> str:
    """`[ID] título` (R-05) sin duplicar el prefijo, en una línea y dentro del límite de Jira."""
    title = _WHITESPACE.sub(" ", clean_text(title)).strip()
    if internal_id and not title.startswith(f"[{internal_id}]"):
        title = f"[{internal_id}] {title}"
    return title[:MAX_SUMMARY_CHARS]


def story_to_adf(story: UserStory) -> Node:
    """Descripción de la HU con la plantilla del proyecto (RF-15): CA en Gherkin, RN, alcance…"""
    content: list[Node] = [
        paragraph(
            [
                *text("Como ", strong=True),
                *text(story.role),
                *text(", quiero ", strong=True),
                *text(story.action),
                *text(", para ", strong=True),
                *text(story.benefit),
            ]
        )
    ]
    content += _text_section("Descripción", story.description)
    content += _text_section("Objetivo de negocio", story.business_goal)
    if story.scope_includes or story.scope_excludes:
        content.append(heading("Alcance", 2))
        content += _list_section("Incluye", story.scope_includes, level=3)
        content += _list_section("Excluye", story.scope_excludes, level=3)
    content.append(heading("Criterios de aceptación", 2))
    for criterion in story.acceptance_criteria:
        content.append(heading(f"{criterion.id} · {criterion.title}", 3))
        content.append(code_block(_gherkin(criterion), "gherkin"))
    if story.business_rules:
        content.append(heading("Reglas de negocio", 2))
        content.append(
            bullet_list(
                [
                    [*text(rule.id, strong=True), *text(f": {rule.description}")]
                    for rule in story.business_rules
                ]
            )
        )
    for field, title in _LIST_SECTIONS:
        content += _list_section(title, getattr(story, field))
    content.append(heading("Prioridad", 2))
    content.append(paragraph(text(story.priority.value)))
    if story.sources:
        content += _list_section(
            "Fuentes", [f"{source.kind} · {source.ref}" for source in story.sources]
        )
    return doc(content)


def _gherkin(criterion: AcceptanceCriterion) -> str:
    lines = [f"Escenario: {criterion.title}"]
    for keyword, steps in (
        ("Dado", criterion.given),
        ("Cuando", criterion.when),
        ("Entonces", criterion.then),
    ):
        lines += [f"  {keyword if i == 0 else 'Y'} {step}" for i, step in enumerate(steps)]
    return "\n".join(lines)


def _text_section(title: str, value: str) -> list[Node]:
    if not value.strip():
        return []
    return [heading(title, 2), paragraph(text(value.strip()))]


def _list_section(title: str, items: list[str], level: int = 2) -> list[Node]:
    items = [item.strip() for item in items if item.strip()]
    if not items:
        return []
    return [heading(title, level), bullet_list([text(item) for item in items])]
