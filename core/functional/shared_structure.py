"""Estructura compartida de una HU de Jira (PA-432, PA-456).

La misma HU de Jira sin cambios se estructura una sola vez: la versión estructurada se guarda en
el almacén de estado por clave y huella de **lo que recibe el modelo** al estructurar (la
incidencia de origen tal como se le envía) y de la versión del prompt `structure_story`. La usan
el grafo (`_baseline`) y la revisión de calidad, así que las dos parten de la misma HU y los mismos
IDs. Es solo un ahorro: si la entrada no está, no cuadra o el almacén falla, se estructura de nuevo.
"""

import hashlib

from core.artifact_state import ArtifactStateStore, structure_cache_id
from core.functional.context import StoryContext, render_context
from core.logging import get_logger
from schemas.user_story import UserStory

log = get_logger(__name__)

# Si cambia la forma de estructurar (código, no el prompt), se sube y no se reutiliza.
# 2 (PA-442): las anteriores pudieron estructurarse con la HU de origen recortada.
STRUCTURE_CACHE_VERSION = 2


def shared_structure_id(
    issue_key: str | None,
    origin_only: StoryContext,
    prompt_version: str,
    cache_version: int = STRUCTURE_CACHE_VERSION,
) -> str | None:
    """Identificador de la entrada compartida, o `None` sin clave de Jira."""
    if not issue_key:
        return None
    payload = f"{cache_version}\n{prompt_version}\n{render_context(origin_only)}"
    fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return structure_cache_id(issue_key, fingerprint)


def load_shared_structure(
    store: ArtifactStateStore, shared: str | None, issue_key: str | None
) -> UserStory | None:
    """La estructura compartida de esta HU (misma clave y contenido), o `None`."""
    if shared is None:
        return None
    try:
        saved = store.load(shared) or {}
        if saved.get("issue_key") != issue_key or not saved.get("baseline"):
            return None
        story = UserStory.model_validate(saved["baseline"])
    except Exception as exc:
        log.warning(
            "estructura compartida sin leer", action="structure_story", error=type(exc).__name__
        )
        return None
    if story.jira_key != issue_key:
        return None
    log.info("estructura compartida reutilizada", action="structure_story")
    return story


def save_shared_structure(
    store: ArtifactStateStore, shared: str | None, issue_key: str | None, story: UserStory
) -> None:
    """Guarda la estructura para las siguientes conversaciones y revisiones; nunca falla."""
    if shared is None:
        return
    try:
        store.save(shared, {"issue_key": issue_key, "baseline": story.model_dump(mode="json")})
    except Exception as exc:  # solo un ahorro: quien la pidió sigue con su estructura
        log.warning(
            "estructura compartida sin guardar",
            action="structure_story",
            error=type(exc).__name__,
        )
