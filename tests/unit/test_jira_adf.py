"""Conversión de ADF a texto plano para el LLM (T-11, RF-03; SPEC-00 §8 «ADF»).

Escritura (T-27): `markdown_to_adf` (SPEC-00 §8, PA-49) e ida y vuelta con `adf_to_text`.

Datos 100 % sintéticos del dominio ficticio de la Biblioteca de Villaficticia.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from adapters.jira.adf import MAX_MARKDOWN_CHARS, adf_to_text, markdown_to_adf, table
from core.graph.nodes import _diff_comment_md
from schemas.impact import ImpactAnalysis, StoryDiff

Node = dict[str, Any]


# --- Constructores de nodos ADF --------------------------------------------------------------


def text(value: str, marks: list[Node] | None = None) -> Node:
    node: Node = {"type": "text", "text": value}
    if marks:
        node["marks"] = marks
    return node


def para(*children: Node) -> Node:
    return {"type": "paragraph", "content": list(children)}


def doc(*blocks: Node) -> Node:
    return {"type": "doc", "version": 1, "content": list(blocks)}


def list_item(*blocks: Node) -> Node:
    return {"type": "listItem", "content": list(blocks)}


def bullet_list(*items: Node) -> Node:
    return {"type": "bulletList", "content": list(items)}


def ordered_list(*items: Node, order: int | None = None) -> Node:
    node: Node = {"type": "orderedList", "content": list(items)}
    if order is not None:
        node["attrs"] = {"order": order}
    return node


def cell(value: str, header: bool = False) -> Node:
    return {"type": "tableHeader" if header else "tableCell", "content": [para(text(value))]}


def row(*cells: Node) -> Node:
    return {"type": "tableRow", "content": list(cells)}


# --- Casos vacíos ----------------------------------------------------------------------------


@pytest.mark.parametrize("node", [None, {}])
def test_adf_to_text_returns_empty_when_node_is_none_or_empty(node: Node | None) -> None:
    """RF-03: None o {} → cadena vacía."""
    assert adf_to_text(node) == ""


def test_adf_to_text_returns_empty_when_doc_has_no_content() -> None:
    """RF-03: un doc sin bloques → cadena vacía."""
    assert adf_to_text(doc()) == ""


# --- Bloques básicos -------------------------------------------------------------------------


def test_adf_to_text_returns_paragraph_text_when_single_paragraph() -> None:
    """RF-03: paragraph → concatenación de sus textos inline."""
    node = doc(para(text("Como persona socia "), text("quiero renovar un préstamo.")))
    assert adf_to_text(node) == "Como persona socia quiero renovar un préstamo."


def test_adf_to_text_accepts_paragraph_as_root() -> None:
    """RF-03: también convierte un nodo que no es doc (p. ej. un paragraph suelto)."""
    assert adf_to_text(para(text("Plazo de 21 días."))) == "Plazo de 21 días."


def test_adf_to_text_joins_blocks_with_blank_line_when_doc_has_several_blocks() -> None:
    """RF-03: los bloques de un doc se unen con una línea en blanco."""
    node = doc(para(text("Primer párrafo.")), para(text("Segundo párrafo.")))
    assert adf_to_text(node) == "Primer párrafo.\n\nSegundo párrafo."


def test_adf_to_text_ignores_marks_when_text_is_bold_or_link() -> None:
    """RF-03: las marcas (negrita, enlaces…) se ignoran y queda solo el texto."""
    node = doc(
        para(
            text("Máximo ", [{"type": "strong"}]),
            text(
                "2 renovaciones",
                [{"type": "link", "attrs": {"href": "https://villaficticia.example/reglamento"}}],
            ),
        )
    )
    assert adf_to_text(node) == "Máximo 2 renovaciones"


def test_adf_to_text_converts_hard_break_to_newline() -> None:
    """RF-03: hardBreak → salto de línea dentro del párrafo."""
    node = doc(para(text("Línea uno"), {"type": "hardBreak"}, text("Línea dos")))
    assert adf_to_text(node) == "Línea uno\nLínea dos"


@pytest.mark.parametrize(("level", "prefix"), [(1, "#"), (2, "##"), (3, "###"), (6, "######")])
def test_adf_to_text_prefixes_hashes_when_heading(level: int, prefix: str) -> None:
    """RF-03: heading de nivel N → N almohadillas, un espacio y el texto."""
    node = doc({"type": "heading", "attrs": {"level": level}, "content": [text("Alcance")]})
    assert adf_to_text(node) == f"{prefix} Alcance"


# --- Listas ----------------------------------------------------------------------------------


def test_adf_to_text_prefixes_dash_when_bullet_list() -> None:
    """RF-03: bulletList → cada listItem en su línea con «- »."""
    node = doc(bullet_list(list_item(para(text("Reservar"))), list_item(para(text("Renovar")))))
    assert adf_to_text(node) == "- Reservar\n- Renovar"


def test_adf_to_text_numbers_items_when_ordered_list() -> None:
    """RF-03: orderedList sin attrs.order → «1. », «2. »…"""
    node = doc(
        ordered_list(
            list_item(para(text("Buscar el libro"))),
            list_item(para(text("Pulsar «Reservar»"))),
            list_item(para(text("Confirmar"))),
        )
    )
    assert adf_to_text(node) == "1. Buscar el libro\n2. Pulsar «Reservar»\n3. Confirmar"


def test_adf_to_text_starts_numbering_at_order_when_attr_present() -> None:
    """RF-03: orderedList con attrs.order empieza en ese número."""
    node = doc(ordered_list(list_item(para(text("Uno"))), list_item(para(text("Dos"))), order=4))
    assert adf_to_text(node) == "4. Uno\n5. Dos"


def test_adf_to_text_indents_two_spaces_per_level_when_nested_lists() -> None:
    """RF-03: listas anidadas dentro de un listItem se indentan 2 espacios por nivel."""
    node = doc(
        bullet_list(
            list_item(
                para(text("Préstamos")),
                bullet_list(
                    list_item(
                        para(text("Renovación")),
                        ordered_list(list_item(para(text("Comprobar reservas")))),
                    )
                ),
            ),
            list_item(para(text("Reservas"))),
        )
    )
    assert adf_to_text(node) == (
        "- Préstamos\n  - Renovación\n    1. Comprobar reservas\n- Reservas"
    )


# --- Otros bloques ---------------------------------------------------------------------------


def test_adf_to_text_wraps_in_fences_when_code_block() -> None:
    """RF-03: codeBlock → texto entre vallas ```."""
    node = doc(
        {
            "type": "codeBlock",
            "attrs": {"language": "json"},
            "content": [text('{"plazo_dias": 21}')],
        }
    )
    assert adf_to_text(node) == '```\n{"plazo_dias": 21}\n```'


def test_adf_to_text_prefixes_each_line_when_blockquote() -> None:
    """RF-03: blockquote → cada línea prefijada con «> »."""
    node = doc(
        {
            "type": "blockquote",
            "content": [
                para(text("Artículo 7 (ficticio)"), {"type": "hardBreak"}, text("21 días"))
            ],
        }
    )
    assert adf_to_text(node) == "> Artículo 7 (ficticio)\n> 21 días"


def test_adf_to_text_renders_dashes_when_rule() -> None:
    """RF-03: rule → «---» como bloque propio."""
    node = doc(para(text("Antes")), {"type": "rule"}, para(text("Después")))
    assert adf_to_text(node) == "Antes\n\n---\n\nDespués"


def test_adf_to_text_renders_content_when_panel() -> None:
    """RF-03: panel → solo su contenido."""
    node = doc(
        {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [para(text("Datos ficticios de prueba."))],
        }
    )
    assert adf_to_text(node) == "Datos ficticios de prueba."


def test_adf_to_text_renders_pipe_rows_when_table() -> None:
    """RF-03: table → una línea «| c1 | c2 |» por tableRow (tableHeader y tableCell)."""
    node = doc(
        {
            "type": "table",
            "content": [
                row(cell("Regla", header=True), cell("Valor", header=True)),
                row(cell("Plazo de préstamo"), cell("21 días")),
                row(cell("Renovaciones"), cell("2")),
            ],
        }
    )
    assert adf_to_text(node) == (
        "| Regla | Valor |\n| Plazo de préstamo | 21 días |\n| Renovaciones | 2 |"
    )


# --- Nodos inline ----------------------------------------------------------------------------


def test_adf_to_text_uses_attrs_text_when_mention() -> None:
    """RF-03: mention → attrs.text."""
    node = doc(
        para(
            text("Revisar con "),
            {"type": "mention", "attrs": {"id": "id-ficticio-1", "text": "@Persona Ficticia"}},
        )
    )
    assert adf_to_text(node) == "Revisar con @Persona Ficticia"


def test_adf_to_text_uses_attrs_text_when_emoji_has_text() -> None:
    """RF-03: emoji → attrs.text si existe."""
    node = doc(para({"type": "emoji", "attrs": {"shortName": ":white_check_mark:", "text": "✅"}}))
    assert adf_to_text(node) == "✅"


def test_adf_to_text_falls_back_to_short_name_when_emoji_has_no_text() -> None:
    """RF-03: emoji sin attrs.text → attrs.shortName."""
    node = doc(para({"type": "emoji", "attrs": {"shortName": ":books:"}}))
    assert adf_to_text(node) == ":books:"


def test_adf_to_text_uses_url_when_inline_card() -> None:
    """RF-03: inlineCard → attrs.url."""
    url = "https://villaficticia.example/browse/DEMO-2"
    node = doc(para(text("Ver "), {"type": "inlineCard", "attrs": {"url": url}}))
    assert adf_to_text(node) == f"Ver {url}"


def test_adf_to_text_uses_attrs_text_when_status() -> None:
    """RF-03: status → attrs.text."""
    node = doc(para({"type": "status", "attrs": {"text": "EN REVISIÓN", "color": "blue"}}))
    assert adf_to_text(node) == "EN REVISIÓN"


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("1767225600000", "2026-01-01"),  # 2026-01-01T00:00:00Z
        ("1767225599000", "2025-12-31"),  # un segundo antes: límite en UTC, no en hora local
        ("1784116800000", "2026-07-15"),  # 2026-07-15T12:00:00Z
    ],
)
def test_adf_to_text_formats_utc_date_when_date_node(timestamp: str, expected: str) -> None:
    """RF-03: date → attrs.timestamp (ms) como «YYYY-MM-DD» en UTC."""
    node = doc(para(text("Vence el "), {"type": "date", "attrs": {"timestamp": timestamp}}))
    assert adf_to_text(node) == f"Vence el {expected}"


# --- Adjuntos --------------------------------------------------------------------------------


def test_adf_to_text_renders_placeholder_when_media_single() -> None:
    """RF-03: mediaSingle (con su media) → «[adjunto]» una sola vez."""
    node = doc(
        {
            "type": "mediaSingle",
            "attrs": {"layout": "center"},
            "content": [
                {"type": "media", "attrs": {"id": "media-ficticio", "type": "file"}},
            ],
        }
    )
    assert adf_to_text(node) == "[adjunto]"


def test_adf_to_text_renders_placeholder_when_media_group() -> None:
    """RF-03: mediaGroup → «[adjunto]»."""
    node = doc(
        {
            "type": "mediaGroup",
            "content": [
                {"type": "media", "attrs": {"id": "media-ficticio-1", "type": "file"}},
                {"type": "media", "attrs": {"id": "media-ficticio-2", "type": "file"}},
            ],
        }
    )
    assert adf_to_text(node) == "[adjunto]"


def test_adf_to_text_renders_placeholder_when_bare_media() -> None:
    """RF-03: media suelto → «[adjunto]»."""
    assert adf_to_text({"type": "media", "attrs": {"id": "media-ficticio"}}) == "[adjunto]"


# --- Nodos desconocidos y normalización -------------------------------------------------------


def test_adf_to_text_traverses_content_when_unknown_node_has_content() -> None:
    """RF-03: nodo desconocido con content → se recorre su contenido."""
    node = doc(
        {
            "type": "expand",
            "attrs": {"title": "Detalle"},
            "content": [para(text("Contenido desplegable ficticio."))],
        }
    )
    assert adf_to_text(node) == "Contenido desplegable ficticio."


def test_adf_to_text_returns_empty_when_unknown_node_has_no_content() -> None:
    """RF-03: nodo desconocido sin content → cadena vacía."""
    assert adf_to_text({"type": "extension", "attrs": {"extensionKey": "ficticia"}}) == ""


def test_adf_to_text_ignores_unknown_inline_without_content() -> None:
    """RF-03: un inline desconocido sin content no aporta texto."""
    node = doc(para(text("Antes"), {"type": "placeholder", "attrs": {}}, text(" después")))
    assert adf_to_text(node) == "Antes después"


def test_adf_to_text_collapses_blank_lines_when_empty_blocks() -> None:
    """RF-03: nunca hay 3 o más saltos de línea seguidos (bloques vacíos o desconocidos)."""
    node = doc(
        para(text("Inicio")),
        para(),
        {"type": "extension", "attrs": {}},
        para(),
        para(text("Fin")),
    )
    result = adf_to_text(node)
    assert "\n\n\n" not in result
    assert result == "Inicio\n\nFin"


def test_adf_to_text_strips_trailing_whitespace_at_end() -> None:
    """RF-03: el resultado final no termina en espacios ni saltos de línea."""
    node = doc(para(text("Texto final   ")), para(), para())
    assert adf_to_text(node) == "Texto final"


# --- Documento completo ----------------------------------------------------------------------


def test_adf_to_text_renders_all_parts_when_realistic_document() -> None:
    """RF-03: un documento realista sintético conserva todo su contenido legible."""
    node = doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Descripción")]},
        para(
            text("Como "),
            text("persona socia", [{"type": "strong"}]),
            text(" quiero renovar un préstamo antes del "),
            {"type": "date", "attrs": {"timestamp": "1767225600000"}},
            text("."),
        ),
        {"type": "heading", "attrs": {"level": 3}, "content": [text("Reglas")]},
        bullet_list(
            list_item(para(text("Máximo 2 renovaciones."))),
            list_item(para(text("No si hay reservas pendientes."))),
        ),
        ordered_list(list_item(para(text("Abrir el préstamo"))), list_item(para(text("Renovar")))),
        {
            "type": "table",
            "content": [
                row(cell("Campo", header=True), cell("Valor", header=True)),
                row(cell("Plazo"), cell("21 días")),
            ],
        },
        {
            "type": "panel",
            "attrs": {"panelType": "warning"},
            "content": [
                para(text("Consultar con "), {"type": "mention", "attrs": {"text": "@Sala"}})
            ],
        },
        {"type": "codeBlock", "content": [text("GET /prestamos/ficticio")]},
        {"type": "rule"},
        {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"id": "m-ficticio"}}]},
        para(
            text("Estado: "),
            {"type": "status", "attrs": {"text": "BORRADOR"}},
            text(" "),
            {"type": "inlineCard", "attrs": {"url": "https://villaficticia.example/browse/DEMO-1"}},
        ),
    )
    result = adf_to_text(node)

    expected_fragments = [
        "## Descripción",
        "Como persona socia quiero renovar un préstamo antes del 2026-01-01.",
        "### Reglas",
        "- Máximo 2 renovaciones.\n- No si hay reservas pendientes.",
        "1. Abrir el préstamo\n2. Renovar",
        "| Campo | Valor |\n| Plazo | 21 días |",
        "Consultar con @Sala",
        "```\nGET /prestamos/ficticio\n```",
        "---",
        "[adjunto]",
        "Estado: BORRADOR https://villaficticia.example/browse/DEMO-1",
    ]
    for fragment in expected_fragments:
        assert fragment in result, fragment
    assert "\n\n\n" not in result
    assert result == result.rstrip()
    assert result.startswith("## Descripción")
    assert result.index("### Reglas") < result.index("| Campo | Valor |")


# =============================================================================================
# Escritura: Markdown → ADF (T-27, SPEC-00 §8, PA-49)
# =============================================================================================


def walk(node: Node) -> Iterator[Node]:
    """Todos los nodos del árbol ADF, en profundidad."""
    yield node
    for child in node.get("content") or []:
        yield from walk(child)


def blocks_of(md: str) -> list[Node]:
    return markdown_to_adf(md)["content"]


def text_nodes(node: Node) -> list[Node]:
    return [n for n in walk(node) if n.get("type") == "text"]


def mark_types(node: Node) -> list[str]:
    return [mark["type"] for mark in node.get("marks", [])]


def joined_text(node: Node) -> str:
    return "".join(n["text"] for n in text_nodes(node))


def table_rows(table: Node) -> list[list[str]]:
    return [[joined_text(c) for c in r["content"]] for r in table["content"]]


def assert_valid_doc(document: Node) -> None:
    """Documento ADF raíz y sin nodos de texto vacíos (Jira los rechaza)."""
    assert document["type"] == "doc"
    assert document["version"] == 1
    assert isinstance(document["content"], list)
    for node in text_nodes(document):
        assert node["text"], node


# --- Documento raíz --------------------------------------------------------------------------


@pytest.mark.parametrize("md", ["", "   \n\n  ", "Texto ficticio"])
def test_markdown_to_adf_returns_doc_version_1_when_any_input(md: str) -> None:
    """§8: la salida es siempre un documento ADF `doc` con `version: 1`."""
    assert_valid_doc(markdown_to_adf(md))


def test_markdown_to_adf_returns_empty_content_when_only_blank_lines() -> None:
    """§8: las líneas en blanco no generan bloques."""
    assert blocks_of("\n\n   \n") == []


# --- Títulos y párrafos ----------------------------------------------------------------------


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_markdown_to_adf_builds_heading_when_hashes_1_to_6(level: int) -> None:
    """§8: `#`…`######` son títulos de nivel 1–6."""
    [block] = blocks_of(f"{'#' * level} Plazo de préstamo")
    assert block["type"] == "heading"
    assert block["attrs"] == {"level": level}
    assert joined_text(block) == "Plazo de préstamo"


