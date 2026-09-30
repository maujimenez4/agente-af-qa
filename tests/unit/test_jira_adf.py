"""Conversión de ADF a texto plano para el LLM (T-11, RF-03; SPEC-00 §8 «ADF»).

Datos 100 % sintéticos del dominio ficticio de la Biblioteca de Villaficticia.
"""

from typing import Any

import pytest

from adapters.jira.adf import adf_to_text

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
