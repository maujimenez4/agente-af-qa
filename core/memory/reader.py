"""Lectura de las memorias publicadas (T-33, RF-36/RF-38): la pestaña Memoria y `GET /memories`.

Solo lee: ni LLM, ni Jira (salvo los proyectos visibles, que da quien llama), ni escrituras. Las
memorias son los `.md` que escribe el nodo `memorize` en `memory_dir` (`<CLAVE>.md`, formato de
`Memory.to_markdown()`); «indexada» es que el documento `memoria-<CLAVE>` está en el vector store.

Seguridad: la clave se valida con `ISSUE_KEY` y la ruta resuelta debe quedar dentro de
`memory_dir`; una memoria inexistente, ilegible, de un proyecto que la conexión no ve o con una
clave no válida dan el mismo resultado (`None`), para que la API responda el mismo 404.
"""

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from adapters.base import VectorStore
from core.logging import get_logger
from core.projects import ISSUE_KEY, project_of
from schemas.memory import _SECTIONS as SECTIONS  # mismos títulos y orden que `to_markdown`
from schemas.memory import Memory

log = get_logger(__name__)

DOCUMENT_PREFIX = "memoria-"  # el mismo identificador que usa `memorize` al reindexar
TITLE_MAX_CHARS = 120
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_QUERY_CHARS = 100
MAX_FILE_BYTES = 256 * 1024  # una memoria real ocupa unos pocos KB
EMPTY_SECTION = "—"
_FRONTMATTER = re.compile(r"\A---\n(?P<head>.*?)\n---\n", re.DOTALL)
_TEXT_FIELDS = {name for name, info in Memory.model_fields.items() if info.annotation is str}


class MemorySummary(BaseModel):
    """Una memoria en la lista (sin su contenido)."""

    key: str = Field(description="Clave de la HU en Jira.")
    project: str
    title: str = Field(description="El objetivo de la memoria, recortado a 120 caracteres.")
    version: int = Field(description="Versión de la HU publicada que resume.")
    updated_at: datetime = Field(description="Última vez que se escribió la memoria (UTC).")
    indexed: bool = Field(description="Si está incorporada al RAG (`memoria-<CLAVE>`).")


class MemoryDocument(BaseModel):
    """Una memoria completa: resumen, contenido estructurado y su `.md`."""

    summary: MemorySummary
    memory: Memory
    markdown: str


def parse_memory(text: str) -> Memory:
    """`.md` de `Memory.to_markdown()` → `Memory`. `ValueError` si no tiene ese formato."""
    text = text.replace("\r\n", "\n")
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError("Sin cabecera de memoria.")
    head: dict[str, str] = {}
    for line in match.group("head").splitlines():
        name, sep, value = line.partition(":")
        if sep:
            head[name.strip()] = value.strip()
    sections = _sections(text[match.end() :].splitlines())
    fields: dict[str, object] = {}
    for title, name in SECTIONS:
        lines = sections[title]
        fields[name] = _text(lines) if name in _TEXT_FIELDS else _items(lines)
    try:
        return Memory.model_validate(
            {
                "jira_key": head.get("jira_key", ""),
                "artifact_type": head.get("artifact_type", ""),
                "version": head.get("version", ""),
                **fields,
            }
        )
    except ValidationError:
        raise ValueError("Cabecera o secciones de memoria no válidas.") from None


def _sections(lines: list[str]) -> dict[str, list[str]]:
    """Reparte las líneas por sección. Los encabezados se buscan **en orden**, así que un
    `## Algo` dentro del texto del LLM no abre una sección nueva, salvo que sea justo el título
    de la siguiente (limitación del formato sin escapar: PA-288)."""
    titles = [title for title, _name in SECTIONS]
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in lines:
        expected = titles[len(found)] if len(found) < len(titles) else None
        if expected is not None and line == f"## {expected}":
            current = found.setdefault(expected, [])
        elif current is not None:
            current.append(line)
    if len(found) != len(titles):
        raise ValueError("Faltan secciones de la memoria.")
    return found


def _text(lines: list[str]) -> str:
    value = "\n".join(lines).strip()
    return "" if value == EMPTY_SECTION else value


def _items(lines: list[str]) -> list[str]:
    items: list[str] = []
    for line in "\n".join(lines).strip("\n").splitlines():
        if line.startswith("- ") or line == "-":  # `to_markdown` escribe «- » si está vacío
            items.append(line[2:])
        elif items:  # continuación de un elemento con saltos de línea
            items[-1] += "\n" + line
        elif line.strip() != EMPTY_SECTION and line.strip():
            raise ValueError("Lista de memoria no válida.")
    return items


