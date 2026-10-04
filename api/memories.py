"""Memorias publicadas (T-33, RF-36/RF-38): `GET /memories` y `GET /memories/{key}`.

Solo lectura sobre `core/memory/reader.py`: ni LLM, ni escrituras. Solo se ven las memorias de los
proyectos que ve la conexión de Jira; una memoria inexistente, de un proyecto que no se ve, ilegible
o con una clave no válida (también `../`) responden el mismo 404.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request

from api import examples as ex
from api.errors import ApiError
from api.models import PROJECT_PATTERN, ErrorResponse, MemoryOut, MemorySummary
from api.security import session_for
from core.memory.reader import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_QUERY_CHARS,
    MemoryReader,
    memory_title,
)
from core.memory.seed_demo import demo_memories
from core.permissions import Permission, require

router = APIRouter(prefix="/memories", tags=["Memoria"])
NOT_FOUND_MESSAGE = "No existe esa memoria o no la puedes ver."


def _json(example: Any) -> dict[str, Any]:
    return {"content": {"application/json": {"example": example}}}


def _err(code: str, message: str, description: str) -> dict[str, Any]:
    return {"model": ErrorResponse, "description": description, **_json(ex.error(code, message))}


def _responses() -> dict[int | str, dict[str, Any]]:
    from api.app import AUTH  # aquí: `api.app` incluye este router al crear la aplicación

    return dict(AUTH)


# --- Ejemplos (las memorias ficticias de `core.memory.seed_demo`) --------------------------------

_UPDATED = datetime(2026, 10, 2, 10, 30, tzinfo=UTC)
_EXAMPLES = demo_memories("DEMO")
MEMORY_LIST = [
    MemorySummary(
        key=memory.jira_key,
        project="DEMO",
        title=memory_title(memory),
        version=memory.version,
        updated_at=_UPDATED,
        indexed=index == 0,
    )
    for index, memory in enumerate(_EXAMPLES)
]
MEMORY = MemoryOut(
    **MEMORY_LIST[0].model_dump(), memory=_EXAMPLES[0], markdown=_EXAMPLES[0].to_markdown()
)


def _reader(request: Request) -> tuple[MemoryReader, list[str]]:
    """El lector del espacio de trabajo y los proyectos que ve la conexión."""
    session = session_for(request)
    require(session.user, Permission.VIEW_MEMORY)
    container = session.workspace.container
    visible = [project.key for project in container.issue_tracker.list_projects()]
    return MemoryReader(container.memory_dir, container.vector_store), visible


@router.get(
    "",
    response_model=list[MemorySummary],
    summary="Memorias de las HU publicadas (más recientes primero)",
    description="Solo las de los proyectos que ve la conexión de Jira. `q` busca, sin distinguir "
    "mayúsculas, en la clave y en el texto de la memoria. Lista vacía: «Aún no hay memorias. Se "
    "generan al publicar una HU en Jira (modo real).»",
    responses={200: _json(ex.dump(MEMORY_LIST)), **_responses()},
)
def list_memories(
    request: Request,
    project: str | None = Query(default=None, pattern=PROJECT_PATTERN, max_length=50),
    q: str = Query(default="", max_length=MAX_QUERY_CHARS),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
) -> list[MemorySummary]:
    reader, visible = _reader(request)
    return reader.summaries(
        visible, project=project.upper() if project else None, query=q, limit=limit
    )


@router.get(
    "/{key:path}",
    response_model=MemoryOut,
    summary="Una memoria: su contenido estructurado y su `.md`",
    description="`memory` se pinta campo a campo como texto (lo escribió el LLM); `markdown` es "
    "solo para descargarlo. El mismo 404 si no existe, si es de un proyecto que no ve la conexión "
    "o si la clave no es válida.",
    responses={
        200: _json(ex.dump(MEMORY)),
        **_responses(),
        404: _err("not_found", NOT_FOUND_MESSAGE, "No existe o no se puede ver (mismo mensaje)."),
    },
)
def get_memory(request: Request, key: str) -> MemoryOut:
    reader, visible = _reader(request)
    document = reader.get(key, visible)
    if document is None:
        raise ApiError(404, "not_found", NOT_FOUND_MESSAGE)
    return MemoryOut(
        **document.summary.model_dump(), memory=document.memory, markdown=document.markdown
    )
