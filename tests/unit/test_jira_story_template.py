"""Plantilla de la HU en Jira: título `[HU-XX]` (R-05) y descripción ADF (T-27, RF-04, RF-15).

Sin red ni LLM. Datos 100 % sintéticos del dominio ficticio de la Biblioteca de Villaficticia
(`tests/fakes/dataset.py`).
"""

from collections.abc import Iterator
from typing import Any

import pytest

from adapters.jira.adf import adf_to_text
from adapters.jira.story_template import MAX_SUMMARY_CHARS, story_summary, story_to_adf
from schemas.common import SourceRef
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes.dataset import renewal_story

Node = dict[str, Any]


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in node.get("content") or []:
        yield from walk(child)


def text_nodes(node: Node) -> list[Node]:
    return [n for n in walk(node) if n.get("type") == "text"]


def mark_types(node: Node) -> list[str]:
    return [mark["type"] for mark in node.get("marks", [])]


def joined_text(node: Node) -> str:
    return "".join(n["text"] for n in text_nodes(node))


def headings(document: Node, level: int | None = None) -> list[str]:
    return [
        joined_text(block)
        for block in document["content"]
        if block["type"] == "heading" and (level is None or block["attrs"]["level"] == level)
    ]


def section(document: Node, title: str) -> list[Node]:
    """Bloques que siguen al título `title` hasta el siguiente título de su nivel o superior."""
    blocks = document["content"]
    for i, block in enumerate(blocks):
        if block["type"] == "heading" and joined_text(block) == title:
            level = block["attrs"]["level"]
            result = []
            for following in blocks[i + 1 :]:
                if following["type"] == "heading" and following["attrs"]["level"] <= level:
                    break
                result.append(following)
            return result
    raise AssertionError(f"No hay sección «{title}»")


def list_items(bullet_list: Node) -> list[str]:
    assert bullet_list["type"] == "bulletList"
    return [joined_text(item) for item in bullet_list["content"]]


def minimal_story(**overrides: Any) -> UserStory:
    """HU sintética con solo los campos obligatorios rellenos."""
    data: dict[str, Any] = {
        "internal_id": "HU-07",
        "title": "Consultar el catálogo ficticio",
        "role": "persona socia",
        "action": "consultar el catálogo",
        "benefit": "saber qué libros hay",
        "description": "",
        "business_goal": "",
        "scope_includes": [],
        "scope_excludes": [],
        "acceptance_criteria": [
            AcceptanceCriterion(
                id="CA-01", title="Consulta básica", given=["g"], when=["w"], then=["t"]
            )
        ],
        "business_rules": [],
        "assumptions": [],
        "constraints": [],
        "dependencies": [],
        "alternate_flows": [],
        "exceptions": [],
        "related_features": [],
        "priority": "Should",
    }
    return UserStory(**(data | overrides))


# --- story_summary (R-05) --------------------------------------------------------------------


def test_story_summary_prefixes_internal_id_when_present() -> None:
    """R-05: el título lleva el prefijo `[HU-02]`."""
    assert story_summary(renewal_story()) == "[HU-02] Renovar un préstamo"


def test_story_summary_does_not_duplicate_prefix_when_title_already_has_it() -> None:
    """R-05: si el título ya empieza por `[HU-02]`, no se repite."""
    story = renewal_story().model_copy(update={"title": "[HU-02] Renovar un préstamo"})
    assert story_summary(story) == "[HU-02] Renovar un préstamo"


def test_story_summary_does_not_duplicate_prefix_when_title_has_leading_spaces() -> None:
    """R-05 (límite): los espacios iniciales no provocan un prefijo duplicado."""
    story = renewal_story().model_copy(update={"title": "   [HU-02] Renovar"})
    assert story_summary(story) == "[HU-02] Renovar"


def test_story_summary_has_no_prefix_when_internal_id_is_none() -> None:
    """R-05: sin `internal_id`, el título va sin prefijo."""
    story = renewal_story().model_copy(update={"internal_id": None})
    assert story_summary(story) == "Renovar un préstamo"


@pytest.mark.parametrize(
    "internal_id", ["", "HU02", "hu-02", "HU-", "HU-0x", "[HU-02]", "HU-02 ", "HU-02\n", "CP-01"]
)
def test_story_summary_has_no_prefix_when_internal_id_is_invalid(internal_id: str) -> None:
    """R-05 (negativa): un `internal_id` con formato no válido no se publica como prefijo."""
    story = renewal_story().model_copy(update={"internal_id": internal_id})
    assert story_summary(story) == "Renovar un préstamo"


