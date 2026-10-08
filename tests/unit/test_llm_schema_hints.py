"""Esquema JSON que se envía al LLM: `sources` obligatorio en HU y suites (medición 2026-10-02).

La validación pydantic de `schemas/` no cambia: solo el esquema que guía la generación.
"""

import json

import pytest
from pydantic import BaseModel

from adapters.llm.schema_hints import llm_json_schema
from schemas.common import SourceRef
from schemas.impact import ImpactAnalysis
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory


@pytest.mark.parametrize("schema", [UserStory, TestSuite, QualityReport])
def test_cited_schemas_require_at_least_one_source(schema: type[BaseModel]) -> None:
    sent = llm_json_schema(schema)
    assert "sources" in sent["required"]
    assert sent["properties"]["sources"]["minItems"] == 1
    assert "default" not in sent["properties"]["sources"]


@pytest.mark.parametrize("schema", [UserStory, TestSuite, QualityReport])
def test_pydantic_schema_is_not_modified(schema: type[BaseModel]) -> None:
    before = json.dumps(schema.model_json_schema(), sort_keys=True)
    llm_json_schema(schema)
    assert json.dumps(schema.model_json_schema(), sort_keys=True) == before
    assert "sources" not in (schema.model_json_schema().get("required") or [])


class _UncitedWithSources(BaseModel):
    """Esquema ficticio con `sources` que no está en `CITED_SCHEMAS`."""

    summary: str
    sources: list[SourceRef] = []


@pytest.mark.parametrize("schema", [_UncitedWithSources, ImpactAnalysis])
def test_other_schemas_are_sent_unchanged(schema: type[BaseModel]) -> None:
    """Un esquema no citado (aunque tenga `sources`) se envía tal cual. PA-456: `QualityReport`
    ya es citado, así que no sirve para esta prueba."""
    assert llm_json_schema(schema) == schema.model_json_schema()


def test_quality_report_is_cited_and_requires_one_source() -> None:
    """PA-456: el informe de calidad lleva `sources` obligatorio (`minItems: 1`) en el esquema
    enviado y conserva su `maxItems`; la validación pydantic no cambia."""
    sent = llm_json_schema(QualityReport)

    assert "sources" in sent["required"]
    assert sent["properties"]["sources"]["minItems"] == 1
    assert sent["properties"]["sources"]["maxItems"] == 30
    assert "default" not in sent["properties"]["sources"]
    assert "sources" not in (QualityReport.model_json_schema().get("required") or [])


def test_story_without_sources_still_validates() -> None:
    """La validación sigue admitiendo `sources` vacío: las citas las comprueba el núcleo."""
    field = UserStory.model_fields["sources"]
    assert field.default == []
