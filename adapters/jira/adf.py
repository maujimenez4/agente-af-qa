"""Atlassian Document Format (ADF) de Jira (SPEC-00 §8).

`adf_to_text` convierte descripciones y comentarios a texto plano legible para el LLM (RF-03).
`markdown_to_adf` (escritura) se implementa en T-27.
"""

import re
from datetime import UTC, datetime
from typing import Any

Node = dict[str, Any]

_INDENT = "  "
_BLANK_LINES = re.compile(r"\n{3,}")


def adf_to_text(node: Node | None) -> str:
    if not node:
        return ""
    text = _block(node)
    return _BLANK_LINES.sub("\n\n", text).rstrip()


def _children(node: Node) -> list[Node]:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _attrs(node: Node) -> dict[str, Any]:
    attrs = node.get("attrs")
    return attrs if isinstance(attrs, dict) else {}


def _blocks(nodes: list[Node]) -> str:
    return "\n\n".join(part for part in (_block(n) for n in nodes) if part)


def _block(node: Node) -> str:
    kind = node.get("type")
    match kind:
        case "doc" | "panel" | "expand" | "nestedExpand":
            return _blocks(_children(node))
        case "paragraph":
            return _inline(_children(node))
        case "heading":
            level = int(_attrs(node).get("level", 1))
            return f"{'#' * max(1, min(level, 6))} {_inline(_children(node))}"
        case "bulletList" | "orderedList":
            return "\n".join(_list_lines(node, depth=0))
        case "codeBlock":
            return f"```\n{_inline(_children(node))}\n```"
        case "blockquote":
            inner = _blocks(_children(node))
            return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        case "rule":
            return "---"
        case "table":
            return "\n".join(_table_row(row) for row in _children(node))
        case "mediaSingle" | "mediaGroup" | "media":
            return "[adjunto]"
        case _:
            children = _children(node)
            if not children:
                return _inline_node(node)
            if all(_is_inline(c) for c in children):
                return _inline(children)
            return _blocks(children)


def _list_lines(node: Node, depth: int) -> list[str]:
    ordered = node.get("type") == "orderedList"
    number = int(_attrs(node).get("order", 1)) if ordered else 0
    lines: list[str] = []
    for item in _children(node):
        marker = f"{number}. " if ordered else "- "
        number += 1
        head: list[str] = []
        nested: list[str] = []
        for child in _children(item):
            if child.get("type") in ("bulletList", "orderedList"):
                nested.extend(_list_lines(child, depth + 1))
            else:
                head.append(_block(child))
        lines.append(f"{_INDENT * depth}{marker}{' '.join(p for p in head if p)}")
        lines.extend(nested)
    return lines


def _table_row(row: Node) -> str:
    cells = [_blocks(_children(cell)).replace("\n", " ") for cell in _children(row)]
    return "| " + " | ".join(cells) + " |"


_INLINE_TYPES = {
    "text",
    "hardBreak",
    "mention",
    "emoji",
    "inlineCard",
    "status",
    "date",
    "placeholder",
}


def _is_inline(node: Node) -> bool:
    return node.get("type") in _INLINE_TYPES


def _inline(nodes: list[Node]) -> str:
    return "".join(_inline_node(n) if _is_inline(n) else _block(n) for n in nodes)


def _inline_node(node: Node) -> str:
    attrs = _attrs(node)
    match node.get("type"):
        case "text":
            return str(node.get("text", ""))
        case "hardBreak":
            return "\n"
        case "mention" | "status":
            return str(attrs.get("text", ""))
        case "emoji":
            return str(attrs.get("text") or attrs.get("shortName", ""))
        case "inlineCard" | "blockCard":
            return str(attrs.get("url", ""))
        case "date":
            return _date(attrs.get("timestamp"))
        case _:
            return ""


def _date(timestamp: Any) -> str:
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000, tz=UTC).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