def test_markdown_to_adf_keeps_paragraph_when_seven_hashes() -> None:
    """§8 (límite): `#######` no es un título válido; queda como párrafo literal."""
    [block] = blocks_of("####### Demasiados")
    assert block["type"] == "paragraph"
    assert joined_text(block) == "####### Demasiados"


def test_markdown_to_adf_keeps_paragraph_when_hash_without_space() -> None:
    """§8 (negativa): `#etiqueta` sin espacio no es un título."""
    [block] = blocks_of("#etiqueta")
    assert block["type"] == "paragraph"


def test_markdown_to_adf_joins_consecutive_lines_with_hard_break_when_paragraph() -> None:
    """§8: las líneas seguidas forman un párrafo, separadas por `hardBreak`."""
    [block] = blocks_of("Primera línea\nSegunda línea")
    assert block["type"] == "paragraph"
    assert [n["type"] for n in block["content"]] == ["text", "hardBreak", "text"]
    assert joined_text(block) == "Primera líneaSegunda línea"


def test_markdown_to_adf_splits_paragraphs_when_blank_line() -> None:
    """§8: una línea en blanco separa párrafos."""
    result = blocks_of("Uno\n\nDos")
    assert [b["type"] for b in result] == ["paragraph", "paragraph"]
    assert [joined_text(b) for b in result] == ["Uno", "Dos"]


