"""JQL que construye el núcleo para buscar contexto en Jira (T-14, RF-02, RF-14).

Son funciones puras: el núcleo no importa el adaptador de Jira (SPEC-00 §2). El texto que
escribe el usuario siempre pasa por aquí antes de llegar a `IssueTracker.search`.
"""

import re

_PROJECT_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
_ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
# Caracteres especiales de la búsqueda de texto de Jira (sintaxis de Lucene).
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^~*?:\\/"])')
MAX_TEXT_CHARS = 200


def _validated(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.fullmatch(value):
        raise ValueError(f"{what} no válida: {value[:50]!r}.")
    return value


def _quote_text(text: str) -> str:
    """Escapa los caracteres especiales de Lucene y lo encierra entre comillas para JQL."""
    lucene = _LUCENE_SPECIAL.sub(r"\\\1", text)
    return '"' + lucene.replace("\\", "\\\\").replace('"', '\\"') + '"'


def text_search_jql(project: str, text: str) -> str:
    """Búsqueda simple por texto libre en un proyecto (§6.1): `text ~ "…"`."""
    _validated(_PROJECT_KEY, project, "Clave de proyecto")
    cleaned = " ".join(text.split())[:MAX_TEXT_CHARS]
    if not cleaned:
        raise ValueError("La búsqueda necesita un texto.")
    return f'project = "{project}" AND text ~ {_quote_text(cleaned)} ORDER BY updated DESC'


def linked_issues_jql(key: str) -> str:
    """Incidencias vinculadas a `key` (cualquier tipo de vínculo)."""
    _validated(_ISSUE_KEY, key, "Clave de incidencia")
    return f"issue in linkedIssues({key}) ORDER BY key"