def test_story_summary_collapses_line_breaks_and_spaces_into_one_line() -> None:
    """R-05: el título de Jira es de una línea; saltos y espacios repetidos se colapsan."""
    story = renewal_story().model_copy(update={"title": "Renovar\nun \r\n préstamo\t\tya"})
    assert story_summary(story) == "[HU-02] Renovar un préstamo ya"


def test_story_summary_removes_control_characters() -> None:
    """PA-49: el título no lleva caracteres de control."""
    story = renewal_story().model_copy(update={"title": "Reno\x00var\x07"})
    assert story_summary(story) == "[HU-02] Renovar"


def test_story_summary_truncates_to_max_chars_when_title_too_long() -> None:
    """R-05: el título no supera los 255 caracteres de Jira."""
    story = renewal_story().model_copy(update={"title": "x" * 400})
    result = story_summary(story)
    assert MAX_SUMMARY_CHARS == 255
    assert len(result) == MAX_SUMMARY_CHARS
    assert result.startswith("[HU-02] x")


def test_story_summary_keeps_title_when_exactly_max_chars() -> None:
    """R-05 (límite): un título que cabe justo no se recorta."""
    title = "y" * (MAX_SUMMARY_CHARS - len("[HU-02] "))
    story = renewal_story().model_copy(update={"title": title})
    assert story_summary(story) == f"[HU-02] {title}"


# --- story_to_adf: plantilla (RF-15) ---------------------------------------------------------


def test_story_to_adf_returns_doc_version_1_without_empty_text_nodes() -> None:
    """§8: la descripción es un documento ADF válido."""
    document = story_to_adf(renewal_story())
    assert document["type"] == "doc"
    assert document["version"] == 1
    assert all(n["text"] for n in text_nodes(document))


def test_story_to_adf_starts_with_role_action_benefit_paragraph() -> None:
    """RF-15: «Como …, quiero …, para …» con las palabras clave en negrita."""
    first = story_to_adf(renewal_story())["content"][0]
    assert first["type"] == "paragraph"
    nodes = first["content"]
    assert [n["text"] for n in nodes] == [
        "Como ",
        "persona socia de la biblioteca",
        ", quiero ",
        "renovar un préstamo activo desde la web",
        ", para ",
        "no tener que acudir al mostrador para ampliar el plazo",
    ]
    assert [mark_types(n) for n in nodes] == [["strong"], [], ["strong"], [], ["strong"], []]


def test_story_to_adf_includes_description_and_business_goal_sections() -> None:
    """RF-15: Descripción y Objetivo de negocio como títulos de nivel 2 con su párrafo."""
    document = story_to_adf(renewal_story())
    [description] = section(document, "Descripción")
    assert joined_text(description) == (
        "La persona socia renueva un préstamo activo antes de su vencimiento."
    )
    [goal] = section(document, "Objetivo de negocio")
    assert joined_text(goal) == "Reducir las visitas al mostrador por renovaciones."


def test_story_to_adf_includes_scope_with_includes_and_excludes_subsections() -> None:
    """RF-15: Alcance (nivel 2) con Incluye/Excluye (nivel 3) en listas."""
    document = story_to_adf(renewal_story())
    assert "Alcance" in headings(document, 2)
    assert {"Incluye", "Excluye"} <= set(headings(document, 3))
    [includes] = section(document, "Incluye")
    assert list_items(includes) == ["Renovación desde la ficha del préstamo"]
    [excludes] = section(document, "Excluye")
    assert list_items(excludes) == ["Renovación de materiales audiovisuales"]


def test_story_to_adf_writes_each_criterion_with_id_and_gherkin_block() -> None:
    """RF-15, RF-16: cada CA-XX tiene su título y un bloque `gherkin` Dado/Y/Cuando/Entonces."""
    document = story_to_adf(renewal_story())
    assert headings(document, 3)[2:4] == [
        "CA-01 · Renovación permitida",
        "CA-02 · Renovación rechazada por reservas",
    ]
    [code] = section(document, "CA-01 · Renovación permitida")
    assert code["type"] == "codeBlock"
    assert code["attrs"] == {"language": "gherkin"}
    assert code["content"][0]["text"] == (
        "Escenario: Renovación permitida\n"
        "  Dado un préstamo activo con menos de 2 renovaciones\n"
        "  Y sin reservas pendientes\n"
        "  Cuando la persona socia pulsa «Renovar»\n"
        "  Entonces el vencimiento se amplía 21 días"
    )


