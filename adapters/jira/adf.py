"""Atlassian Document Format (ADF) de Jira (SPEC-00 §8).

`adf_to_text` convierte descripciones y comentarios a texto plano legible para el LLM (RF-03).
`markdown_to_adf` (escritura, T-27) convierte el Markdown de los comentarios a ADF: títulos,
párrafos, listas, tablas, negrita y bloques de código. El contenido llega de una HU editada a
mano o generada por el LLM, así que no es fiable (PA-49): el HTML queda como texto, los enlaces
solo admiten `http(s)`, `\\|` es una barra literal dentro de una celda y se eliminan los
caracteres de control. Los constructores (`doc`, `text`, `paragraph`…) generan ADF a partir de
texto literal, sin interpretar Markdown.
"""

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

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


# --- Escritura: constructores de ADF a partir de texto literal (T-27) ----------------------

MAX_MARKDOWN_CHARS = 100_000  # por encima se trunca: Jira rechaza documentos enormes
MAX_URL_CHARS = 2_000
MAX_TABLE_COLUMNS = 50  # PA-230: Jira tampoco admite tablas más anchas de forma útil
MAX_TABLE_CELLS = 5_000  # PA-230: por encima, la tabla se publica como texto literal
# C0 (salvo `\t` y `\n`), C1, control bidireccional y espacios de anchura cero (orden visual
# engañoso); se conservan U+200C/U+200D, que usan los emojis y algunas escrituras.
_CONTROL = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f"  # C0 y C1
    r"\u061c\u200b\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]"  # bidi (LRM/RLM/ALM: PA-186)
)


def clean_text(value: str) -> str:
    """Normaliza los saltos de línea y quita los caracteres de control (salvo `\t` y `\n`)."""
    return _CONTROL.sub("", value.replace("\r\n", "\n").replace("\r", "\n"))


def doc(content: list[Node]) -> Node:
    return {"type": "doc", "version": 1, "content": content}


def text(value: str, *, strong: bool = False) -> list[Node]:
    """Texto literal (sin interpretar Markdown); cada salto de línea es un `hardBreak`."""
    marks = ("strong",) if strong else ()
    nodes: list[Node] = []
    for i, line in enumerate(clean_text(value).split("\n")):
        if i:
            nodes.append({"type": "hardBreak"})
        _append_text(nodes, line, marks)
    return nodes


def paragraph(content: list[Node]) -> Node:
    return {"type": "paragraph", "content": content} if content else {"type": "paragraph"}


def heading(value: str, level: int) -> Node:
    return {"type": "heading", "attrs": {"level": level}, "content": text(value)}


def bullet_list(items: list[list[Node]]) -> Node:
    return {
        "type": "bulletList",
        "content": [{"type": "listItem", "content": [paragraph(item)]} for item in items],
    }


def table(header: list[str], rows: list[list[str]]) -> Node:
    """Tabla con cabecera; cada celda, texto literal."""

    def row(cells: list[str], cell_type: str) -> Node:
        return {
            "type": "tableRow",
            "content": [{"type": cell_type, "content": [paragraph(text(c))]} for c in cells],
        }

    return {
        "type": "table",
        "content": [row(header, "tableHeader"), *(row(cells, "tableCell") for cells in rows)],
    }


def code_block(value: str, language: str = "") -> Node:
    node: Node = {"type": "codeBlock"}
    if language:
        node["attrs"] = {"language": language}
    value = clean_text(value)
    if value:
        node["content"] = [{"type": "text", "text": value}]
    return node


def _append_text(nodes: list[Node], value: str, marks: tuple[str, ...]) -> None:
    if not value:
        return  # ADF no admite nodos de texto vacíos
    node: Node = {"type": "text", "text": value}
    if marks:
        node["marks"] = [{"type": mark} for mark in marks]
    nodes.append(node)


# --- Escritura: Markdown → ADF (T-27, SPEC-00 §8, PA-49) -----------------------------------

