"""PA-317: el título de la conversación del flujo «HU nueva en una épica».

Solo cambia ese título; el resto queda igual. Claves ficticias del proyecto DEMO.
"""

import pytest

from core.conversations import conversation_title


def test_epic_flow_title_is_hu_nueva_en_la_epica() -> None:
    """Criterio 4: functional + epic → «HU nueva en la épica DEMO-1»."""
    assert conversation_title("functional", "epic", "DEMO-1", "DEMO") == (
        "HU nueva en la épica DEMO-1"
    )


def test_epic_flow_title_without_key_uses_project() -> None:
    """Criterio 4 (límite): sin clave, el título lleva el proyecto."""
    assert conversation_title("functional", "epic", None, "DEMO") == "HU nueva en la épica · DEMO"


@pytest.mark.parametrize(
    ("mode", "kind", "key", "expected"),
    [
        ("functional", "story", "DEMO-3", "Evolucionar DEMO-3"),
        ("functional", "need", None, "Nueva necesidad · DEMO"),
        ("qa", "story", "DEMO-3", "Preparar pruebas de DEMO-3"),
        ("qa", "epic", "DEMO-1", "Conversación DEMO-1"),
    ],
    ids=["evolucionar", "necesidad", "qa", "desconocido"],
)
def test_other_titles_do_not_change(mode: str, kind: str, key: str | None, expected: str) -> None:
    """Criterio 4 (no regresión): los demás títulos no cambian."""
    assert conversation_title(mode, kind, key, "DEMO") == expected