def memory_title(memory: Memory) -> str:
    """El objetivo en una línea, recortado a `TITLE_MAX_CHARS`; si no hay, «Memoria de CLAVE»."""
    title = " ".join(memory.objective.split())
    if not title:
        return f"Memoria de {memory.jira_key}"
    if len(title) > TITLE_MAX_CHARS:
        return title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return title


class MemoryReader:
    """Lista y lee las memorias de `memory_dir` de los proyectos que ve la conexión."""

    def __init__(self, memory_dir: Path, vector_store: VectorStore) -> None:
        self._dir = memory_dir
        self._vectors = vector_store

    def summaries(
        self,
        visible_projects: Iterable[str],
        *,
        project: str | None = None,
        query: str = "",
        limit: int = DEFAULT_LIMIT,
    ) -> list[MemorySummary]:
        """Más recientes primero. `query` busca, sin distinguir mayúsculas, en la clave y en el
        texto de la memoria. Los archivos que no son memorias se ignoran."""
        visible = set(visible_projects)
        if project is not None:
            visible &= {project}
        needle = query.strip()[:MAX_QUERY_CHARS].casefold()
        found: list[tuple[datetime, str, Memory]] = []
        for path in self._files():
            key = path.stem
            if project_of(key) not in visible:
                continue
            loaded = self._load(path, key)
            if loaded is None:
                continue
            memory, markdown, updated_at = loaded
            if needle and needle not in key.casefold() and needle not in markdown.casefold():
                continue
            found.append((updated_at, key, memory))
        found.sort(key=lambda row: (row[0], row[1]), reverse=True)
        limit = max(1, min(limit, MAX_LIMIT))
        # El vector store solo se consulta para lo que se devuelve.
        return [self._summary(memory, updated_at) for updated_at, _key, memory in found[:limit]]

    def get(self, raw_key: str, visible_projects: Iterable[str]) -> MemoryDocument | None:
        """La memoria de `raw_key`, o `None` si no existe, no se puede leer, la clave no es
        válida o su proyecto no es visible (el mismo resultado en todos los casos)."""
        key = raw_key.strip().upper()
        if not ISSUE_KEY.fullmatch(key) or project_of(key) not in set(visible_projects):
            return None
        path = self._path(key)
        if path is None:
            return None
        loaded = self._load(path, key)
        if loaded is None:
            return None
        memory, markdown, updated_at = loaded
        return MemoryDocument(
            summary=self._summary(memory, updated_at), memory=memory, markdown=markdown
        )

    # --- Archivos -------------------------------------------------------------------------------

    def _root(self) -> Path | None:
        root = self._dir.resolve()
        return root if root.is_dir() else None

    def _files(self) -> list[Path]:
        root = self._root()
        if root is None:
            return []
        return [
            path
            for path in root.glob("*.md")
            if ISSUE_KEY.fullmatch(path.stem) and self._inside(root, path)
        ]

    def _path(self, key: str) -> Path | None:
        root = self._root()
        if root is None:
            return None
        path = root / f"{key}.md"
        return path if self._inside(root, path) else None

    @staticmethod
    def _inside(root: Path, path: Path) -> bool:
        """El archivo existe y, ya resuelto (enlaces incluidos), sigue dentro de `memory_dir`."""
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            return False
        return resolved.is_file() and resolved.is_relative_to(root)

    def _load(self, path: Path, key: str) -> tuple[Memory, str, datetime] | None:
        try:
            stat = path.stat()
            if stat.st_size > MAX_FILE_BYTES:
                raise ValueError("Memoria demasiado grande.")
            markdown = path.read_text(encoding="utf-8")
            memory = parse_memory(markdown)
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            log.warning("memoria ilegible", action="read_memory", error=type(exc).__name__)
            return None
        if memory.jira_key != key:  # la cabecera no puede hacerse pasar por otra HU
            log.warning("memoria ilegible", action="read_memory", error="clave distinta")
            return None
        return memory, markdown, datetime.fromtimestamp(stat.st_mtime, UTC)

    def _summary(self, memory: Memory, updated_at: datetime) -> MemorySummary:
        return MemorySummary(
            key=memory.jira_key,
            project=project_of(memory.jira_key),
            title=memory_title(memory),
            version=memory.version,
            updated_at=updated_at,
            indexed=self._vectors.has_document(f"{DOCUMENT_PREFIX}{memory.jira_key}"),
        )