def test_markdown_to_adf_ends_paragraph_when_heading_follows() -> None:
    """§8: un título sin línea en blanco previa corta el párrafo."""
    assert [b["type"] for b in blocks_of("Texto\n## Título")] == ["paragraph", "heading"]


# --- Listas ----------------------------------------------------------------------------------


@pytest.mark.parametrize("marker", ["-", "*", "+"])
def test_markdown_to_adf_builds_bullet_list_when_dash_star_or_plus(marker: str) -> None:
    """§8: listas con viñetas."""
    [block] = blocks_of(f"{marker} Reservar\n{marker} Renovar")
    assert block["type"] == "bulletList"
    items = block["content"]
    assert [i["type"] for i in items] == ["listItem", "listItem"]
    assert [joined_text(i) for i in items] == ["Reservar", "Renovar"]
    assert items[0]["content"][0]["type"] == "paragraph"


@pytest.mark.parametrize("sep", [".", ")"])
def test_markdown_to_adf_builds_ordered_list_when_numbered(sep: str) -> None:
    """§8: listas numeradas `1.` y `1)`."""
    [block] = blocks_of(f"1{sep} Abrir el préstamo\n2{sep} Pulsar «Renovar»")
    assert block["type"] == "orderedList"
    assert [joined_text(i) for i in block["content"]] == ["Abrir el préstamo", "Pulsar «Renovar»"]


