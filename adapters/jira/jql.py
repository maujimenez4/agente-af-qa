"""Construcción segura de JQL para el adaptador de Jira (T-14, RF-02)."""

import re

PROJECT_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+$")
ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


def quote(value: str) -> str:
    """Literal JQL entre comillas dobles, con `\\` y `"` escapados."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def epics_jql(project: str) -> str:
    # `hierarchyLevel = 1` identifica las épicas sin depender del idioma del tipo de incidencia.
    return f"project = {quote(project)} AND hierarchyLevel = 1 ORDER BY key"


def children_jql(epic_key: str) -> str:
    # La clave va sin comillas en la JQL: se valida aquí para que no se pueda inyectar JQL.
    if not ISSUE_KEY_RE.fullmatch(epic_key):
        raise ValueError(f"Clave de incidencia no válida: {epic_key[:50]!r}.")
    return f"parent = {epic_key} ORDER BY key"
