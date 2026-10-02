"""Ingesta de documentos: carga, extracción con Docling, normalización y clasificación.

- RF-07: admite PDF, DOCX, MD y TXT.
- RF-08: extrae el texto como Markdown (Docling) y lo normaliza.
- RF-12: clasifica cada fuente en una de las 7 categorías. Usa la categoría de la cabecera YAML
  si es válida; si no, pregunta al LLM (`TaskType.CLASSIFY_SOURCE`) con salida estructurada.

La indexación (embeddings y `documents`/`chunks`) es de T-16; la fragmentación, de T-13.
"""

import hashlib
import io
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from adapters.base import LLMProvider, Message, TaskType
from adapters.errors import ExternalServiceError
from core.rag.documents import (
    CATEGORIES,
    MEMORY_CATEGORY,
    SUPPORTED_EXTENSIONS,
    IngestedDocument,
    IngestionError,
    SourceClassification,
)
from core.rag.prompts import Prompt, load_prompt

INDEX_FILENAMES = frozenset({"README.md"})
DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # evita agotar memoria o CPU con archivos enormes
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")
_H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.MULTILINE)


def normalize_text(text: str) -> str:
    """NFC, saltos de línea `\\n`, sin BOM, caracteres de control ni espacios finales (RF-08)."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("﻿", "")  # PA-213: el BOM (también el que llega de Docling)
    text = _CONTROL_CHARS.sub("", text)
    text = _TRAILING_SPACES.sub("", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    """Separa la cabecera YAML (`---` … `---`) del cuerpo; sin cabecera válida → ({}, raw)."""
    raw = raw.removeprefix("﻿")  # PA-213: un BOM inicial no oculta la cabecera
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, raw
    end = text.find("\n---\n", 4)
    closing = len("\n---\n")
    if end == -1 and text.endswith("\n---"):
        end, closing = len(text) - len("\n---"), len("\n---")
    if end == -1:
        return {}, raw
    try:
        header = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return {}, raw
    if not isinstance(header, dict):
        return {}, raw
    return header, text[end + closing :]


@runtime_checkable
class Extractor(Protocol):
    def extract(self, path: Path) -> str: ...


class DoclingExtractor:
    """Extrae Markdown con Docling (PDF, DOCX, MD); los TXT se leen tal cual."""

    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter

    def extract(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return path.read_text(encoding="utf-8-sig")
        if suffix == ".md":
            _, body = split_front_matter(path.read_text(encoding="utf-8-sig"))
            return self._convert(_markdown_stream(path.name, body))
        return self._convert(path)

    def _convert(self, source: Any) -> str:
        if self._converter is None:
            self._converter = _default_converter()
        result = self._converter.convert(source)
        return str(result.document.export_to_markdown())


class Ingestor:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        extractor: Extractor | None = None,
        prompt: Prompt | None = None,
        max_classify_chars: int = 4000,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> None:
        self._llm = llm
        self._extractor = extractor or DoclingExtractor()
        self._prompt = prompt
        self._max_classify_chars = max_classify_chars
        self._max_bytes = max_bytes

    def ingest(self, path: Path) -> IngestedDocument:
        if not path.is_file():
            raise IngestionError(f"No se encuentra el documento «{path.name}».")
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise IngestionError(
                f"Formato «{suffix or path.name}» no admitido. "
                f"Formatos admitidos: {', '.join(SUPPORTED_EXTENSIONS)}."
            )
        if path.stat().st_size > self._max_bytes:
            raise IngestionError(
                f"«{path.name}» supera el tamaño máximo admitido "
                f"({self._max_bytes // (1024 * 1024)} MB)."
            )
        header = self._header(path)
        try:
            text = normalize_text(self._extractor.extract(path))
        except Exception:  # Docling lanza sus propias excepciones de conversión
            raise IngestionError(f"No se pudo extraer el texto de «{path.name}».") from None
        if not text:
            raise IngestionError(f"El documento «{path.name}» no contiene texto.")

        title = _str(header.get("title")) or _first_heading(text) or path.stem
        category, classified_by = self._classify(path, header, title, text)
        return IngestedDocument(
            id=_str(header.get("id")) or path.stem,
            title=title,
            category=category,
            classified_by=classified_by,
            source_path=path.as_posix(),
            content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            text=text,
            metadata=_metadata(header, path),
        )

    def ingest_dir(self, root: Path) -> list[IngestedDocument]:
        base = root.resolve()
        paths = sorted(
            p
            for p in root.rglob("*")
            if p.is_file()
            and not p.is_symlink()  # no se ingieren archivos de fuera de `root`
            and p.resolve().is_relative_to(base)
            and p.suffix.lower() in SUPPORTED_EXTENSIONS
            and p.name not in INDEX_FILENAMES
        )
        documents = [self.ingest(p) for p in paths]
        _check_unique_ids(documents, base)  # PA-214: un id repetido borraría otro documento
        return documents

    # --- Internos ------------------------------------------------------------------------

    def _header(self, path: Path) -> dict[str, Any]:
        if path.suffix.lower() != ".md":
            return {}
        try:
            header, _ = split_front_matter(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            return {}
        return header

    def _classify(
        self, path: Path, header: dict[str, Any], title: str, text: str
    ) -> tuple[str, str]:
        declared = _str(header.get("category"))
        if declared == MEMORY_CATEGORY:
            raise IngestionError(
                f"«{path.name}» declara la categoría «memoria», reservada al agente."
            )
        if declared in CATEGORIES:
            return declared, "metadata"
        prompt = self._prompt or load_prompt("classify_source")
        messages = [
            Message(role="system", content=prompt.text),
            Message(
                role="user",
                content=(
                    f"<titulo>{title}</titulo>\n\n"
                    f"<documento>\n{text[: self._max_classify_chars]}\n</documento>"
                ),
            ),
        ]
        try:
            result = self._llm.generate_structured(
                messages, SourceClassification, TaskType.CLASSIFY_SOURCE
            )
        except ExternalServiceError:
            raise IngestionError(
                f"No se pudo clasificar «{path.name}» con el LLM. Inténtalo de nuevo más tarde."
            ) from None
        return result.content.category, "llm"


def _default_converter() -> Any:
    # Importación diferida: Docling carga dependencias pesadas.
    from docling.datamodel.base_models import InputFormat
    from docling.document_converter import DocumentConverter

    return DocumentConverter(allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.MD])


def _markdown_stream(name: str, body: str) -> Any:
    from docling.datamodel.base_models import DocumentStream

    return DocumentStream(name=name, stream=io.BytesIO(body.encode("utf-8")))


def _check_unique_ids(documents: list[IngestedDocument], base: Path) -> None:
    """Rechaza dos documentos con el mismo id (PA-214): al indexar, uno borraría al otro."""
    seen: dict[str, IngestedDocument] = {}
    for doc in documents:
        first = seen.setdefault(doc.id, doc)
        if first is not doc:
            raise IngestionError(
                f"«{_relative(first, base)}» y «{_relative(doc, base)}» tienen el mismo id "
                f"«{doc.id[:80]}». Pon un «id:» distinto en la cabecera de uno de ellos o "
                "cámbiale el nombre al archivo."
            )


def _relative(doc: IngestedDocument, base: Path) -> str:
    path = Path(doc.source_path)
    try:
        return path.resolve().relative_to(base).as_posix()
    except ValueError:
        return path.name


def _first_heading(text: str) -> str | None:
    match = _H1.search(text)
    return match.group(1).strip() if match else None


def _str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, list | tuple):
        return ", ".join(str(v) for v in value)
    return str(value).strip()


def _metadata(header: dict[str, Any], path: Path) -> dict[str, str]:
    metadata = {
        key: _str(header[key])
        for key in ("date", "version", "related", "epics")
        if key in header and header[key] is not None
    }
    metadata["source"] = path.as_posix()
    metadata["extension"] = path.suffix.lower()
    return metadata
