"""*Editar a mano* una HU (Mixta 3, decisión `edit`; RF-32, T-51).

Funciones puras entre la `UserStory` y los campos del formulario. Las claves (`jira_key`,
`internal_id`) y los ID de CA y RN no se editan; las fuentes citadas se conservan. Las listas
se editan como una línea por elemento.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from schemas.user_story import UserStory

TEXT_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Título"),
    ("role", "Como"),
    ("action", "Quiero"),
    ("benefit", "Para"),
    ("description", "Descripción"),
    ("business_goal", "Objetivo de negocio"),
)
LIST_FIELDS: tuple[tuple[str, str], ...] = (
    ("scope_includes", "Alcance · incluye"),
    ("scope_excludes", "Alcance · excluye"),
    ("assumptions", "Supuestos"),
    ("constraints", "Restricciones"),
    ("dependencies", "Dependencias"),
    ("alternate_flows", "Flujos alternos"),
    ("exceptions", "Excepciones"),
    ("related_features", "Funcionalidades relacionadas"),
    ("open_questions", "Preguntas abiertas"),
)
STEP_FIELDS: tuple[tuple[str, str], ...] = (
    ("given", "Dado"),
    ("when", "Cuando"),
    ("then", "Entonces"),
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def story_to_form(story: UserStory) -> dict[str, Any]:
    """Valores iniciales del formulario."""
    form: dict[str, Any] = {name: getattr(story, name) for name, _ in TEXT_FIELDS}
    form |= {name: "\n".join(getattr(story, name)) for name, _ in LIST_FIELDS}
    form["criteria"] = [
        {
            "id": ca.id,
            "title": ca.title,
            **{step: "\n".join(getattr(ca, step)) for step, _ in STEP_FIELDS},
        }
        for ca in story.acceptance_criteria
    ]
    form["rules"] = [{"id": rn.id, "description": rn.description} for rn in story.business_rules]
    return form


def form_to_content(story: UserStory, form: Mapping[str, Any]) -> dict[str, Any]:
    """Contenido completo editado para `{"decision": "edit", "content": …}`.

    `ValueError` con mensaje para la UI si la HU resultante no es válida o no cambia nada.
    """
    content = story.model_dump(mode="json")
    for name, _ in TEXT_FIELDS:
        content[name] = str(form.get(name, "")).strip()
    for name, _ in LIST_FIELDS:
        content[name] = _lines(str(form.get(name, "")))
    criteria = {c["id"]: c for c in form.get("criteria", [])}
    for ca in content["acceptance_criteria"]:
        edited_ca = criteria.get(ca["id"])
        if edited_ca is None:
            continue  # el CA no está en el formulario: se conserva tal cual
        ca["title"] = str(edited_ca.get("title", "")).strip()
        for step, _ in STEP_FIELDS:
            ca[step] = _lines(str(edited_ca.get(step, "")))
    rules = {r["id"]: r for r in form.get("rules", [])}
    content["business_rules"] = [
        {"id": rn["id"], "description": str(rules.get(rn["id"], rn)["description"]).strip()}
        for rn in content["business_rules"]
    ]
    try:
        edited = UserStory.model_validate(content)
    except ValidationError as exc:
        raise ValueError(f"La HU editada no es válida: {_first_error(exc)}") from None
    if edited == story:
        raise ValueError("No has cambiado nada de la propuesta.")
    return edited.model_dump(mode="json")


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error.get("loc", ()))
    return f"{where}: {error.get('msg', '')}" if where else str(error.get("msg", ""))