def test_story_to_adf_uses_y_for_extra_steps_in_when_and_then() -> None:
    """RF-16: los pasos adicionales de Cuando y Entonces empiezan por «Y»."""
    criterion = AcceptanceCriterion(
        id="CA-05", title="Varios pasos", given=["g1"], when=["w1", "w2"], then=["t1", "t2"]
    )
    document = story_to_adf(minimal_story(acceptance_criteria=[criterion]))
    [code] = section(document, "CA-05 · Varios pasos")
    lines = code["content"][0]["text"].split("\n")
    assert lines == [
        "Escenario: Varios pasos",
        "  Dado g1",
        "  Cuando w1",
        "  Y w2",
        "  Entonces t1",
        "  Y t2",
    ]


def test_story_to_adf_lists_business_rules_with_bold_ids() -> None:
    """RF-17: Reglas de negocio con `RN-XX` en negrita."""
    document = story_to_adf(renewal_story())
    [rules] = section(document, "Reglas de negocio")
    assert list_items(rules) == [
        "RN-01: Máximo 2 renovaciones por préstamo.",
        "RN-02: No se renueva si hay reservas pendientes.",
    ]
    first = rules["content"][0]["content"][0]["content"]
    assert first[0] == {"type": "text", "text": "RN-01", "marks": [{"type": "strong"}]}
    assert mark_types(first[1]) == []


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Supuestos", ["La persona socia ha iniciado sesión."]),
        ("Restricciones", ["Plazo de préstamo de 21 días (reglamento, art. 7)."]),
        ("Dependencias", ["DEMO-2"]),
        ("Flujos alternos", ["Renovación desde el correo de aviso de vencimiento."]),
        ("Excepciones", ["El servicio de catálogo no responde."]),
        ("Funcionalidades relacionadas", ["Reservas"]),
    ],
)
def test_story_to_adf_includes_list_section_when_items(title: str, expected: list[str]) -> None:
    """RF-15: las listas simples de la plantilla se publican con su título."""
    [items] = section(story_to_adf(renewal_story()), title)
    assert list_items(items) == expected


def test_story_to_adf_includes_optional_lists_when_filled() -> None:
    """RF-15: requisitos relacionados, cambios y preguntas abiertas cuando existen."""
    story = minimal_story(
        related_requirements=["RF-04"],
        changes_from_previous=["Se amplía el plazo"],
        open_questions=["¿Se avisa por correo?"],
    )
    document = story_to_adf(story)
    assert list_items(section(document, "Requisitos relacionados")[0]) == ["RF-04"]
    cambios = section(document, "Cambios respecto a la versión anterior")[0]
    assert list_items(cambios) == ["Se amplía el plazo"]
    assert list_items(section(document, "Preguntas abiertas")[0]) == ["¿Se avisa por correo?"]


def test_story_to_adf_includes_priority_section() -> None:
    """RF-15: Prioridad con su valor MoSCoW."""
    [priority] = section(story_to_adf(renewal_story()), "Prioridad")
    assert joined_text(priority) == "Must"


def test_story_to_adf_lists_sources_with_kind_and_ref() -> None:
    """RF-21: Fuentes con tipo y referencia."""
    story = minimal_story(
        sources=[
            SourceRef(kind="jira", ref="DEMO-3"),
            SourceRef(kind="rag", ref="doc-reglamento"),
        ]
    )
    [sources] = section(story_to_adf(story), "Fuentes")
    assert list_items(sources) == ["jira · DEMO-3", "rag · doc-reglamento"]


def test_story_to_adf_keeps_section_order() -> None:
    """RF-15: el orden de las secciones de la plantilla es estable."""
    names = headings(story_to_adf(renewal_story()), 2)
    assert names == [
        "Descripción",
        "Objetivo de negocio",
        "Alcance",
        "Criterios de aceptación",
        "Reglas de negocio",
        "Supuestos",
        "Restricciones",
        "Dependencias",
        "Flujos alternos",
        "Excepciones",
        "Funcionalidades relacionadas",
        "Prioridad",
    ]