# PA-230: sobre la línea ya recortada (`_fence`) y con un solo `\s*`: el patrón anterior,
# con `\s*` a ambos lados de un grupo que puede ser vacío, era cuadrático (~54 s con 100 000
# espacios).
_FENCE = re.compile(r"^```\s*([A-Za-z0-9_+-]{0,20})$")
# PA-143: sin `\s*$` tras un grupo perezoso (backtracking cuadrático con miles de espacios);
# los espacios del título se quitan con `.strip()`.
_HEADING = re.compile(r"^(#{1,6})\s(.*)$")
_LIST_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])\s+(.*)$")
_RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
# Celda del separador de tabla (`---`, `:--`, `-:`); se valida celda a celda, sin `\s*`
# contiguos que den backtracking cuadrático con texto no fiable (PA-187).
_SEPARATOR_CELL = re.compile(r":?-+:?")
# PA-230: la etiqueta no admite `[`: así, con miles de `[`, cada intento falla al momento en vez
# de recorrer hasta 500 caracteres.
_LINK = re.compile(rf"\[([^\[\]\n]{{1,500}})\]\(([^()\s]{{1,{MAX_URL_CHARS}}})\)")
_ESCAPABLE = frozenset("\\`*_[]()#+-.!|>")
_TAB_WIDTH = 4


def markdown_to_adf(md: str) -> Node:
    """Convierte Markdown (subconjunto de SPEC-00 §8) en un documento ADF, sin HTML."""
    lines = clean_text(md[:MAX_MARKDOWN_CHARS]).expandtabs(_TAB_WIDTH).split("\n")
    return doc(_parse_blocks(lines))


def _parse_blocks(lines: list[str]) -> list[Node]:
    blocks: list[Node] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif fence := _fence(line):
            body: list[str] = []
            i += 1
            while i < len(lines) and not _fence(lines[i]):
                body.append(lines[i])
                i += 1
            blocks.append(code_block("\n".join(body), fence.group(1)))
            i += 1  # cierre del bloque (o fin del texto si falta)
        elif match := _HEADING.match(line):
            level = len(match.group(1))
            content = _md_inline(match.group(2).strip())
            blocks.append({"type": "heading", "attrs": {"level": level}, "content": content})
            i += 1
        elif _RULE.match(line):
            blocks.append({"type": "rule"})
            i += 1
        elif _is_table_line(line):
            start = i
            while i < len(lines) and _is_table_line(lines[i]):
                i += 1
            blocks.append(_table(lines[start:i]))
        elif _LIST_ITEM.match(line):
            start = i
            i += 1
            while i < len(lines) and _continues_list(lines[i]):
                i += 1
            blocks.extend(_lists(lines[start:i]))
        else:
            start = i
            while i < len(lines) and lines[i].strip() and not _starts_block(lines[i]):
                i += 1
            joined = "\n".join(part.strip() for part in lines[start:i])
            blocks.append(paragraph(_md_inline(joined)))
    return blocks


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _fence(line: str) -> re.Match[str] | None:
    """Valla de código (```lenguaje) en la línea, sin espacios en los extremos (PA-230)."""
    return _FENCE.match(line.strip())


def _starts_block(line: str) -> bool:
    return bool(
        _fence(line)
        or _HEADING.match(line)
        or _RULE.match(line)
        or _is_table_line(line)
        or _LIST_ITEM.match(line)
    )


def _continues_list(line: str) -> bool:
    """Un elemento nuevo o una línea sangrada que continúa el anterior."""
    if _LIST_ITEM.match(line):
        return True
    return bool(line.strip()) and line.startswith("  ") and not _starts_block(line)


# --- Listas ----------------------------------------------------------------------------------

_Item = tuple[int, bool, str]  # (sangría, ordenada, texto)


def _lists(lines: list[str]) -> list[Node]:
    items: list[_Item] = []
    for line in lines:
        if match := _LIST_ITEM.match(line):
            indent, marker, content = match.groups()
            items.append((len(indent), marker[0].isdigit(), content))
        elif items:
            indent, ordered, content = items[-1]
            items[-1] = (indent, ordered, f"{content}\n{line.strip()}")
    nodes: list[Node] = []
    pos = 0
    while pos < len(items):  # un elemento menos sangrado que el primero abre otra lista
        level, pos = _list_level(items, pos)
        nodes += level
    return nodes


def _list_level(items: list[_Item], pos: int) -> tuple[list[Node], int]:
    """Agrupa los elementos de una sangría; los más sangrados se anidan en el anterior."""
    nodes: list[Node] = []
    base = items[pos][0]
    current: Node | None = None
    while pos < len(items):
        indent, ordered, content = items[pos]
        if indent < base:
            break
        if indent > base and current is not None:
            nested, pos = _list_level(items, pos)
            current["content"][-1]["content"].extend(nested)
            continue
        kind = "orderedList" if ordered else "bulletList"
        if current is None or current["type"] != kind:
            current = {"type": kind, "content": []}
            nodes.append(current)
        current["content"].append({"type": "listItem", "content": [paragraph(_md_inline(content))]})
        pos += 1
    return nodes, pos


# --- Tablas ----------------------------------------------------------------------------------


