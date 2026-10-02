"""Fragmentación por encabezados + recursiva, con metadatos (RF-09).

1. Se corta por encabezados Markdown (`#` a `######`); cada sección conserva su jerarquía.
2. Las secciones que superan `chunk_tokens` se dividen recursivamente por párrafos, líneas,
   frases y palabras, con un solapamiento de `overlap_tokens` entre fragmentos consecutivos.

Los tokens se estiman como `ceil(caracteres / 4)`: no hay tokenizador local sin descargas.
Las memorias (`memoria`) no se fragmentan (SPEC-00 §6).
"""

import math
import re
from dataclasses import dataclass

from adapters.base import Chunk
from core.config import AppConfig
from core.rag.documents import MEMORY_CATEGORY, IngestedDocument

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SEPARATORS = ("\n\n", "\n", ". ", " ")
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


@dataclass(frozen=True)
class Section:
    path: tuple[str, ...]
    text: str


def split_sections(markdown: str) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []  # (nivel, título)
    current_path: tuple[str, ...] = ()
    buffer: list[str] = []
    in_code = False

    def flush() -> None:
        text = "\n".join(buffer).strip("\n")
        if text.strip():
            sections.append(Section(path=current_path, text=text))

    for line in markdown.split("\n"):
        if _FENCE.match(line):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match:
            flush()
            buffer = []
            level, title = len(match.group(1)), match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            current_path = tuple(t for _, t in stack)
        buffer.append(line)
    flush()
    return sections


def split_recursive(text: str, chunk_tokens: int, overlap_tokens: int) -> list[str]:
    if chunk_tokens <= 0:
        raise ValueError("chunk_tokens debe ser mayor que 0.")
    if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
        raise ValueError("overlap_tokens debe estar entre 0 y chunk_tokens - 1.")
    if estimate_tokens(text) <= chunk_tokens:
        return [text] if text.strip() else []
    max_chars = chunk_tokens * _CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * _CHARS_PER_TOKEN
    pieces = _atomize(text, max_chars - overlap_chars)
    return _merge(pieces, max_chars, overlap_chars)


def _atomize(text: str, limit: int, level: int = 0) -> list[str]:
    """Divide en piezas de como mucho `limit` caracteres; cada pieza conserva su separador."""
    if len(text) <= limit:
        return [text]
    if level >= len(_SEPARATORS):
        return [text[i : i + limit] for i in range(0, len(text), limit)]
    separator = _SEPARATORS[level]
    parts = text.split(separator)
    pieces: list[str] = []
    for index, part in enumerate(parts):
        piece = part + separator if index < len(parts) - 1 else part
        if not piece:
            continue
        pieces.extend(_atomize(piece, limit, level + 1) if len(piece) > limit else [piece])
    return pieces


def _merge(pieces: list[str], max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for piece in pieces:
        if current and size + len(piece) > max_chars:
            chunks.append("".join(current))
            current = _overlap(current, overlap_chars)
            size = sum(len(p) for p in current)
        current.append(piece)
        size += len(piece)
    if current:
        chunks.append("".join(current))
    return [c.strip() for c in chunks if c.strip()]


def _overlap(pieces: list[str], overlap_chars: int) -> list[str]:
    """Piezas finales enteras que caben en el solapamiento (no parte filas ni frases)."""
    if overlap_chars <= 0:
        return []
    kept: list[str] = []
    size = 0
    for piece in reversed(pieces):
        if size + len(piece) > overlap_chars:
            break
        kept.insert(0, piece)
        size += len(piece)
    if kept:
        return kept
    last = pieces[-1]
    if last.lstrip().startswith("|"):
        return []  # una fila de tabla no se parte para solapar
    # Párrafo, frase o palabra larga: su final desde un límite de palabra (PA-211: antes un
    # párrafo terminado en salto de línea dejaba el solapamiento vacío). Se conserva su
    # separador final para que no se pegue con la pieza siguiente.
    body = last.rstrip()
    separator = last[len(body) :]
    tail = body[-overlap_chars:]
    index = tail.find(" ")
    tail = tail[index + 1 :] if 0 <= index < len(tail) - 1 else tail
    return [tail + separator] if tail else []


def chunk_document(doc: IngestedDocument, chunk_tokens: int, overlap_tokens: int) -> list[Chunk]:
    # Los campos propios del documento prevalecen sobre su metadata libre.
    base = {**doc.metadata, "category": doc.category, "title": doc.title, "source": doc.source_path}
    if doc.category == MEMORY_CATEGORY:
        return [
            Chunk(id=f"{doc.id}#0", document_id=doc.id, ordinal=0, content=doc.text, metadata=base)
        ]

    chunks: list[Chunk] = []
    for section in split_sections(doc.text):
        name = " > ".join(section.path) or None
        metadata = {**base, "section": name} if name else dict(base)
        for content in split_recursive(section.text, chunk_tokens, overlap_tokens):
            ordinal = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{doc.id}#{ordinal}",
                    document_id=doc.id,
                    ordinal=ordinal,
                    section=name,
                    content=content,
                    metadata=metadata,
                )
            )
    return chunks


def chunk_with_config(doc: IngestedDocument, config: AppConfig) -> list[Chunk]:
    rag = config.models.rag
    return chunk_document(doc, rag.chunk_tokens, rag.overlap_tokens)
