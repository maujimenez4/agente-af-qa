"""Esquema JSON que se envía al LLM: `sources` obligatorio en HU y suites (medición 2026-10-02).

La validación pydantic de `schemas/` no cambia: solo el esquema que guía la generación.
"""

import json

import pytest
from pydantic import BaseModel

from adapters.llm.schema_hints import llm_json_schema
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory


@pytest.mark.parametrize("schema", [UserStory, TestSuite])
def test_cited_schemas_require_at_least_one_source(schema: type[BaseModel]) -> None:
    sent = llm_json_schema(schema)
    assert "sources" in sent["required"]
    assert sent["properties"]["sources"]["minItems"] == 1
    assert "default" not in sent["properties"]["sources"]


@pytest.mark.parametrize("schema", [UserStory, TestSuite])
def test_pydantic_schema_is_not_modified(schema: type[BaseModel]) -> None:
    before = json.dumps(schema.model_json_schema(), sort_keys=True)
    llm_json_schema(schema)
    assert json.dumps(schema.model_json_schema(), sort_keys=True) == before
    assert "sources" not in (schema.model_json_schema().get("required") or [])


def test_other_schemas_are_sent_unchanged() -> None:
    """El informe de calidad puede no citar nada: su esquema no cambia."""
    assert llm_json_schema(QualityReport) == QualityReport.model_json_schema()


def test_story_without_sources_still_validates() -> None:
    """La validación sigue admitiendo `sources` vacío: las citas las comprueba el núcleo."""
    field = UserStory.model_fields["sources"]
    assert field.default == []