def test_markdown_to_adf_nests_list_when_item_indented() -> None:
    """§8: una viñeta sangrada se anida en el elemento anterior."""
    [block] = blocks_of("- Préstamos\n  - Renovar\n  - Devolver\n- Reservas")
    assert block["type"] == "bulletList"
    first, second = block["content"]
    assert [c["type"] for c in first["content"]] == ["paragraph", "bulletList"]
    assert [joined_text(i) for i in first["content"][1]["content"]] == ["Renovar", "Devolver"]
    assert joined_text(second) == "Reservas"


def test_markdown_to_adf_nests_bullets_inside_ordered_list_when_mixed() -> None:
    """§8: anidación de tipos distintos (numerada con viñetas dentro)."""
    [block] = blocks_of("1. Uno\n2. Dos\n   - Detalle")
    assert block["type"] == "orderedList"
    second = block["content"][1]
    assert second["content"][1]["type"] == "bulletList"
    assert joined_text(second["content"][1]) == "Detalle"


def test_markdown_to_adf_nests_three_levels_when_deeper_indent() -> None:
    """§8 (límite): tres niveles de anidación."""
    [block] = blocks_of("- a\n  - b\n    - c")
    level2 = block["content"][0]["content"][1]
    level3 = level2["content"][0]["content"][1]
    assert level3["type"] == "bulletList"
    assert joined_text(level3) == "c"


def test_markdown_to_adf_splits_lists_when_marker_type_changes() -> None:
    """§8: una viñeta tras una numerada al mismo nivel abre otra lista."""
    assert [b["type"] for b in blocks_of("1. Uno\n- Otro")] == ["orderedList", "bulletList"]


def test_markdown_to_adf_appends_indented_continuation_to_item_when_list() -> None:
    """§8: una línea sangrada continúa el elemento anterior con un `hardBreak`."""
    [block] = blocks_of("- Primera parte\n  segunda parte")
    [item] = block["content"]
    assert [n["type"] for n in item["content"][0]["content"]] == ["text", "hardBreak", "text"]


def test_markdown_to_adf_keeps_all_items_when_first_item_is_indented() -> None:
    """§8: no se pierde contenido aunque la lista empiece sangrada."""
    document = markdown_to_adf("  - Elemento sangrado\n- Elemento sin sangría")
    assert "Elemento sin sangría" in joined_text(document)


# --- Tablas ----------------------------------------------------------------------------------


def test_markdown_to_adf_builds_table_with_header_cells_when_separator_row() -> None:
    """§8: la fila separadora `|---|` convierte la primera en cabecera (`tableHeader`)."""
    [block] = blocks_of("| Campo | Valor |\n|---|:---:|\n| Plazo | 21 días |")
    assert block["type"] == "table"
    header, body = block["content"]
    assert [c["type"] for c in header["content"]] == ["tableHeader", "tableHeader"]
    assert [c["type"] for c in body["content"]] == ["tableCell", "tableCell"]
    assert table_rows(block) == [["Campo", "Valor"], ["Plazo", "21 días"]]
    assert all(r["type"] == "tableRow" for r in block["content"])


