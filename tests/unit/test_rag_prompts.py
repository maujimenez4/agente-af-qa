"""Pruebas del cargador de prompts versionados (T-12, RF-12; convención `prompts/<tarea>.md`)."""

import dataclasses
from pathlib import Path

import pytest

from core.config import ConfigError
from core.rag.prompts import PROMPTS_DIR, Prompt, load_prompt

ROOT = Path(__file__).resolve().parents[2]


def _write(directory: Path, name: str, content: str) -> Path:
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_prompts_dir_points_to_repo_prompts_folder() -> None:
    """RF-12 · PROMPTS_DIR apunta a `<raíz>/prompts`."""
    assert PROMPTS_DIR.resolve() == (ROOT / "prompts").resolve()


def test_load_prompt_returns_name_version_and_body_when_header_is_valid(tmp_path: Path) -> None:
    """RF-12 · Devuelve nombre, versión como str y el cuerpo sin cabecera ni espacios extremos."""
    _write(
        tmp_path,
        "clasificar_prueba",
        "---\nversion: 1\ndescription: Prompt ficticio\n---\n\n"
        "  Clasifica documentos de la Biblioteca de Villaficticia.\n\nResponde en JSON.  \n\n",
    )

    prompt = load_prompt("clasificar_prueba", prompts_dir=tmp_path)

    assert prompt == Prompt(
        name="clasificar_prueba",
        version="1",
        text="Clasifica documentos de la Biblioteca de Villaficticia.\n\nResponde en JSON.",
    )


def test_load_prompt_keeps_version_as_string_when_version_is_textual(tmp_path: Path) -> None:
    """RF-12 · Una versión textual (p. ej. "1.2") se conserva tal cual como str."""
    _write(tmp_path, "tarea_ficticia", '---\nversion: "1.2"\n---\nCuerpo ficticio.\n')

    prompt = load_prompt("tarea_ficticia", prompts_dir=tmp_path)

    assert prompt.version == "1.2"
    assert isinstance(prompt.version, str)


def test_load_prompt_body_does_not_include_header(tmp_path: Path) -> None:
    """RF-12 · El texto devuelto no incluye la cabecera YAML ni sus delimitadores."""
    _write(tmp_path, "sin_fuga", "---\nversion: 3\nautor: equipo-ficticio\n---\nSolo el cuerpo.")

    prompt = load_prompt("sin_fuga", prompts_dir=tmp_path)

    assert prompt.text == "Solo el cuerpo."
    assert "version" not in prompt.text
    assert "---" not in prompt.text


def test_prompt_is_immutable() -> None:
    """RF-12 · Prompt es un dataclass congelado."""
    prompt = Prompt(name="x", version="1", text="Texto ficticio")

    with pytest.raises(dataclasses.FrozenInstanceError):
        prompt.version = "2"  # type: ignore[misc]


def test_load_prompt_raises_config_error_when_file_is_missing(tmp_path: Path) -> None:
    """RF-12 · Archivo inexistente → ConfigError en español que menciona el nombre."""
    with pytest.raises(ConfigError) as exc_info:
        load_prompt("prompt_inexistente", prompts_dir=tmp_path)

    assert "prompt_inexistente" in str(exc_info.value)


def test_load_prompt_raises_config_error_when_header_is_missing(tmp_path: Path) -> None:
    """RF-12 · Archivo sin cabecera YAML → ConfigError que menciona el nombre."""
    _write(tmp_path, "sin_cabecera", "Clasifica el documento ficticio.\n")

    with pytest.raises(ConfigError) as exc_info:
        load_prompt("sin_cabecera", prompts_dir=tmp_path)

    assert "sin_cabecera" in str(exc_info.value)


def test_load_prompt_raises_config_error_when_header_is_not_closed(tmp_path: Path) -> None:
    """RF-12 · Cabecera abierta sin cierre `---` se trata como ausente → ConfigError."""
    _write(tmp_path, "sin_cierre", "---\nversion: 1\nCuerpo sin cierre de cabecera.\n")

    with pytest.raises(ConfigError) as exc_info:
        load_prompt("sin_cierre", prompts_dir=tmp_path)

    assert "sin_cierre" in str(exc_info.value)


def test_load_prompt_raises_config_error_when_version_is_missing(tmp_path: Path) -> None:
    """RF-12 · Cabecera sin `version` → ConfigError que menciona el nombre."""
    _write(tmp_path, "sin_version", "---\ndescription: Prompt ficticio\n---\nCuerpo.\n")

    with pytest.raises(ConfigError) as exc_info:
        load_prompt("sin_version", prompts_dir=tmp_path)

    assert "sin_version" in str(exc_info.value)


def test_load_prompt_raises_config_error_when_version_is_empty(tmp_path: Path) -> None:
    """RF-12 · `version:` vacío (null en YAML) cuenta como ausente → ConfigError."""
    _write(tmp_path, "version_vacia", "---\nversion:\n---\nCuerpo.\n")

    with pytest.raises(ConfigError) as exc_info:
        load_prompt("version_vacia", prompts_dir=tmp_path)

    assert "version_vacia" in str(exc_info.value)


def test_load_prompt_raises_config_error_when_header_yaml_is_invalid(tmp_path: Path) -> None:
    """RF-12 · Cabecera con YAML inválido → ConfigError (no yaml.YAMLError)."""
    _write(tmp_path, "yaml_roto", "---\nversion: [1\n---\nCuerpo.\n")

    with pytest.raises(ConfigError) as exc_info:
        load_prompt("yaml_roto", prompts_dir=tmp_path)

    assert "yaml_roto" in str(exc_info.value)


def test_classify_source_prompt_exists_with_version() -> None:
    """RF-12 · El prompt real `prompts/classify_source.md` existe, tiene versión y cuerpo."""
    prompt = load_prompt("classify_source")

    assert prompt.name == "classify_source"
    assert prompt.version.strip()
    assert prompt.text.strip()
