"""Prueba cruzada T-34 (RNF-19): el área A prueba la carga de prompts del área B.

Cubre huecos de `core/rag/prompts.py` que no prueban `test_rag_prompts.py`: BOM, cuerpo vacío,
`version` no escalar, nombres con `../`, cierre de la cabecera con espacios y CRLF.
El BOM, el cuerpo vacío y los nombres con `../` se corrigieron en PA-224; lo demás se fija como
comportamiento. Datos ficticios.
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


def test_load_prompt_reads_header_when_file_starts_with_bom(tmp_path: Path) -> None:
    """PA-224: un BOM inicial no oculta la cabecera (se lee con `utf-8-sig`)."""
    _write(tmp_path, "con_bom", "﻿---\nversion: 1\n---\n\nCuerpo ficticio.")

    prompt = load_prompt("con_bom", tmp_path)

    assert (prompt.version, prompt.text) == ("1", "Cuerpo ficticio.")


def test_load_prompt_raises_config_error_when_body_is_empty(tmp_path: Path) -> None:
    """PA-224: un prompt sin texto tras la cabecera no se carga (no llegaría nada al LLM)."""
    _write(tmp_path, "vacio", "---\nversion: 1\n---\n\n   \n")

    with pytest.raises(ConfigError, match="no tiene texto"):
        load_prompt("vacio", tmp_path)


def test_load_prompt_raises_config_error_when_header_closes_at_end(tmp_path: Path) -> None:
    """PA-224 (límite): la cabecera cerrada al final del archivo deja el cuerpo vacío: error."""
    _write(tmp_path, "solo_cabecera", "---\nversion: 2\n---")

    with pytest.raises(ConfigError, match="no tiene texto"):
        load_prompt("solo_cabecera", tmp_path)


@pytest.mark.parametrize("name", ["../fuera", "sub/dir", "Mayusculas", "con-guion", "", "x" * 65])
def test_load_prompt_rejects_invalid_name_without_reading(tmp_path: Path, name: str) -> None:
    """PA-224: el nombre debe ser `[a-z0-9_]` (hasta 64); «../x» no sale de `prompts/`."""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    _write(tmp_path, "fuera", "---\nversion: 1\n---\n\nPrompt ficticio fuera de la carpeta.")

    with pytest.raises(ConfigError, match="no es un nombre de prompt válido"):
        load_prompt(name, prompts_dir)


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
