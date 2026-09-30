"""Construcción segura de JQL (T-14: RF-02, RF-14; SPEC-00 §6.1, §11).

Cubre `adapters/jira/jql.py` (literales, épicas e hijas) y `core/context/jql.py` (búsqueda por
texto libre y vínculos). Funciones puras: sin red. Claves y textos ficticios.
"""

import pytest

from adapters.jira.jql import ISSUE_KEY_RE, PROJECT_KEY_RE, children_jql, epics_jql, quote
from core.context.jql import MAX_TEXT_CHARS, linked_issues_jql, text_search_jql

LUCENE_SPECIAL = set('+-&|!(){}[]^~*?:\\/"')
TEXT_PREFIX = 'project = "DEMO" AND text ~ '
TEXT_SUFFIX = " ORDER BY updated DESC"


# --- Utilidades ------------------------------------------------------------------------------


def read_jql_string(jql: str, start: int) -> tuple[str, int]:
    """Lee un literal JQL entre comillas desde `start`; devuelve (contenido, índice final).

    Simula el analizador de JQL: `\\x` es el carácter `x` y la primera `"` sin escapar cierra.
    """
    assert jql[start] == '"'
    chars: list[str] = []
    index = start + 1
    while index < len(jql):
        char = jql[index]
        if char == "\\":
            chars.append(jql[index + 1])
            index += 2
            continue
        if char == '"':
            return "".join(chars), index + 1
        chars.append(char)
        index += 1
    pytest.fail("El literal JQL no está cerrado.")


def lucene_unescape(value: str) -> str:
    """Quita el escape de Lucene: `\\x` → `x`."""
    chars: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\":
            index += 1
        chars.append(value[index])
        index += 1
    return "".join(chars)


def assert_all_special_escaped(lucene: str) -> None:
    index = 0
    while index < len(lucene):
        if lucene[index] == "\\":
            index += 2
            continue
        assert lucene[index] not in LUCENE_SPECIAL, f"Carácter sin escapar en {lucene!r}"
        index += 1


def decode_text_literal(jql: str) -> str:
    """Contenido Lucene del único literal de `text ~`; falla si sobra algo detrás."""
    assert jql.startswith(TEXT_PREFIX)
    content, end = read_jql_string(jql, len(TEXT_PREFIX))
    assert jql[end:] == TEXT_SUFFIX
    return content


# --- adapters/jira/jql: quote ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param("DEMO", '"DEMO"', id="simple"),
        pytest.param('a"b', r'"a\"b"', id="comilla"),
        pytest.param("a\\b", r'"a\\b"', id="barra"),
        pytest.param('\\"', r'"\\\""', id="barra-y-comilla"),
        pytest.param("", '""', id="vacio"),
    ],
)
def test_quote_escapes_quotes_and_backslashes(value: str, expected: str) -> None:
    """RF-02: el literal escapa `\\` y `"` (la barra primero, sin dobles escapes)."""
    assert quote(value) == expected


@pytest.mark.parametrize("value", ['x" OR project = OTRO OR summary ~ "y', 'fin\\" OR 1=1', "\\"])
def test_quote_keeps_value_inside_single_literal_when_injection_attempt(value: str) -> None:
    """RF-02 (seguridad): el valor no puede cerrar el literal y añadir JQL."""
    literal = quote(value)
    content, end = read_jql_string(literal, 0)
    assert content == value
    assert end == len(literal)


# --- adapters/jira/jql: épicas e hijas -------------------------------------------------------


def test_epics_jql_uses_hierarchy_level_and_quoted_project() -> None:
    """RF-02: épicas por `hierarchyLevel = 1`, con la clave de proyecto entre comillas."""
    assert epics_jql("DEMO") == 'project = "DEMO" AND hierarchyLevel = 1 ORDER BY key'


def test_children_jql_filters_by_parent_ordered_by_key() -> None:
    """RF-02: HU hijas de una épica con `parent = KEY ORDER BY key`."""
    assert children_jql("DEMO-1") == "parent = DEMO-1 ORDER BY key"


@pytest.mark.parametrize("key", ["DEMO", "AB", "PROJ_2", "X1"])
def test_project_key_re_accepts_valid_keys(key: str) -> None:
    """§11: claves de proyecto `^[A-Z][A-Z0-9_]+$`."""
    assert PROJECT_KEY_RE.fullmatch(key)


@pytest.mark.parametrize(
    "key", ["demo", "D", "DE MO", 'DEMO"', "DEMO OR project = X", "1DEMO", "", "DEMO\n"]
)
def test_project_key_re_rejects_invalid_keys(key: str) -> None:
    """§11: minúsculas, una letra, espacios, comillas, operadores o salto final no valen."""
    assert not PROJECT_KEY_RE.fullmatch(key)


@pytest.mark.parametrize(
    "key", ["demo-1", "DEMO", "DEMO-", "DEMO-1 OR project = X", "DEMO-1\n", "DEMO-1)"]
)
def test_issue_key_re_rejects_invalid_keys(key: str) -> None:
    """§11: claves de incidencia no válidas (incluidos intentos de inyección)."""
    assert not ISSUE_KEY_RE.fullmatch(key)


# --- core/context/jql: text_search_jql (RF-14) ----------------------------------------------


def test_text_search_jql_builds_project_text_query_when_plain_text() -> None:
    """RF-14, §6.1: `project = "KEY" AND text ~ "…" ORDER BY updated DESC`."""
    assert text_search_jql("DEMO", "renovar") == (
        'project = "DEMO" AND text ~ "renovar" ORDER BY updated DESC'
    )