def test_markdown_to_adf_builds_table_without_header_when_no_separator() -> None:
    """§8: sin fila separadora, todas las celdas son `tableCell`."""
    [block] = blocks_of("| Plazo | 21 días |\n| Renovaciones | 2 |")
    for r in block["content"]:
        assert {c["type"] for c in r["content"]} == {"tableCell"}
    assert table_rows(block) == [["Plazo", "21 días"], ["Renovaciones", "2"]]


def test_markdown_to_adf_pads_rows_when_cell_counts_differ() -> None:
    """§8: las filas con menos celdas se rellenan hasta el ancho de la tabla."""
    [block] = blocks_of("| a | b | c |\n|---|---|---|\n| solo uno |")
    assert [len(r["content"]) for r in block["content"]] == [3, 3]
    assert table_rows(block)[1] == ["solo uno", "", ""]


def test_markdown_to_adf_empty_cell_has_paragraph_without_text_node() -> None:
    """§8: una celda vacía lleva un párrafo sin nodos de texto vacíos."""
    [block] = blocks_of("| a |  |")
    assert block["content"][0]["content"][1]["content"] == [{"type": "paragraph"}]


def test_markdown_to_adf_treats_escaped_pipe_as_literal_when_in_cell() -> None:
    """PA-49: `\\|` es una barra literal dentro de una sola celda."""
    [block] = blocks_of("| a \\| b | c |")
    assert table_rows(block) == [["a | b", "c"]]


def test_markdown_to_adf_does_not_split_cell_when_line_break_follows_row() -> None:
    """PA-49: un salto de línea termina la fila; no abre celdas ni pasa texto a la celda."""
    table, paragraph_node = blocks_of("| Campo | Valor |\ntexto suelto")
    assert table_rows(table) == [["Campo", "Valor"]]
    assert paragraph_node["type"] == "paragraph"
    assert joined_text(paragraph_node) == "texto suelto"


def test_markdown_to_adf_applies_inline_marks_when_inside_cell() -> None:
    """§8: la negrita funciona dentro de una celda."""
    [node] = text_nodes(blocks_of("| **Plazo** |")[0])
    assert mark_types(node) == ["strong"]


def test_markdown_to_adf_keeps_data_row_when_cells_are_only_dashes() -> None:
    """§8: no se pierde una fila de datos con valores «-»."""
    [block] = blocks_of("| a | b |\n|---|---|\n| - | - |")
    assert len(block["content"]) == 2


# --- En línea: negrita, código y enlaces -----------------------------------------------------


def test_markdown_to_adf_marks_strong_when_double_asterisks() -> None:
    """§8: `**texto**` lleva el mark `strong`."""
    [block] = blocks_of("Plazo de **21 días** fijo")
    nodes = block["content"]
    assert [n["text"] for n in nodes] == ["Plazo de ", "21 días", " fijo"]
    assert [mark_types(n) for n in nodes] == [[], ["strong"], []]


def test_markdown_to_adf_keeps_literal_when_bold_not_closed() -> None:
    """§8 (negativa): `**` sin cerrar queda literal."""
    [block] = blocks_of("**sin cerrar")
    assert joined_text(block) == "**sin cerrar"
    assert all(not mark_types(n) for n in text_nodes(block))


def test_markdown_to_adf_marks_code_when_backticks() -> None:
    """§8: `` `x` `` lleva el mark `code`."""
    [block] = blocks_of("Llama a `renovar()` ahora")
    code = [n for n in text_nodes(block) if "code" in mark_types(n)]
    assert [n["text"] for n in code] == ["renovar()"]


@pytest.mark.parametrize("md", ["**`renovar`**", "**antes `renovar` después**"])
def test_markdown_to_adf_never_combines_code_with_strong_when_code_inside_bold(md: str) -> None:
    """§8: ADF solo admite `code` junto a `link`; nunca `code` + `strong`."""
    nodes = text_nodes(markdown_to_adf(md))
    assert any("code" in mark_types(n) for n in nodes)
    for node in nodes:
        if "code" in mark_types(node):
            assert mark_types(node) == ["code"]


def test_markdown_to_adf_does_not_parse_bold_inside_code() -> None:
    """§8: dentro de código en línea el Markdown es literal."""
    [node] = text_nodes(markdown_to_adf("`**x**`"))
    assert node["text"] == "**x**"
    assert mark_types(node) == ["code"]


def test_markdown_to_adf_resolves_backslash_escapes_when_escapable() -> None:
    """§8: `\\*` es un asterisco literal, sin negrita."""
    [block] = blocks_of("\\*\\*no negrita\\*\\*")
    assert joined_text(block) == "**no negrita**"
    assert all(not mark_types(n) for n in text_nodes(block))


@pytest.mark.parametrize(
    "url",
    [
        "https://villaficticia.example/prestamos",
        "http://villaficticia.example",
        "HTTPS://villaficticia.example/x?y=1",
    ],
)
def test_markdown_to_adf_marks_link_when_http_or_https_with_netloc(url: str) -> None:
    """PA-49: solo los enlaces `http(s)` con dominio llevan el mark `link`."""
    [block] = blocks_of(f"Ver [reglamento]({url})")
    link_nodes = [n for n in text_nodes(block) if "link" in mark_types(n)]
    assert [n["text"] for n in link_nodes] == ["reglamento"]
    assert link_nodes[0]["marks"] == [{"type": "link", "attrs": {"href": url}}]


