"""Mostrar contenido no fiable (Jira, RAG, LLM) como texto.

Nunca va a `st.html` ni a `unsafe_allow_html`. Además se neutraliza el markdown para que un
texto no pueda colar enlaces, imágenes (que cargarían una URL externa) ni formato.
"""

import re

# También `$` (fórmulas), `=` (encabezados setext) y `:` (iconos `:material/…:` y emojis).
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<&$=:])")


def md_escape(text: object) -> str:
    """Texto literal para `st.markdown`: escapa los caracteres con significado en markdown."""
    return _MD_SPECIAL.sub(r"\\\1", str(text))


def md_lines(items: list[str]) -> str:
    """Lista de viñetas con cada elemento escapado."""
    return "\n".join(f"- {md_escape(item)}" for item in items)