def test_text_search_jql_escapes_lucene_and_quotes_exactly() -> None:
    """RF-14: paréntesis, `+`, `?` y comillas se escapan para Lucene y luego para JQL."""
    jql = text_search_jql("DEMO", 'reserva (48 h) "lista" + aviso?')
    assert jql == (TEXT_PREFIX + r'"reserva \\(48 h\\) \\\"lista\\\" \\+ aviso\\?"' + TEXT_SUFFIX)


def test_text_search_jql_escapes_backslash_twice() -> None:
    """RF-14: `a\\b` → Lucene `a\\\\b` → JQL `a\\\\\\\\b` (cuatro barras en el literal)."""
    assert text_search_jql("DEMO", "a\\b") == TEXT_PREFIX + r'"a\\\\b"' + TEXT_SUFFIX


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('reserva (48 h) "lista" + aviso?', id="mixto"),
        pytest.param('+-&|!(){}[]^~*?:\\/"', id="todos-los-especiales"),
        pytest.param("socio && préstamo || -multa", id="operadores"),
        pytest.param("ruta/a:b\\c", id="barras-y-dos-puntos"),
        pytest.param('\\"\\', id="barra-comilla-barra"),
        pytest.param("ñandú «préstamo» 21 días", id="unicode"),
    ],
)
def test_text_search_jql_round_trips_and_escapes_every_special_char(text: str) -> None:
    """RF-14: el literal decodificado tiene todo especial escapado y reproduce el texto."""
    lucene = decode_text_literal(text_search_jql("DEMO", text))
    assert_all_special_escaped(lucene)
    assert lucene_unescape(lucene) == text


@pytest.mark.parametrize(
    "text",
    [
        'x" OR project = OTRO OR text ~ "y',
        'x\\" OR project = OTRO OR text ~ "y',
        '" ORDER BY key --',
        'x") OR (project = OTRO',
    ],
)
def test_text_search_jql_keeps_injection_inside_single_literal(text: str) -> None:
    """RF-14 (seguridad): el texto no rompe el literal; la JQL sigue limitada al proyecto."""
    jql = text_search_jql("DEMO", text)
    lucene = decode_text_literal(jql)
    assert lucene_unescape(lucene) == text
    assert jql.count('project = "DEMO"') == 1
    assert_all_special_escaped(lucene)


def test_text_search_jql_collapses_whitespace() -> None:
    """RF-14: espacios, tabuladores y saltos de línea se colapsan en un solo espacio."""
    jql = text_search_jql("DEMO", "  renovar \t\n  préstamo   ")
    assert decode_text_literal(jql) == "renovar préstamo"


def test_text_search_jql_truncates_text_to_max_chars() -> None:
    """RF-14 (límite): el texto se recorta a MAX_TEXT_CHARS (200) antes de escapar."""
    assert MAX_TEXT_CHARS == 200
    lucene = decode_text_literal(text_search_jql("DEMO", "a" * 500))
    assert lucene == "a" * MAX_TEXT_CHARS


def test_text_search_jql_keeps_text_when_exactly_max_chars() -> None:
    """RF-14 (límite): 200 caracteres exactos no se recortan."""
    text = "b" * MAX_TEXT_CHARS
    assert decode_text_literal(text_search_jql("DEMO", text)) == text


def test_text_search_jql_truncates_before_escaping_special_chars() -> None:
    """RF-14 (límite): con 300 `?` quedan 200, todos escapados (el escape no se corta)."""
    lucene = decode_text_literal(text_search_jql("DEMO", "?" * 300))
    assert lucene == "\\?" * MAX_TEXT_CHARS


@pytest.mark.parametrize("text", ["", "   ", "\t\n "])
def test_text_search_jql_raises_value_error_when_text_empty(text: str) -> None:
    """RF-14 (error): texto vacío o solo espacios → ValueError."""
    with pytest.raises(ValueError):
        text_search_jql("DEMO", text)


@pytest.mark.parametrize(
    "project", ["demo", "DE MO", 'DEMO"', "DEMO OR project = OTRO", "", "D", "DEMO\n"]
)
def test_text_search_jql_raises_value_error_when_project_invalid(project: str) -> None:
    """RF-14, §11 (error): clave de proyecto no válida → ValueError."""
    with pytest.raises(ValueError):
        text_search_jql(project, "renovar")


def test_text_search_jql_error_message_truncates_long_project() -> None:
    """§11: el mensaje de error no repite entradas arbitrariamente largas."""
    with pytest.raises(ValueError) as info:
        text_search_jql("x" * 500, "renovar")
    assert len(str(info.value)) < 120


# --- core/context/jql: linked_issues_jql -----------------------------------------------------


def test_linked_issues_jql_formats_linked_issues_function() -> None:
    """RF-14: incidencias vinculadas con `issue in linkedIssues(KEY) ORDER BY key`."""
    assert linked_issues_jql("DEMO-3") == "issue in linkedIssues(DEMO-3) ORDER BY key"


@pytest.mark.parametrize(
    "key",
    ["demo-3", "DEMO", "DEMO-", "DEMO-3) OR project = OTRO OR issue in (DEMO-1", "DEMO-3\n", ""],
)
def test_linked_issues_jql_raises_value_error_when_key_invalid(key: str) -> None:
    """RF-14, §11 (error): clave no válida → ValueError, sin construir JQL."""
    with pytest.raises(ValueError):
        linked_issues_jql(key)


@pytest.mark.parametrize("key", ["DEMO-1 OR project = X", "DEMO-1\n", "demo-1"])
def test_children_jql_rejects_invalid_keys(key: str) -> None:
    with pytest.raises(ValueError, match="no válida"):
        children_jql(key)
