"""Esquema JSON que se envía al LLM (no cambia la validación de `schemas/`).

Medición con modelos locales (sesión Ollama, 2026-10-02): la gramática de Ollama solo genera las
propiedades `required` del JSON Schema, así que los modelos pequeños omiten `sources` y siempre
necesitan el reintento de citas. Al pedir `sources` con al menos una cita, `qwen3:1.7b` generó una
HU válida a la primera.

Se aplica a las HU, las suites y el informe de calidad (PA-456: si la revisión cae al modelo
local, que tampoco omita las citas). La validación pydantic sigue admitiendo `sources` vacío y las
citas las comprueba `core/functional/citations` contra el contexto real. Si el contexto no trae
ninguna fuente (una necesidad sin resultados del RAG, o con todo excluido), la cita forzada solo
puede ser inventada: el núcleo la quita (`without_forced_citations`) en lugar de dar error.
"""

import copy
from typing import Any

from pydantic import BaseModel

from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

CITED_SCHEMAS: tuple[type[BaseModel], ...] = (UserStory, TestSuite, QualityReport)


def llm_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """`model_json_schema()` con `sources` obligatorio (mínimo 1) en los esquemas citados."""
    json_schema = copy.deepcopy(schema.model_json_schema())
    properties = json_schema.get("properties") or {}
    if not issubclass(schema, CITED_SCHEMAS) or "sources" not in properties:
        return json_schema
    sources = {k: v for k, v in properties["sources"].items() if k != "default"}
    properties["sources"] = sources | {"minItems": 1}
    required = json_schema.setdefault("required", [])
    if "sources" not in required:
        required.append("sources")
    return json_schema
