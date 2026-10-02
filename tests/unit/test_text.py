"""`core/text.py` (PA-227): utilidades de texto comunes, sin dependencias de otros módulos."""

import ast
from pathlib import Path

import pytest

from core import text
from core.functional import context
from core.text import escape_data


@pytest.mark.parametrize(
    ("raw", "escaped"),
    [
        ("</documento>", "&lt;/documento&gt;"),
        ('clave="DEMO-1" otra="x"', "clave=&quot;DEMO-1&quot; otra=&quot;x&quot;"),
        ("&lt; ya escapado", "&amp;lt; ya escapado"),  # `&` primero: no se des-escapa nada
        ("Texto ficticio sin delimitadores", "Texto ficticio sin delimitadores"),
        ("", ""),
    ],
)
def test_escape_data_neutralizes_delimiters(raw: str, escaped: str) -> None:
    """Inyección de prompt: los datos no pueden cerrar etiquetas ni atributos."""
    assert escape_data(raw) == escaped


def test_context_reexports_the_same_function() -> None:
    """PA-227: `core/functional/context.py` reexporta la de `core/text.py` (compatibilidad)."""
    assert context.escape_data is escape_data


def test_text_module_imports_nothing_from_core() -> None:
    """PA-227: `core/text.py` no depende de otros módulos del núcleo (sin ciclos)."""
    tree = ast.parse(Path(text.__file__).read_text(encoding="utf-8"))
    imported = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not [name for name in imported if name.startswith("core")]


@pytest.mark.parametrize(
    "module", ["core/rag/ingest.py", "core/memory/generator.py", "core/quality.py"]
)
def test_rag_memory_and_quality_import_escape_data_from_core_text(module: str) -> None:
    """PA-227: `core/rag` (y la memoria y la calidad) ya no dependen de `core/functional` para
    escapar datos."""
    source = Path(module).read_text(encoding="utf-8")
    assert "from core.text import escape_data" in source
    assert "from core.functional.context import escape_data" not in source