def test_markdown_to_adf_combines_strong_and_link_when_bold_label() -> None:
    """§8: una etiqueta en negrita conserva `strong` y añade `link`."""
    [node] = text_nodes(markdown_to_adf("[**Ficha**](https://villaficticia.example)"))
    assert mark_types(node) == ["strong", "link"]


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:void",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///ruta/ficticia",
        "/ruta/relativa",
        "relativa.html",
        "//villaficticia.example",
        "mailto:persona@example.com",
        "http://",
        "ftp://villaficticia.example",
    ],
)
def test_markdown_to_adf_keeps_link_as_literal_text_when_unsafe_url(url: str) -> None:
    """PA-49: `javascript:`, `data:`, `file:`, relativos, `mailto:`… quedan como texto."""
    document = markdown_to_adf(f"Ver [enlace]({url}) fin")
    assert all("link" not in mark_types(n) for n in text_nodes(document))
    assert "[enlace](" in joined_text(document)
    assert_valid_doc(document)


@pytest.mark.parametrize(
    "md",
    [
        "<script>alert('ficticio')</script>",
        "<b>negrita html</b>",
        '<a href="javascript:alert(1)">x</a>',
        "<img src=x onerror=alert(1)>",
    ],
)
def test_markdown_to_adf_keeps_html_as_literal_text_when_html_tags(md: str) -> None:
    """PA-49: el HTML nunca se interpreta; queda como texto literal en un párrafo."""
    [block] = blocks_of(md)
    assert block["type"] == "paragraph"
    assert joined_text(block) == md
    assert {n["type"] for n in walk(block)} <= {"paragraph", "text"}
    assert all(not mark_types(n) for n in text_nodes(block))


# --- Bloques de código y regla ---------------------------------------------------------------


def test_markdown_to_adf_builds_code_block_with_language_when_fenced() -> None:
    """§8: bloque de código con lenguaje; el contenido es literal."""
    [block] = blocks_of("```gherkin\nDado **algo**\nCuando <b>x</b>\n```")
    assert block["type"] == "codeBlock"
    assert block["attrs"] == {"language": "gherkin"}
    assert block["content"] == [{"type": "text", "text": "Dado **algo**\nCuando <b>x</b>"}]


def test_markdown_to_adf_builds_code_block_without_attrs_when_no_language() -> None:
    """§8: sin lenguaje no hay `attrs`."""
    [block] = blocks_of("```\nGET /prestamos\n```")
    assert block["type"] == "codeBlock"
    assert "attrs" not in block


def test_markdown_to_adf_takes_rest_as_code_when_fence_not_closed() -> None:
    """§8 (límite): un bloque sin cerrar llega hasta el final del texto."""
    [block] = blocks_of("```python\nlinea 1\n\n# no es título")
    assert block["type"] == "codeBlock"
    assert block["attrs"] == {"language": "python"}
    assert block["content"][0]["text"] == "linea 1\n\n# no es título"


def test_markdown_to_adf_omits_text_node_when_code_block_empty() -> None:
    """§8: un bloque de código vacío no lleva nodos de texto vacíos."""
    assert blocks_of("```\n```") == [{"type": "codeBlock"}]


def test_markdown_to_adf_continues_after_closed_code_block() -> None:
    """§8: tras cerrar el bloque se siguen leyendo bloques."""
    assert [b["type"] for b in blocks_of("```\nx\n```\nDespués")] == ["codeBlock", "paragraph"]


@pytest.mark.parametrize("md", ["---", "***", "___", "-----"])
def test_markdown_to_adf_builds_rule_when_three_or_more_dashes(md: str) -> None:
    """§8: `---` es una regla horizontal."""
    assert blocks_of(f"Antes\n\n{md}\n\nDespués")[1] == {"type": "rule"}


# --- PA-49: limpieza y límites ---------------------------------------------------------------


def test_markdown_to_adf_removes_control_characters() -> None:
    """PA-49: se eliminan los caracteres de control (salvo saltos de línea)."""
    assert joined_text(markdown_to_adf("Pla\x00zo\x07 de\x1b préstamo\x7f")) == "Plazo de préstamo"


def test_markdown_to_adf_normalises_crlf_line_endings() -> None:
    """PA-49: `\\r\\n` y `\\r` se tratan como saltos de línea."""
    result = blocks_of("# Título\r\nTexto\rMás")
    assert [b["type"] for b in result] == ["heading", "paragraph"]
    assert all("\r" not in n["text"] for b in result for n in text_nodes(b))


def test_markdown_to_adf_truncates_input_when_longer_than_max() -> None:
    """PA-49: la entrada de más de MAX_MARKDOWN_CHARS se trunca."""
    document = markdown_to_adf("a" * (MAX_MARKDOWN_CHARS + 500))
    assert len(joined_text(document)) == MAX_MARKDOWN_CHARS


def test_markdown_to_adf_does_not_truncate_when_exactly_max() -> None:
    """PA-49 (límite): exactamente MAX_MARKDOWN_CHARS no pierde nada."""
    assert len(joined_text(markdown_to_adf("b" * MAX_MARKDOWN_CHARS))) == MAX_MARKDOWN_CHARS


@pytest.mark.parametrize(
    "md",
    [
        "****",
        "** **",
        "``",
        "#  ",
        "| |",
        "- ",
        "[]()",
        "\\",
        "**a**\n\n**b**",
        "a\n\n\n\nb",
        "| a | b |\n|---|---|\n|  |  |",
        "[**](https://villaficticia.example)",
        "\x00\x01\x02",
    ],
)
def test_markdown_to_adf_never_emits_empty_text_nodes(md: str) -> None:
    """PA-49 / §8: ningún nodo `text` vacío (Jira rechaza el documento)."""
    assert_valid_doc(markdown_to_adf(md))


# --- Ida y vuelta con adf_to_text ------------------------------------------------------------


