"""Contexto de generación de HU: fuentes citables de Jira y del RAG (RF-21, RNF-14).

`StoryContext` reúne lo que recibe el LLM y `render_context` lo serializa como datos
delimitados: cada fuente lleva su referencia citable (clave de Jira o `DOC-NN`), su fecha y su
categoría, para que el modelo pueda resolver contradicciones por fecha (hallazgo de T-17). El
presupuesto de tokens del contexto es de T-18.
"""

import json
from dataclasses import dataclass, field, replace
from typing import Literal

from adapters.base import IssueDetail, RetrievedChunk
from core.text import escape_data as escape_data  # PA-227: reexportada (core/impact, core/qa)
from schemas.user_story import UserStory

SourceKind = Literal["jira", "rag", "memory"]
EXCERPT_CHARS = 200


@dataclass(frozen=True)
class CitableSource:
    """Fuente que el LLM puede citar; `excerpt` es el extracto real que se mostrará (RF-21)."""

    kind: SourceKind
    ref: str
    title: str
    excerpt: str
    content: str
    date: str = ""
    category: str = ""
    section: str = ""
    aliases: tuple[str, ...] = ()  # otras formas válidas de la misma referencia


@dataclass(frozen=True)
class StoryContext:
    origin_kind: Literal["epic", "story", "need"]
    origin_key: str | None = None
    need: str = ""
    jira: list[IssueDetail] = field(default_factory=list)
    rag: list[RetrievedChunk] = field(default_factory=list)
    previous: UserStory | None = None
    feedback: list[str] = field(default_factory=list)

    def sources(self) -> list[CitableSource]:
        """Una fuente por referencia citable, en orden de aparición.

        Los fragmentos del mismo documento se fusionan: se conserva el contenido de todos (sus
        secciones y alias) y los metadatos y el extracto del primero.
        """
        merged: dict[tuple[str, str], CitableSource] = {}
        for source in [*map(_jira_source, self.jira), *map(_rag_source, self.rag)]:
            key = (source.kind, source.ref)
            first = merged.get(key)
            if first is None:
                merged[key] = source
            elif source.content not in first.content:
                merged[key] = _merge(first, source)
            else:
                merged[key] = replace(first, aliases=_union(first.aliases, source.aliases))
        return list(merged.values())


def _merge(first: CitableSource, other: CitableSource) -> CitableSource:
    sections = [s for s in dict.fromkeys((*first.section.split(" | "), other.section)) if s]
    return replace(
        first,
        content=f"{first.content}\n[…]\n{other.content}",
        section=" | ".join(sections),
        aliases=_union(first.aliases, other.aliases),
    )


def _union(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*a, *b)))


def render_context(ctx: StoryContext) -> str:
    """Mensaje de usuario con el contexto como datos delimitados."""
    parts = [f'<origen tipo="{ctx.origin_kind}" clave="{escape_data(ctx.origin_key or "")}"/>']
    if ctx.need:
        parts.append(f"<necesidad>\n{escape_data(ctx.need)}\n</necesidad>")
    if ctx.previous is not None:
        story_json = json.dumps(ctx.previous.model_dump(mode="json"), ensure_ascii=False)
        parts.append(f"<hu_actual>\n{escape_data(story_json)}\n</hu_actual>")
    if ctx.feedback:
        items = "\n".join(f"- {escape_data(item)}" for item in ctx.feedback)
        parts.append(f"<feedback>\n{items}\n</feedback>")
    blocks = [_render_source(s) for s in ctx.sources()]
    parts.append("<contexto>\n" + "\n".join(blocks) + "\n</contexto>")
    return "\n\n".join(parts)


def _render_source(source: CitableSource) -> str:
    attrs = {
        "ref": source.ref,
        "tipo": source.kind,
        "titulo": source.title,
        "fecha": source.date,
        "categoria": source.category,
        "seccion": source.section,
    }
    rendered = " ".join(f'{name}="{escape_data(value)}"' for name, value in attrs.items() if value)
    return f"<fuente {rendered}>\n{escape_data(source.content)}\n</fuente>"


def _jira_source(issue: IssueDetail) -> CitableSource:
    # PA-281: la primera clave que lee el modelo es la que debe citar (la de la fuente); la épica
    # o el padre va al final, como relación. Si iba al principio, citaba la del padre.
    lines = [f"Clave: {issue.key} · {issue.issue_type} · {issue.status}"]
    if issue.description_text:
        lines.append(issue.description_text)
    lines += [f"Vínculo: {link.link_type} {link.key}" for link in issue.links]
    lines += [f"Comentario: {comment}" for comment in issue.comments]
    if issue.parent_key:
        lines.append(f"Pertenece a la épica o padre {issue.parent_key}")
    return CitableSource(
        kind="jira",
        ref=issue.key,
        title=issue.summary,
        excerpt=_excerpt(f"{issue.summary}. {issue.description_text}".strip(". ")),
        content="\n".join(lines),
    )


def _rag_source(retrieved: RetrievedChunk) -> CitableSource:
    chunk, metadata = retrieved.chunk, retrieved.chunk.metadata
    doc_id = metadata.get("doc_id") or retrieved.source.ref
    aliases = tuple({retrieved.source.ref, chunk.document_id} - {doc_id})
    return CitableSource(
        kind=retrieved.source.kind,
        ref=doc_id,
        title=metadata.get("title", ""),
        excerpt=retrieved.source.excerpt or _excerpt(chunk.content),
        content=chunk.content,
        date=metadata.get("date", ""),
        category=metadata.get("category", ""),
        section=chunk.section or "",
        aliases=aliases,
    )


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_CHARS else text[: EXCERPT_CHARS - 1] + "…"