def test_story_to_adf_round_trips_to_readable_text() -> None:
    """RF-03: la descripción publicada se vuelve a leer como texto con los CA y las RN."""
    result = adf_to_text(story_to_adf(renewal_story()))
    for fragment in ("## Criterios de aceptación", "### CA-01 · Renovación permitida", "RN-02"):
        assert fragment in result


# --- Secciones vacías ------------------------------------------------------------------------


def test_story_to_adf_omits_empty_sections() -> None:
    """RF-15: las secciones vacías no se publican; CA y Prioridad siempre están."""
    names = headings(story_to_adf(minimal_story()), 2)
    assert names == ["Criterios de aceptación", "Prioridad"]


def test_story_to_adf_omits_text_section_when_only_whitespace() -> None:
    """RF-15 (límite): una descripción de solo espacios se omite."""
    document = story_to_adf(minimal_story(description="  \n\t ", business_goal=" "))
    assert "Descripción" not in headings(document)
    assert "Objetivo de negocio" not in headings(document)


def test_story_to_adf_omits_blank_list_items_and_section_when_all_blank() -> None:
    """RF-15 (límite): los elementos en blanco se descartan y la sección vacía se omite."""
    document = story_to_adf(minimal_story(assumptions=["  ", ""], constraints=["", " Real "]))
    assert "Supuestos" not in headings(document)
    assert list_items(section(document, "Restricciones")[0]) == ["Real"]


def test_story_to_adf_shows_scope_with_only_includes_when_excludes_empty() -> None:
    """RF-15: con solo «Incluye», no aparece «Excluye»."""
    document = story_to_adf(minimal_story(scope_includes=["Algo"]))
    assert "Alcance" in headings(document, 2)
    assert "Incluye" in headings(document, 3)
    assert "Excluye" not in headings(document, 3)


# --- Contenido literal (PA-49) ---------------------------------------------------------------

UNTRUSTED = (
    "**negrita** [enlace](javascript:alert(1)) [web](https://villaficticia.example) "
    "<script>x</script>"
)


def test_story_to_adf_publishes_markdown_and_html_as_literal_text() -> None:
    """PA-49: el texto de la HU no se interpreta: ni `strong`, ni `link`, ni HTML."""
    story = minimal_story(
        title=UNTRUSTED,
        role=UNTRUSTED,
        description=UNTRUSTED,
        business_goal=UNTRUSTED,
        scope_includes=[UNTRUSTED],
        business_rules=[BusinessRule(id="RN-01", description=UNTRUSTED)],
        open_questions=[UNTRUSTED],
        acceptance_criteria=[
            AcceptanceCriterion(
                id="CA-01", title=UNTRUSTED, given=[UNTRUSTED], when=["w"], then=["t"]
            )
        ],
    )
    document = story_to_adf(story)
    nodes = text_nodes(document)
    assert all("link" not in mark_types(n) for n in nodes)
    literal = [n for n in nodes if UNTRUSTED in n["text"]]
    assert len(literal) >= 6
    assert all(mark_types(n) in ([], ["strong"]) for n in nodes)
    # Solo las palabras clave fijas de la plantilla llevan negrita, nunca el texto de la HU.
    assert all("strong" not in mark_types(n) for n in literal)
    allowed = {"doc", "paragraph", "text", "heading", "bulletList", "listItem", "codeBlock"}
    assert {n["type"] for n in walk(document)} <= allowed | {"hardBreak"}


def test_story_to_adf_turns_line_breaks_into_hard_breaks_not_blocks() -> None:
    """PA-49: un salto de línea en un campo no crea títulos ni listas."""
    story = minimal_story(description="Línea uno\n# no es título\n- no es lista")
    [description] = section(story_to_adf(story), "Descripción")
    assert description["type"] == "paragraph"
    assert [n["type"] for n in description["content"]] == [
        "text",
        "hardBreak",
        "text",
        "hardBreak",
        "text",
    ]


def test_story_to_adf_removes_control_characters_from_fields() -> None:
    """PA-49: los caracteres de control se eliminan de los campos."""
    document = story_to_adf(minimal_story(description="Pla\x00zo\x1b"))
    [description] = section(document, "Descripción")
    assert joined_text(description) == "Plazo"
