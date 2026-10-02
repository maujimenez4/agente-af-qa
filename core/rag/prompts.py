"""Carga de prompts versionados desde `prompts/<tarea>.md` (CLAUDE.md, SPEC-00 §8).

Cada archivo empieza con una cabecera YAML con `version:`; el cuerpo es el texto del prompt.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import ROOT_DIR, ConfigError

PROMPTS_DIR = ROOT_DIR / "prompts"
_NAME = re.compile(r"[a-z0-9_]{1,64}")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    if not _NAME.fullmatch(name):  # PA-224: nada de «../»; solo nombres de `prompts/`
        raise ConfigError(f"«{name[:40]}» no es un nombre de prompt válido.")
    path = prompts_dir / f"{name}.md"
    try:
        raw = path.read_text(encoding="utf-8-sig")  # PA-224: un BOM no oculta la cabecera
    except OSError:
        raise ConfigError(f"No se encuentra el prompt «{name}» en {prompts_dir.name}/.") from None
    header, body = _split_header(raw)
    version = header.get("version") if isinstance(header, dict) else None
    if version is None or not str(version).strip():
        raise ConfigError(f"El prompt «{name}» no tiene cabecera con «version:».")
    if not body.strip():  # PA-224: un prompt vacío no llega al LLM
        raise ConfigError(f"El prompt «{name}» no tiene texto después de la cabecera.")
    return Prompt(name=name, version=str(version).strip(), text=body.strip())


def _split_header(raw: str) -> tuple[object, str]:
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    closing = len("\n---\n")
    if end == -1 and text.endswith("\n---"):
        end, closing = len(text) - len("\n---"), len("\n---")
    if end == -1:
        return None, text
    try:
        header = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None, text
    return header, text[end + closing :]