@pytest.mark.parametrize(
    "md",
    [
        "# Título 1",
        "###### Título 6",
        "Un párrafo de texto ficticio.",
        "- Reservar\n- Renovar",
        "1. Abrir\n2. Renovar",
        "- Préstamos\n  - Renovar",
        "| Campo | Valor |\n| Plazo | 21 días |",
        "```\nGET /prestamos/ficticio\n```",
        "---",
    ],
)
def test_markdown_to_adf_round_trips_with_adf_to_text_per_block_type(md: str) -> None:
    """§8: Markdown → ADF → texto devuelve el mismo bloque (sin marcas en línea)."""
    assert adf_to_text(markdown_to_adf(md)) == md


def test_markdown_to_adf_round_trip_drops_separator_row_when_table_with_header() -> None:
    """§8: la fila separadora no se conserva en el texto (la cabecera sí)."""
    result = adf_to_text(markdown_to_adf("| a | b |\n|---|---|\n| 1 | 2 |"))
    assert result == "| a | b |\n| 1 | 2 |"


def test_markdown_to_adf_round_trip_keeps_inline_text_without_marks() -> None:
    """§8: la negrita, el código y los enlaces se leen como texto plano."""
    md = "Plazo **21 días**, `renovar()` y [ficha](https://villaficticia.example)"
    assert adf_to_text(markdown_to_adf(md)) == "Plazo 21 días, renovar() y ficha"


def test_markdown_to_adf_round_trip_keeps_line_breaks_when_paragraph() -> None:
    """§8: los `hardBreak` vuelven como saltos de línea."""
    assert adf_to_text(markdown_to_adf("Uno\nDos")) == "Uno\nDos"


def test_markdown_to_adf_round_trip_preserves_block_order_when_mixed_document() -> None:
    """§8: un documento con todos los tipos de bloque conserva el orden."""
    md = (
        "## Cambios\n\nTexto\n\n- a\n- b\n\n1. uno\n\n| C | V |\n|---|---|\n| x | y |\n\n"
        "```\ncodigo\n```\n\n---"
    )
    expected = (
        "## Cambios\n\nTexto\n\n- a\n- b\n\n1. uno\n\n| C | V |\n| x | y |\n\n"
        "```\ncodigo\n```\n\n---"
    )
    assert adf_to_text(markdown_to_adf(md)) == expected


# --- Comentario de diff de core (core/graph/nodes.py `_diff_comment_md`) ---------------------


def _impact(*diffs: StoryDiff) -> ImpactAnalysis:
    return ImpactAnalysis(diffs=list(diffs), affected=[], regression_notes=[])


def test_markdown_to_adf_builds_header_table_when_core_diff_comment() -> None:
    """RF-05 / §8: el diff de core es una tabla ADF con cabecera Campo/Antes/Después."""
    impact = _impact(
        StoryDiff(field="title", before="Renovar", after="Renovar un préstamo"),
        StoryDiff(field="business_goal", before=None, after="Menos visitas al mostrador"),
    )
    paragraph_node, table = blocks_of(_diff_comment_md(impact))
    assert paragraph_node["type"] == "paragraph"
    assert [mark_types(n) for n in text_nodes(paragraph_node)] == [["strong"]]
    assert table["type"] == "table"
    assert [c["type"] for c in table["content"][0]["content"]] == ["tableHeader"] * 3
    assert table_rows(table) == [
        ["Campo", "Antes", "Después"],
        ["title", "Renovar", "Renovar un préstamo"],
        ["business_goal", "—", "Menos visitas al mostrador"],
    ]


def test_markdown_to_adf_builds_header_only_table_when_core_diff_has_no_diffs() -> None:
    """RF-05 (límite): sin diferencias queda la cabecera, sin filas de datos."""
    _, table = blocks_of(_diff_comment_md(_impact()))
    assert table_rows(table) == [["Campo", "Antes", "Después"]]


def test_markdown_to_adf_keeps_three_cells_when_core_diff_values_have_pipe_and_newline() -> None:
    """PA-49: `|` y saltos de línea de un valor no rompen la tabla del diff."""
    impact = _impact(StoryDiff(field="title", before="a | b", after="línea 1\nlínea 2"))
    result = blocks_of(_diff_comment_md(impact))
    assert [b["type"] for b in result] == ["paragraph", "table"]
    rows = table_rows(result[1])
    assert [len(r) for r in rows] == [3, 3]
    assert rows[1][1] == "a | b"


@pytest.mark.parametrize("char", ["‮", "‪", "⁦", "⁩", "​", "﻿"])
def test_markdown_to_adf_removes_bidi_and_zero_width_characters(char: str) -> None:
    """PA-49: sin control bidireccional ni anchura cero (orden visual engañoso en Jira)."""
    assert adf_to_text(markdown_to_adf(f"pago{char}seguro")) == "pagoseguro"


def test_markdown_to_adf_keeps_zero_width_joiner_used_by_emojis() -> None:
    """Las secuencias de emoji (U+200D) no se rompen."""
    assert adf_to_text(markdown_to_adf("👩‍💻")) == "👩‍💻"


# --- table (T-30) ----------------------------------------------------------------------------


def test_table_builds_header_row_and_literal_cells() -> None:
    """T-30: la tabla de pasos lleva cabecera y celdas de texto literal (sin Markdown)."""
    node = table(["#", "Acción"], [["1", "**pulsa** <b>Renovar</b>"], ["2", ""]])
    header, first, second = node["content"]
    assert [c["type"] for c in header["content"]] == ["tableHeader", "tableHeader"]
    assert [c["type"] for c in first["content"]] == ["tableCell", "tableCell"]
    action = first["content"][1]["content"][0]["content"]
    assert action == [{"type": "text", "text": "**pulsa** <b>Renovar</b>"}]
    assert second["content"][1]["content"] == [{"type": "paragraph"}]  # sin texto vacío
    assert adf_to_text({"type": "doc", "content": [node]}).splitlines()[0] == "| # | Acción |"


# --- PA-143: _HEADING sin backtracking ------------------------------------------------------


