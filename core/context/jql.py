"""JQL que construye el núcleo para buscar contexto en Jira (T-14, RF-02, RF-14).

Son funciones puras: el núcleo no importa el adaptador de Jira (SPEC-00 §2). El texto que
escribe el usuario siempre pasa por aquí antes de llegar a `IssueTracker.search`.
"""

import re
import unicodedata

_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-[0-9]+$")  # PA-181: solo dígitos ASCII
# PA-168: operadores booleanos de la búsqueda de texto; en el texto libre son palabras.
_TEXT_OPERATORS = re.compile(r"\b(AND|OR|NOT)\b")
# Caracteres especiales de la búsqueda de texto de Jira (sintaxis de Lucene).
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^~*?:\\/"])')
MAX_TEXT_CHARS = 200
MAX_KEYWORDS = 8
MAX_KEYWORD_CHARS = 40
# Palabras vacías frecuentes en las necesidades redactadas como HU («como… quiero… para…»).
_STOPWORDS = frozenset(
    [
        "como",
        "quiero",
        "quieren",
        "para",
        "pueda",
        "puedan",
        "puede",
        "pueden",
        "desde",
        "hasta",
        "sobre",
        "entre",
        "cuando",
        "donde",
        "porque",
        "tambien",
        "también",
        "sistema",
        "usuario",
        "usuaria",
        "persona",
        "personas",
        "socia",
        "socias",
        "socio",
        "socios",
        "poder",
        "tener",
        "hacer",
        "debe",
        "deben",
        "debería",
        "esta",
        "este",
        "estos",
        "estas",
        "cada",
        "todos",
        "todas",
        "otro",
        "otra",
        "ellos",
        "ellas",
        "nuestro",
        "nuestra",
        "mediante",
        "según",
        "sin",
    ]
)


def _validated(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"{what} no válida: {value[:50]!r}.")
    return value


def _quote_text(text: str) -> str:
    """Escapa los caracteres especiales de Lucene y lo encierra entre comillas para JQL."""
    lucene = _LUCENE_SPECIAL.sub(r"\\\1", text)
    return '"' + lucene.replace("\\", "\\\\").replace('"', '\\"') + '"'


def text_search_jql(project: str, text: str) -> str:
    """Búsqueda simple por texto libre en un proyecto (§6.1): `text ~ "…"`.

    «AND», «OR» y «NOT» escritos por la persona son palabras, no operadores (PA-168): en
    minúsculas, la búsqueda de texto de Jira no los interpreta.
    """
    _validated(_PROJECT_KEY, project, "Clave de proyecto")
    normalized = unicodedata.normalize("NFC", text)
    cleaned = _TEXT_OPERATORS.sub(lambda m: m.group(1).lower(), " ".join(normalized.split()))
    cleaned = cleaned[:MAX_TEXT_CHARS]
    if not cleaned:
        raise ValueError("La búsqueda necesita un texto.")
    return f'project = "{project}" AND text ~ {_quote_text(cleaned)} ORDER BY updated DESC'


def keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """Palabras significativas (≥ 4 letras, sin palabras vacías), sin repetir y en orden."""
    seen: list[str] = []
    # PA-180: NFC para que un texto pegado en NFD («pre» + «́» + «stamo») dé las mismas palabras.
    for word in re.findall(r"\w+", unicodedata.normalize("NFC", text).lower()):
        word = word[:MAX_KEYWORD_CHARS]  # PA-170: se recorta antes de comprobar los repetidos
        if len(word) >= 4 and not word.isdigit() and word not in _STOPWORDS and word not in seen:
            seen.append(word)
    return seen[:limit]


def any_keyword_jql(project: str, words: list[str]) -> str:
    """Incidencias que contienen alguna de las palabras (`OR` de la búsqueda de texto)."""
    _validated(_PROJECT_KEY, project, "Clave de proyecto")
    cleaned = [w for w in (" ".join(word.split()) for word in words) if w]
    if not cleaned:
        raise ValueError("La búsqueda necesita al menos una palabra.")
    # Cada palabra se escapa como literal; «OR» es el operador de la búsqueda de texto. PA-169:
    # se añaden términos completos mientras quepan (ni «OR» colgando ni palabras partidas).
    terms = ""
    for word in (w[:MAX_KEYWORD_CHARS] for w in cleaned):
        candidate = f"{terms} OR {word}" if terms else word
        if len(candidate) > MAX_TEXT_CHARS:
            break
        terms = candidate
    return f'project = "{project}" AND text ~ {_quote_text(terms)}'


def linked_issues_jql(key: str) -> str:
    """Incidencias vinculadas a `key` (cualquier tipo de vínculo)."""
    _validated(_ISSUE_KEY, key, "Clave de incidencia")
    return f"issue in linkedIssues({key}) ORDER BY key"
