"""Prueba cruzada T-34 (RNF-19): el área A prueba la carga de prompts del área B.

Cubre huecos de `core/rag/prompts.py` que no prueban `test_rag_prompts.py`: BOM, cuerpo vacío,
`version` no escalar, nombres con `../`, cierre de la cabecera con espacios y CRLF.
Ninguno se marca `xfail`: se fijan como comportamiento y la propuesta de corrección (BOM, cuerpo
vacío y `../`) es PA-224; al corregirla, invertir estas pruebas. Datos ficticios.
"""

from pathlib import Path

import pytest

from core.config import ConfigError
from core.rag.prompts import load_prompt


def _write(directory: Path, name: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_bytes(content.encode("utf-8"))
    return path


def test_load_prompt_raises_config_error_when_file_starts_with_bom(tmp_path: Path) -> None:
    """CLAUDE.md (comportamiento fijado): con BOM la cabecera no se reconoce y falla en alto.

    El mensaje dice que falta «version:», aunque la cabecera exista tras el BOM.
    """
    _write(tmp_path, "con_bom", "﻿---\nversion: 1\n---\n\nCuerpo ficticio.")

    with pytest.raises(ConfigError, match="no tiene cabecera"):
        load_prompt("con_bom", tmp_path)


def test_load_prompt_returns_empty_text_when_body_is_empty(tmp_path: Path) -> None:
    """CLAUDE.md (comportamiento fijado): un prompt sin cuerpo se carga con texto vacío."""
    _write(tmp_path, "vacio", "---\nversion: 1\n---\n\n   \n")

    prompt = load_prompt("vacio", tmp_path)

    assert (prompt.version, prompt.text) == ("1", "")


def test_load_prompt_returns_empty_text_when_header_closes_at_end(tmp_path: Path) -> None:
    """CLAUDE.md (límite): la cabecera cerrada al final del archivo da cuerpo vacío."""
    _write(tmp_path, "solo_cabecera", "---\nversion: 2\n---")

    assert load_prompt("solo_cabecera", tmp_path).text == ""


@pytest.mark.parametrize(
    ("raw_version", "expected"),
    [("[1, 2]", "[1, 2]"), ("{mayor: 1}", "{'mayor': 1}"), ("false", "False"), ("0", "0")],
)
def test_load_prompt_stringifies_version_when_it_is_not_a_plain_string(
    tmp_path: Path, raw_version: str, expected: str
) -> None:
    """CLAUDE.md (comportamiento fijado): una `version` no escalar o falsa se acepta como str."""
    _write(tmp_path, "version_rara", f"---\nversion: {raw_version}\n---\n\nCuerpo ficticio.")

    assert load_prompt("version_rara", tmp_path).version == expected


def test_load_prompt_reads_outside_prompts_dir_when_name_has_parent_segments(
    tmp_path: Path,
) -> None:
    """CLAUDE.md (comportamiento fijado): el nombre no se valida; '../x' sale de la carpeta.

    Los nombres son constantes del código, no entrada del usuario.
    """
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    _write(tmp_path, "fuera", "---\nversion: 1\n---\n\nPrompt ficticio fuera de la carpeta.")

    prompt = load_prompt("../fuera", prompts_dir)

    assert prompt.text == "Prompt ficticio fuera de la carpeta."


def test_load_prompt_raises_config_error_when_closing_line_has_trailing_space(
    tmp_path: Path,
) -> None:
    """CLAUDE.md (comportamiento fijado): «--- » con espacio final no cierra la cabecera."""
    _write(tmp_path, "cierre", "---\nversion: 1\n--- \n\nCuerpo ficticio.")

    with pytest.raises(ConfigError, match="«cierre»"):
        load_prompt("cierre", tmp_path)


def test_load_prompt_parses_header_when_file_uses_crlf(tmp_path: Path) -> None:
    """CLAUDE.md: los saltos CRLF (Windows) no impiden leer la cabecera."""
    _write(tmp_path, "crlf", "---\r\nversion: 4\r\n---\r\n\r\nCuerpo ficticio.\r\n")

    prompt = load_prompt("crlf", tmp_path)

    assert (prompt.version, prompt.text) == ("4", "Cuerpo ficticio.")


def test_load_prompt_raises_config_error_when_header_is_a_list(tmp_path: Path) -> None:
    """CLAUDE.md (negativa): una cabecera YAML que no es un mapa no tiene «version:»."""
    _write(tmp_path, "lista", "---\n- version\n- 1\n---\n\nCuerpo ficticio.")

    with pytest.raises(ConfigError, match="version"):
        load_prompt("lista", tmp_path)


def test_load_prompt_keeps_inner_separator_when_body_contains_dashes(tmp_path: Path) -> None:
    """CLAUDE.md: solo el primer '---' cierra la cabecera; los siguientes son del cuerpo."""
    _write(tmp_path, "guiones", "---\nversion: 1\n---\n\nAntes\n---\nDespués")

    assert load_prompt("guiones", tmp_path).text == "Antes\n---\nDespués"