def test_markdown_to_adf_heading_is_linear_with_many_spaces() -> None:
    """PA-143 (ReDoS): «# a» + 20 000 espacios + «b» tardaba ~4,5 s; ahora es lineal."""
    import time

    started = time.perf_counter()
    adf = markdown_to_adf("# a" + " " * 20_000 + "b")
    assert time.perf_counter() - started < 0.5
    assert adf["content"][0]["type"] == "heading"


@pytest.mark.parametrize(
    ("md", "level", "title"),
    [
        ("# Título   ", 1, "Título"),
        ("###   Varios   espacios  ", 3, "Varios   espacios"),
        ("## ", 2, ""),
    ],
)
def test_markdown_to_adf_heading_keeps_title_without_surrounding_spaces(
    md: str, level: int, title: str
) -> None:
    """PA-143: el título sale igual que antes, sin los espacios de los extremos."""
    [node] = markdown_to_adf(md)["content"]
    assert node["type"] == "heading" and node["attrs"]["level"] == level
    assert "".join(c.get("text", "") for c in node.get("content", [])) == title


def test_markdown_to_adf_hashes_without_space_are_not_a_heading() -> None:
    """PA-143 (límite): «##» sin espacio sigue sin ser un título."""
    assert markdown_to_adf("##titulo")["content"][0]["type"] == "paragraph"


# --- PA-230: _FENCE y _LINK sin coste no lineal -----------------------------------------------


@pytest.mark.parametrize(
    "md",
    [
        "```" + " " * 100_000 + "!",
        "```" + "\t" * 20_000 + "!",  # los tabuladores se expanden a 4 espacios
        "[" * 100_000,
        "[a](" * 25_000,
    ],
    ids=["valla-espacios", "valla-tabs", "corchetes", "enlaces-abiertos"],
)
def test_markdown_to_adf_is_linear_on_adversarial_lines(md: str) -> None:
    """PA-230 (ReDoS): «```» + 100 000 espacios + «!» tardaba ~54 s (y 20 000 tabuladores, ~60 s
    en el conversor completo); ahora todo se convierte en tiempo lineal."""
    import time

    started = time.perf_counter()
    markdown_to_adf(md)
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize(
    ("md", "language"),
    [
        ("```python\nprint(1)\n```", "python"),
        ("   ```  sql  \nselect 1\n  ```  ", "sql"),
        ("```\nx\n```", ""),
    ],
    ids=["normal", "espacios-alrededor", "sin-lenguaje"],
)
def test_markdown_to_adf_fence_still_recognized(md: str, language: str) -> None:
    """PA-230: las vallas con espacios alrededor y con o sin lenguaje se siguen reconociendo."""
    [node] = markdown_to_adf(md)["content"]
    assert node["type"] == "codeBlock"
    assert node.get("attrs", {}).get("language", "") == language


def test_markdown_to_adf_link_label_stops_at_an_inner_bracket() -> None:
    """PA-230 (comportamiento fijado): la etiqueta no admite «[» (así el patrón es lineal). En
    «[uno [dos](url)» antes se enlazaba «uno [dos»; ahora «[uno » queda como texto literal y el
    enlace es solo «dos». El texto completo se conserva."""
    url = "https://ejemplo.invalid"
    [paragraph] = markdown_to_adf(f"[uno [dos]({url})")["content"]
    nodes = paragraph["content"]
    linked = [n["text"] for n in nodes if any(m["type"] == "link" for m in n.get("marks", []))]
    assert linked == ["dos"]
    assert "".join(n.get("text", "") for n in nodes) == "[uno dos"
    assert all(
        m["attrs"]["href"] == url for n in nodes for m in n.get("marks", []) if m["type"] == "link"
    )


# --- PA-230: tablas acotadas (ancho × filas) --------------------------------------------------


def test_markdown_to_adf_wide_table_with_many_rows_is_linear() -> None:
    """PA-230 (DoS, security-reviewer): una fila de 50 000 «|» y 25 000 filas creaba ancho × filas
    celdas (290 s y 7 GB con 12 000 caracteres). Ahora se publica como texto literal, en tiempo
    lineal y sin perder contenido."""
    import time

    md = "|" * 50_000 + "\n" + "|\n" * 25_000
    started = time.perf_counter()
    [node] = markdown_to_adf(md)["content"]
    assert time.perf_counter() - started < 1.0
    assert node["type"] == "codeBlock"
    assert node["content"][0]["text"].count("|") == md.count("|")


def test_markdown_to_adf_caps_columns_and_keeps_extra_cells_in_the_last_one() -> None:
    """PA-230: como mucho MAX_TABLE_COLUMNS columnas; las que sobran se unen a la última celda."""
    from adapters.jira.adf import MAX_TABLE_COLUMNS

    cells = [f"c{i}" for i in range(MAX_TABLE_COLUMNS + 5)]
    [table] = markdown_to_adf("| " + " | ".join(cells) + " |")["content"]
    [row] = table["content"]
    assert len(row["content"]) == MAX_TABLE_COLUMNS
    last = row["content"][-1]["content"][0]["content"][0]["text"]
    assert last == " | ".join(cells[MAX_TABLE_COLUMNS - 1 :])


def test_markdown_to_adf_table_over_the_cell_limit_becomes_literal_text() -> None:
    """PA-230: una tabla con más de MAX_TABLE_CELLS celdas va como bloque de código literal."""
    from adapters.jira.adf import MAX_TABLE_CELLS

    rows = MAX_TABLE_CELLS // 2 + 1
    md = "\n".join("| a | b |" for _ in range(rows))
    [node] = markdown_to_adf(md)["content"]
    assert node["type"] == "codeBlock"
    assert node["content"][0]["text"] == md


def test_markdown_to_adf_normal_table_is_still_a_table() -> None:
    """PA-230 (no regresión): una tabla corriente, como la del diff, sigue siendo una tabla."""
    [node] = markdown_to_adf("| Campo | Antes | Después |\n|---|---|---|\n| title | a | b |")[
        "content"
    ]
    assert node["type"] == "table"
    assert [c["type"] for c in node["content"][0]["content"]] == ["tableHeader"] * 3
