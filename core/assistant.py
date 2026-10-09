"""Nombre del asistente en los textos del backend (PA-479, PA-480, PA-481; diseño PA-478).

El asistente se llama **FAQ**; **Qaracter** es la marca. Es el mismo nombre que usa la web
(`web/src/text/assistant.ts`). Los textos lo leen al construirse (no al importar el módulo), así
que cambiarlo es cambiar esta línea.
"""

ASSISTANT_NAME = "FAQ"
BRAND = "Qaracter"


def display_name() -> str:
    """Nombre visible con la marca: «FAQ · Qaracter» (pestaña, servidor MCP)."""
    return f"{ASSISTANT_NAME} · {BRAND}"
