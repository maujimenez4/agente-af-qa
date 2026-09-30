"""Carga de prompts versionados desde `prompts/<tarea>.md` (CLAUDE.md, SPEC-00 §8).

Cada archivo empieza con una cabecera YAML con `version:`; el cuerpo es el texto del prompt.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

from core.config import ROOT_DIR, ConfigError

PROMPTS_DIR = ROOT_DIR / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str


def load_prompt(name: str, prompts_dir: Path = PROMPTS_DIR) -> Prompt:
    path = prompts_dir / f"{name}.md"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise ConfigError(f"No se encuentra el prompt «{name}» en {prompts_dir.name}/.") from None
    header, body = _split_header(raw)
    version = header.get("version") if isinstance(header, dict) else None
    if version is None or not str(version).strip():
        raise ConfigError(f"El prompt «{name}» no tiene cabecera con «version:».")
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