def _table(lines: list[str]) -> Node:
    has_header = len(lines) > 1 and _is_table_separator(lines[1])
    # Solo la segunda línea puede ser el separador; `| - | - |` más abajo es una fila de datos.
    rows = [
        _cap_columns(_split_cells(line))
        for n, line in enumerate(lines)
        if not (has_header and n == 1)
    ]
    width = max(len(row) for row in rows)
    # PA-230: cada fila se rellena hasta el ancho máximo; sin topes, una fila de 50 000 «|»
    # seguida de miles de filas creaba ancho × filas celdas (cuadrático en tiempo y memoria).
    # Una tabla demasiado grande se publica como texto literal, sin perder contenido.
    if width * len(rows) > MAX_TABLE_CELLS:
        return code_block("\n".join(lines))
    content: list[Node] = []
    for r, row in enumerate(rows):
        cell_type = "tableHeader" if has_header and r == 0 else "tableCell"
        cells = row + [""] * (width - len(row))
        content.append(
            {
                "type": "tableRow",
                "content": [
                    {"type": cell_type, "content": [paragraph(_md_inline(cell))]} for cell in cells
                ],
            }
        )
    return {"type": "table", "content": content}


def _cap_columns(cells: list[str]) -> list[str]:
    """Como mucho `MAX_TABLE_COLUMNS` celdas: las que sobran se unen a la última (PA-230)."""
    if len(cells) <= MAX_TABLE_COLUMNS:
        return cells
    keep = MAX_TABLE_COLUMNS - 1
    return [*cells[:keep], " | ".join(cells[keep:])]


def _is_table_separator(line: str) -> bool:
    """`| --- | :-: |`: cada celda solo con guiones y dos puntos. Tiempo lineal (PA-187)."""
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    cells = row.split("|")
    return bool(cells) and all(_SEPARATOR_CELL.fullmatch(cell.strip()) for cell in cells)


def _split_cells(line: str) -> list[str]:
    """Separa las celdas por las `|` sin escapar; `\\|` es una barra literal (PA-49)."""
    row = line.strip()
    cells: list[str] = []
    buffer: list[str] = []
    i = 0
    while i < len(row):
        if row.startswith("\\|", i):
            buffer.append("\\|")  # el escape lo resuelve `_inline`
            i += 2
            continue
        if row[i] == "|":
            cells.append("".join(buffer))
            buffer = []
        else:
            buffer.append(row[i])
        i += 1
    cells.append("".join(buffer))
    # Las barras de los extremos delimitan la fila: no abren celdas.
    cells = cells[1:]
    if cells and not cells[-1].strip():
        cells = cells[:-1]
    return [cell.strip() for cell in cells] or [""]


# --- En línea --------------------------------------------------------------------------------


def _md_inline(value: str, marks: tuple[str, ...] = ()) -> list[Node]:
    """Negrita `**…**`, código `` `…` ``, enlaces `[texto](http…)` y escapes `\\x`."""
    nodes: list[Node] = []
    buffer: list[str] = []

    def flush() -> None:
        _append_text(nodes, "".join(buffer), marks)
        buffer.clear()

    i = 0
    while i < len(value):
        char = value[i]
        if char == "\\" and i + 1 < len(value) and value[i + 1] in _ESCAPABLE:
            buffer.append(value[i + 1])
            i += 2
        elif char == "\n":
            flush()
            nodes.append({"type": "hardBreak"})
            i += 1
        elif char == "`" and (end := value.find("`", i + 1)) > i + 1:
            flush()
            _append_text(nodes, value[i + 1 : end], ("code",))  # ADF: `code` solo con `link`
            i = end + 1
        elif (
            value.startswith("**", i)
            and "strong" not in marks
            and (end := value.find("**", i + 2)) > i + 2
        ):
            flush()
            nodes.extend(_md_inline(value[i + 2 : end], (*marks, "strong")))
            i = end + 2
        elif char == "[" and (link := _LINK.match(value, i)):
            flush()
            label, url = link.groups()
            if _safe_url(url):
                nodes.extend(_with_link(_md_inline(label, marks), url))
            else:
                _append_text(nodes, link.group(0), marks)  # PA-49: solo http(s)
            i = link.end()
        else:
            buffer.append(char)
            i += 1
    flush()
    return nodes


def _with_link(nodes: list[Node], url: str) -> list[Node]:
    for node in nodes:
        if node["type"] == "text":
            node.setdefault("marks", []).append({"type": "link", "attrs": {"href": url}})
    return nodes


def _safe_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc)
