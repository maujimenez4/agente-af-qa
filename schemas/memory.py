"""Memoria sintética de un artefacto publicado (RF-36, RNF-25)."""

from pydantic import BaseModel, Field, PositiveInt

from schemas.common import ArtifactType

_SECTIONS = (
    ("Objetivo", "objective"),
    ("Alcance", "scope"),
    ("Reglas de negocio", "business_rules"),
    ("Decisiones", "decisions"),
    ("Dependencias", "dependencies"),
    ("Cambios", "changes"),
    ("Criterios de aceptación", "acceptance_criteria"),
    ("Referencias", "references"),
)
EMPTY_SECTION = "—"


def escape_line(line: str) -> str:
    """PA-288: una línea del texto del LLM que se confundiría con la estructura de la memoria
    (un `## Título`, un `- elemento`, el «—» de sección vacía o una barra invertida propia) lleva
    una barra invertida delante, como en markdown, para que releerla no parta el campo."""
    if line.startswith(("#", "-", "\\")) or line.strip() == EMPTY_SECTION:
        return "\\" + line
    return line


def unescape_line(line: str) -> str:
    return line[1:] if line.startswith("\\") else line


def _escape(text: str) -> str:
    return "\n".join(escape_line(line) for line in text.split("\n"))


class Memory(BaseModel):
    artifact_type: ArtifactType
    jira_key: str = Field(min_length=1)
    version: PositiveInt
    objective: str
    scope: str
    business_rules: list[str]
    decisions: list[str]
    dependencies: list[str]
    changes: list[str]
    acceptance_criteria: list[str]
    references: list[str]

    def to_markdown(self) -> str:
        """Memoria `data/memory/<JIRA_KEY>.md`, con metadatos en la cabecera para el reindexado."""
        lines = [
            "---",
            f"jira_key: {self.jira_key}",
            f"artifact_type: {self.artifact_type.value}",
            f"version: {self.version}",
            "---",
            "",
            f"# Memoria · {self.jira_key} (v{self.version})",
        ]
        for title, name in _SECTIONS:
            value: str | list[str] = getattr(self, name)
            lines += ["", f"## {title}"]
            if isinstance(value, str):
                lines.append(_escape(value.strip()) or EMPTY_SECTION)
            else:
                lines += [f"- {_escape(item)}" for item in value] or [EMPTY_SECTION]
        return "\n".join(lines) + "\n"
