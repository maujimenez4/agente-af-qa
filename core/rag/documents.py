"""Tipos de la base de conocimiento: categorías de fuente y documentos ingeridos (RF-07, RF-12).

`SourceClassification` es la salida estructurada del LLM para clasificar una fuente. Es
provisional: se propone moverla a `schemas/`, junto con el enum de categorías (PA-09/PA-10),
en la próxima sincronización.
"""

from typing import Literal

from pydantic import BaseModel, Field

from adapters.errors import AgentError

# Categorías de la presentación del proyecto (T-49, decisiones del día 6).
CATEGORIES: tuple[str, ...] = (
    "productos",  # productos y servicios
    "procesos",  # procesos de negocio
    "politicas",  # políticas y reglas operativas
    "documentacion",  # documentación funcional y técnica
    "glosarios",  # glosarios, catálogos y criterios internos
    "historias",  # HU y artefactos previos
    "pruebas",  # estrategias, matrices y casos de prueba
)
MEMORY_CATEGORY = "memoria"  # reservada para las memorias que genera el agente
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".pdf", ".docx", ".md", ".txt")

Category = Literal[
    "productos",
    "procesos",
    "politicas",
    "documentacion",
    "glosarios",
    "historias",
    "pruebas",
]


class SourceClassification(BaseModel):
    category: Category
    justification: str = Field(min_length=1)


class IngestedDocument(BaseModel):
    """Documento extraído, normalizado y clasificado; corresponde a la tabla `documents`."""

    id: str
    title: str
    category: str
    classified_by: Literal["metadata", "llm"]
    source_path: str
    content_hash: str
    text: str
    metadata: dict[str, str] = {}


class IngestionError(AgentError):
    """No se pudo ingerir un documento; el mensaje está en español para la UI."""
