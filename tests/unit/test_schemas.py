"""Pruebas de schemas/ (T-05 · SPEC-00 §3 · CA-00-02).

Dominio ficticio: el servicio de préstamos de una biblioteca municipal inventada.
Claves de Jira ficticias del tipo "DEMO-1".
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from schemas import (
    AcceptanceCriterion,
    Artifact,
    ArtifactStatus,
    ArtifactType,
    BusinessRule,
    ImpactAnalysis,
    ImpactItem,
    Memory,
    Priority,
    SourceRef,
    StoryDiff,
    TestCase,
    TestCaseType,
    TestStep,
    TestSuite,
    UserStory,
)

# --------------------------------------------------------------------------- builders


def make_criterion(id_: str = "CA-1", **overrides: Any) -> AcceptanceCriterion:
    data: dict[str, Any] = {
        "id": id_,
        "title": "Préstamo de un libro disponible",
        "given": ["un socio ficticio con carné activo"],
        "when": ["solicita el préstamo de un libro disponible"],
        "then": ["el sistema registra el préstamo durante 15 días"],
    }
    data.update(overrides)
    return AcceptanceCriterion(**data)


def make_rule(id_: str = "RN-1", **overrides: Any) -> BusinessRule:
    data: dict[str, Any] = {"id": id_, "description": "Máximo de 3 préstamos simultáneos"}
    data.update(overrides)
    return BusinessRule(**data)


def story_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "internal_id": "HU-01",
        "jira_key": "DEMO-1",
        "title": "Préstamo de libros en la Biblioteca Ficticia",
        "role": "socio de la biblioteca",
        "action": "reservar un libro desde la web",
        "benefit": "no tener que desplazarme para comprobar su disponibilidad",
        "description": "Descripción ficticia de la funcionalidad de préstamo.",
        "business_goal": "Aumentar los préstamos en la biblioteca ficticia",
        "scope_includes": ["reserva de libros"],
        "scope_excludes": ["pago de multas"],
        "acceptance_criteria": [make_criterion("CA-1"), make_criterion("CA-2")],
        "business_rules": [make_rule("RN-1")],
        "assumptions": [],
        "constraints": [],
        "dependencies": [],
        "alternate_flows": [],
        "exceptions": [],
        "related_features": [],
        "priority": Priority.MUST,
    }
    data.update(overrides)
    return data


def make_story(**overrides: Any) -> UserStory:
    return UserStory(**story_data(**overrides))


def make_step(**overrides: Any) -> TestStep:
    data: dict[str, Any] = {
        "action": "Solicitar el préstamo del libro ficticio",
        "data": "ISBN 000-0-00-000000-0",
        "expected": "Se muestra la confirmación del préstamo",
    }
    data.update(overrides)
    return TestStep(**data)


def case_data(internal_id: str = "CP-1", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "internal_id": internal_id,
        "title": "Préstamo correcto",
        "criterion_ids": ["CA-1"],
        "rule_ids": [],
        "type": TestCaseType.POSITIVE,
        "preconditions": ["socio ficticio dado de alta"],
        "steps": [make_step()],
        "priority": Priority.SHOULD,
    }
    data.update(overrides)
    return data


def make_case(internal_id: str = "CP-1", **overrides: Any) -> TestCase:
    return TestCase(**case_data(internal_id, **overrides))


def make_suite(cases: list[TestCase] | None = None, **overrides: Any) -> TestSuite:
    data: dict[str, Any] = {
        "story_jira_key": "DEMO-1",
        "cases": cases if cases is not None else [make_case()],
        "strategy_md": "# Estrategia\n\nPruebas funcionales del préstamo ficticio.",
    }
    data.update(overrides)
    return TestSuite(**data)


def make_memory(**overrides: Any) -> Memory:
    data: dict[str, Any] = {
        "artifact_type": ArtifactType.USER_STORY,
        "jira_key": "DEMO-1",
        "version": 2,
        "objective": "Permitir reservas en la biblioteca ficticia",
        "scope": "Reserva web de libros",
        "business_rules": ["RN-1: máximo 3 préstamos"],
        "decisions": ["Plazo de 15 días"],
        "dependencies": ["DEMO-2"],
        "changes": ["Se añade la reserva web"],
        "acceptance_criteria": ["CA-1: préstamo de un libro disponible"],
        "references": ["DEMO-1"],
    }
    data.update(overrides)
    return Memory(**data)


def artifact_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": uuid4(),
        "type": ArtifactType.USER_STORY,
        "status": ArtifactStatus.DRAFT,
        "version": 1,
        "origin_key": "DEMO-1",
        "content": make_story(),
        "created_by": "usuario-ficticio",
    }
    data.update(overrides)
    return data


# --------------------------------------------------------------------------- enums


def test_enums_have_expected_values_when_listed() -> None:
    """CA-00-02: los enums exponen los valores de la SPEC-00 §3."""
    assert [p.value for p in Priority] == ["Must", "Should", "Could", "Won't"]
    assert [s.value for s in ArtifactStatus] == [
        "draft",
        "in_review",
        "approved",
        "published",
        "discarded",
    ]
    assert [t.value for t in ArtifactType] == ["user_story", "test_suite"]
    assert [t.value for t in TestCaseType] == ["positivo", "negativo", "alterno", "excepcion"]


def test_priority_accepts_string_value_when_parsing() -> None:
    """CA-00-02: un enum se valida a partir de su valor de texto."""
    story = UserStory(**story_data(priority="Won't"))
    assert story.priority is Priority.WONT


def test_priority_rejects_unknown_value_when_parsing() -> None:
    """CA-00-02: un valor fuera del enum es rechazado."""
    with pytest.raises(ValidationError):
        UserStory(**story_data(priority="Urgente"))


def test_test_case_type_rejects_unknown_value_when_parsing() -> None:
    """CA-00-02: tipo de caso fuera del enum es rechazado."""
    with pytest.raises(ValidationError):
        TestCase(**case_data(type="humo"))


# --------------------------------------------------------------------------- SourceRef


@pytest.mark.parametrize("kind", ["jira", "rag", "memory"])
def test_source_ref_accepts_kind_when_valid(kind: str) -> None:
    """CA-00-02: SourceRef acepta los tres tipos de fuente."""
    ref = SourceRef(kind=kind, ref="DEMO-1")
    assert ref.kind == kind
    assert ref.excerpt is None


def test_source_ref_rejects_kind_when_unknown() -> None:
    """CA-00-02: tipo de fuente no permitido."""
    with pytest.raises(ValidationError):
        SourceRef(kind="web", ref="DEMO-1")


def test_source_ref_rejects_ref_when_empty() -> None:
    """CA-00-02: la referencia no puede estar vacía."""
    with pytest.raises(ValidationError):
        SourceRef(kind="jira", ref="")


# ------------------------------------------------------- AcceptanceCriterion / BusinessRule


@pytest.mark.parametrize("id_", ["CA-1", "CA-01", "CA-123"])
def test_criterion_accepts_id_when_pattern_matches(id_: str) -> None:
    """CA-00-02: patrón CA-<n> válido."""
    assert make_criterion(id_).id == id_


@pytest.mark.parametrize("id_", ["CA1", "ca-1", "CA-", "CA-1a", "RN-1", "CP-1", " CA-1", ""])
def test_criterion_rejects_id_when_pattern_mismatch(id_: str) -> None:
    """CA-00-02: patrón CA-<n> inválido."""
    with pytest.raises(ValidationError):
        make_criterion(id_)


@pytest.mark.parametrize("field", ["given", "when", "then"])
def test_criterion_rejects_gherkin_list_when_empty(field: str) -> None:
    """CA-00-02: given/when/then requieren al menos un elemento."""
    with pytest.raises(ValidationError):
        make_criterion(**{field: []})


def test_criterion_rejects_title_when_empty() -> None:
    """CA-00-02: el título del CA es obligatorio y no vacío."""
    with pytest.raises(ValidationError):
        make_criterion(title="")


@pytest.mark.parametrize("id_", ["RN-1", "RN-07"])
def test_rule_accepts_id_when_pattern_matches(id_: str) -> None:
    """CA-00-02: patrón RN-<n> válido."""
    assert make_rule(id_).id == id_


@pytest.mark.parametrize("id_", ["RN1", "rn-1", "CA-1", "RN-x"])
def test_rule_rejects_id_when_pattern_mismatch(id_: str) -> None:
    """CA-00-02: patrón RN-<n> inválido."""
    with pytest.raises(ValidationError):
        make_rule(id_)


def test_rule_rejects_description_when_empty() -> None:
    """CA-00-02: la descripción de la RN no puede estar vacía."""
    with pytest.raises(ValidationError):
        make_rule(description="")


# --------------------------------------------------------------------------- UserStory


def test_user_story_builds_when_data_valid() -> None:
    """CA-00-02: HU válida con valores por defecto para los campos opcionales."""
    story = make_story()
    assert story.jira_key == "DEMO-1"
    assert story.changes_from_previous == []
    assert story.related_requirements == []
    assert story.sources == []
    assert story.open_questions == []


def test_user_story_accepts_missing_optional_keys_when_new() -> None:
    """CA-00-02: una HU nueva aún no tiene internal_id ni jira_key."""
    data = story_data()
    del data["internal_id"], data["jira_key"]
    story = UserStory(**data)
    assert story.internal_id is None
    assert story.jira_key is None


@pytest.mark.parametrize(
    "field",
    [
        "title",
        "role",
        "action",
        "benefit",
        "description",
        "business_goal",
        "scope_includes",
        "scope_excludes",
        "acceptance_criteria",
        "business_rules",
        "assumptions",
        "constraints",
        "dependencies",
        "alternate_flows",
        "exceptions",
        "related_features",
        "priority",
    ],
)
def test_user_story_rejects_when_required_field_missing(field: str) -> None:
    """CA-00-02: todos los campos obligatorios de la plantilla de HU."""
    data = story_data()
    del data[field]
    with pytest.raises(ValidationError) as exc:
        UserStory(**data)
    assert any(err["loc"] == (field,) for err in exc.value.errors())


def test_user_story_rejects_title_when_empty() -> None:
    """CA-00-02: el título de la HU no puede estar vacío."""
    with pytest.raises(ValidationError):
        make_story(title="")


def test_user_story_rejects_criteria_when_empty_list() -> None:
    """CA-00-02: una HU necesita al menos un CA."""
    with pytest.raises(ValidationError):
        make_story(acceptance_criteria=[])


def test_user_story_accepts_rules_when_empty_list() -> None:
    """CA-00-02 (límite): una HU puede no tener RN."""
    assert make_story(business_rules=[]).business_rules == []


def test_user_story_rejects_when_criterion_ids_repeated() -> None:
    """CA-00-02: IDs de CA repetidos."""
    with pytest.raises(ValidationError, match="IDs repetidos en la HU: CA-1"):
        make_story(acceptance_criteria=[make_criterion("CA-1"), make_criterion("CA-1")])


def test_user_story_rejects_when_rule_ids_repeated() -> None:
    """CA-00-02: IDs de RN repetidos."""
    with pytest.raises(ValidationError, match="RN-2"):
        make_story(business_rules=[make_rule("RN-2"), make_rule("RN-2")])


def test_user_story_reports_all_repeated_ids_when_several() -> None:
    """CA-00-02: el error enumera todos los IDs repetidos."""
    with pytest.raises(ValidationError) as exc:
        make_story(
            acceptance_criteria=[make_criterion("CA-1"), make_criterion("CA-1")],
            business_rules=[make_rule("RN-1"), make_rule("RN-1")],
        )
    assert "CA-1, RN-1" in str(exc.value)


def test_user_story_rejects_when_nested_criterion_invalid() -> None:
    """CA-00-02: la validación se propaga a los CA anidados."""
    bad = {"id": "CA-X", "title": "t", "given": ["g"], "when": ["w"], "then": ["t"]}
    with pytest.raises(ValidationError):
        UserStory(**story_data(acceptance_criteria=[bad]))


# --------------------------------------------------------------------------- TestStep / TestCase


def test_test_step_accepts_data_when_missing() -> None:
    """CA-00-02: el dato del paso es opcional."""
    assert TestStep(action="Abrir el catálogo", expected="Se muestra el catálogo").data is None


@pytest.mark.parametrize("field", ["action", "expected"])
def test_test_step_rejects_when_text_empty(field: str) -> None:
    """CA-00-02: acción y resultado esperado no vacíos."""
    with pytest.raises(ValidationError):
        make_step(**{field: ""})


def test_test_case_builds_when_data_valid() -> None:
    """CA-00-02: caso válido con valores por defecto."""
    case = TestCase(**{k: v for k, v in case_data().items() if k != "rule_ids"})
    assert case.rule_ids == []
    assert case.gherkin is None


@pytest.mark.parametrize("internal_id", ["CP1", "cp-1", "CA-1", "CP-", "CP-01b"])
def test_test_case_rejects_internal_id_when_pattern_mismatch(internal_id: str) -> None:
    """CA-00-02: patrón CP-<n> inválido."""
    with pytest.raises(ValidationError):
        make_case(internal_id)


@pytest.mark.parametrize("internal_id", ["CP-1", "CP-01", "CP-999"])
def test_test_case_accepts_internal_id_when_pattern_matches(internal_id: str) -> None:
    """CA-00-02: patrón CP-<n> válido."""
    assert make_case(internal_id).internal_id == internal_id


def test_test_case_rejects_criteria_when_empty_list() -> None:
    """CA-00-02: un caso debe vincular al menos un CA."""
    with pytest.raises(ValidationError):
        make_case(criterion_ids=[])


def test_test_case_rejects_steps_when_empty_list() -> None:
    """CA-00-02: un caso necesita al menos un paso."""
    with pytest.raises(ValidationError):
        make_case(steps=[])


def test_test_case_rejects_when_criterion_reference_invalid() -> None:
    """CA-00-02: referencia a CA con patrón inválido; el mensaje cita el caso y el ID."""
    with pytest.raises(ValidationError, match="CP-3: referencias no válidas a CA/RN: RN-1"):
        make_case("CP-3", criterion_ids=["CA-1", "RN-1"])


def test_test_case_rejects_when_rule_reference_invalid() -> None:
    """CA-00-02: referencia a RN con patrón inválido."""
    with pytest.raises(ValidationError, match="CA-9"):
        make_case(rule_ids=["CA-9"])


@pytest.mark.parametrize("field", ["internal_id", "title", "type", "preconditions", "priority"])
def test_test_case_rejects_when_required_field_missing(field: str) -> None:
    """CA-00-02: campos obligatorios del caso."""
    data = case_data()
    del data[field]
    with pytest.raises(ValidationError):
        TestCase(**data)


# --------------------------------------------------------------------------- TestSuite


def test_test_suite_builds_when_data_valid() -> None:
    """CA-00-02: suite válida con valores por defecto."""
    suite = make_suite()
    assert suite.synthetic_data == []
    assert suite.risks == suite.dependencies == suite.impact_areas == []
    assert suite.sources == []


def test_test_suite_rejects_cases_when_empty_list() -> None:
    """CA-00-02: una suite necesita al menos un caso."""
    with pytest.raises(ValidationError):
        make_suite(cases=[])


def test_test_suite_rejects_story_key_when_empty() -> None:
    """CA-00-02: la suite referencia la HU de origen (trazabilidad)."""
    with pytest.raises(ValidationError):
        make_suite(story_jira_key="")


def test_test_suite_rejects_when_case_ids_repeated() -> None:
    """CA-00-02: IDs de caso repetidos."""
    with pytest.raises(ValidationError, match="IDs de caso repetidos: CP-1"):
        make_suite(cases=[make_case("CP-1"), make_case("CP-1")])


def test_coverage_maps_references_to_cases_when_computed() -> None:
    """CA-00-02: matriz CA/RN → CP calculada a partir de los casos (RF-24)."""
    suite = make_suite(
        cases=[
            make_case("CP-1", criterion_ids=["CA-1"], rule_ids=["RN-1"]),
            make_case("CP-2", criterion_ids=["CA-1", "CA-2"]),
        ]
    )
    assert suite.coverage() == {"CA-1": ["CP-1", "CP-2"], "CA-2": ["CP-2"], "RN-1": ["CP-1"]}


def test_coverage_orders_criteria_before_rules_when_mixed() -> None:
    """CA-00-02: los CA van antes que las RN aunque aparezcan después."""
    suite = make_suite(cases=[make_case("CP-1", criterion_ids=["CA-5"], rule_ids=["RN-1"])])
    suite2 = make_suite(
        cases=[
            make_case("CP-1", criterion_ids=["CA-9"], rule_ids=["RN-1", "RN-2"]),
            make_case("CP-2", criterion_ids=["CA-1"]),
        ]
    )
    assert list(suite.coverage()) == ["CA-5", "RN-1"]
    assert list(suite2.coverage()) == ["CA-1", "CA-9", "RN-1", "RN-2"]


def test_coverage_orders_numerically_when_multi_digit() -> None:
    """CA-00-02 (límite): CA-2 antes que CA-10 y CP-2 antes que CP-10."""
    suite = make_suite(
        cases=[
            make_case("CP-10", criterion_ids=["CA-10", "CA-2"], rule_ids=["RN-10"]),
            make_case("CP-2", criterion_ids=["CA-10"], rule_ids=["RN-3"]),
        ]
    )
    coverage = suite.coverage()
    assert list(coverage) == ["CA-2", "CA-10", "RN-3", "RN-10"]
    assert coverage["CA-10"] == ["CP-2", "CP-10"]


def test_coverage_has_no_duplicates_when_reference_repeated_in_case() -> None:
    """CA-00-02 (límite): un caso que repite una referencia aparece una sola vez."""
    suite = make_suite(cases=[make_case("CP-1", criterion_ids=["CA-1", "CA-1"])])
    assert suite.coverage() == {"CA-1": ["CP-1"]}


def test_coverage_md_contains_header_and_rows_when_rendered() -> None:
    """CA-00-02: la matriz en Markdown incluye la clave de la HU y una fila por CA/RN."""
    suite = make_suite(
        story_jira_key="DEMO-7",
        cases=[
            make_case("CP-1", criterion_ids=["CA-1"], rule_ids=["RN-1"]),
            make_case("CP-2", criterion_ids=["CA-1"]),
        ],
    )
    md = suite.coverage_md()
    lines = md.splitlines()
    assert lines[0] == "# Matriz de cobertura · DEMO-7"
    assert lines[2] == "| CA/RN | Casos de prueba | Nº |"
    assert lines[3] == "|---|---|---|"
    assert lines[4:] == ["| CA-1 | CP-1, CP-2 | 2 |", "| RN-1 | CP-1 | 1 |"]
    assert md.endswith("\n")


# --------------------------------------------------------------------------- Impact


def test_impact_analysis_builds_when_data_valid() -> None:
    """CA-00-02: análisis de impacto válido (RF-19)."""
    impact = ImpactAnalysis(
        diffs=[StoryDiff(field="title", before="Antes", after="Después")],
        affected=[ImpactItem(jira_key="DEMO-2", reason="Comparte la RN-1", kind="rule")],
        regression_notes=["Revisar devoluciones ficticias"],
    )
    assert impact.affected[0].kind == "rule"


def test_story_diff_accepts_none_when_field_added_or_removed() -> None:
    """CA-00-02 (límite): before/after admiten None."""
    diff = StoryDiff(field="scope", before=None, after=None)
    assert diff.before is None and diff.after is None


def test_story_diff_rejects_field_when_empty() -> None:
    """CA-00-02: nombre de campo obligatorio."""
    with pytest.raises(ValidationError):
        StoryDiff(field="", before="a", after="b")


def test_impact_item_rejects_kind_when_unknown() -> None:
    """CA-00-02: tipo de impacto fuera del Literal."""
    with pytest.raises(ValidationError):
        ImpactItem(jira_key="DEMO-2", reason="motivo", kind="epic")


@pytest.mark.parametrize("field", ["jira_key", "reason"])
def test_impact_item_rejects_when_text_empty(field: str) -> None:
    """CA-00-02: clave y motivo no vacíos."""
    data = {"jira_key": "DEMO-2", "reason": "motivo", "kind": "story", field: ""}
    with pytest.raises(ValidationError):
        ImpactItem(**data)


# --------------------------------------------------------------------------- Memory


def test_memory_rejects_version_when_not_positive() -> None:
    """CA-00-02 (límite): la versión es un entero positivo."""
    with pytest.raises(ValidationError):
        make_memory(version=0)


def test_memory_rejects_jira_key_when_empty() -> None:
    """CA-00-02: la memoria referencia su clave de Jira."""
    with pytest.raises(ValidationError):
        make_memory(jira_key="")


def test_memory_markdown_starts_with_front_matter_when_rendered() -> None:
    """CA-00-02: cabecera YAML con los metadatos para el reindexado."""
    lines = make_memory().to_markdown().splitlines()
    assert lines[:5] == [
        "---",
        "jira_key: DEMO-1",
        "artifact_type: user_story",
        "version: 2",
        "---",
    ]
    assert lines[6] == "# Memoria · DEMO-1 (v2)"


def test_memory_markdown_lists_sections_in_order_when_rendered() -> None:
    """CA-00-02: todas las secciones aparecen en el orden definido."""
    md = make_memory().to_markdown()
    headings = [line for line in md.splitlines() if line.startswith("## ")]
    assert headings == [
        "## Objetivo",
        "## Alcance",
        "## Reglas de negocio",
        "## Decisiones",
        "## Dependencias",
        "## Cambios",
        "## Criterios de aceptación",
        "## Referencias",
    ]
    assert "## Reglas de negocio\n- RN-1: máximo 3 préstamos\n" in md
    assert md.endswith("\n")


def test_memory_markdown_uses_dash_when_lists_and_texts_empty() -> None:
    """CA-00-02 (límite): listas y textos vacíos se representan como '—'."""
    memory = make_memory(
        objective="   ",
        scope="",
        business_rules=[],
        decisions=[],
        dependencies=[],
        changes=[],
        acceptance_criteria=[],
        references=[],
    )
    lines = memory.to_markdown().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            assert lines[i + 1] == "—", line


def test_memory_markdown_renders_each_item_when_list_has_several() -> None:
    """CA-00-02: cada elemento de lista es una viñeta."""
    md = make_memory(decisions=["Decisión A", "Decisión B"]).to_markdown()
    assert "## Decisiones\n- Decisión A\n- Decisión B\n" in md


# --------------------------------------------------------------------------- Artifact


def test_artifact_builds_when_user_story_content() -> None:
    """CA-00-02: artefacto de tipo HU."""
    artifact = Artifact(**artifact_data())
    assert isinstance(artifact.content, UserStory)
    assert artifact.impact is None
    assert artifact.model_used is None and artifact.prompt_version is None


def test_artifact_builds_when_test_suite_content() -> None:
    """CA-00-02: artefacto de tipo suite de pruebas."""
    artifact = Artifact(**artifact_data(type=ArtifactType.TEST_SUITE, content=make_suite()))
    assert isinstance(artifact.content, TestSuite)


def test_artifact_rejects_when_type_is_story_but_content_suite() -> None:
    """CA-00-02: el type debe coincidir con el contenido."""
    with pytest.raises(ValidationError, match="'user_story' debe ser UserStory"):
        Artifact(**artifact_data(type=ArtifactType.USER_STORY, content=make_suite()))


def test_artifact_rejects_when_type_is_suite_but_content_story() -> None:
    """CA-00-02: el type debe coincidir con el contenido."""
    with pytest.raises(ValidationError, match="'test_suite' debe ser TestSuite"):
        Artifact(**artifact_data(type=ArtifactType.TEST_SUITE, content=make_story()))


@pytest.mark.parametrize("version", [0, -1])
def test_artifact_rejects_version_when_not_positive(version: int) -> None:
    """CA-00-02 (límite): versión positiva."""
    with pytest.raises(ValidationError):
        Artifact(**artifact_data(version=version))


def test_artifact_rejects_id_when_not_uuid() -> None:
    """CA-00-02: el id es un UUID."""
    with pytest.raises(ValidationError):
        Artifact(**artifact_data(id="no-es-un-uuid"))


def test_artifact_rejects_status_when_unknown() -> None:
    """CA-00-02: estado fuera del enum."""
    with pytest.raises(ValidationError):
        Artifact(**artifact_data(status="archived"))


def test_artifact_roundtrips_json_when_user_story() -> None:
    """CA-00-02: serializar y deserializar conserva el tipo UserStory y el impacto."""
    impact = ImpactAnalysis(
        diffs=[StoryDiff(field="title", before="A", after="B")],
        affected=[ImpactItem(jira_key="DEMO-3", reason="dependencia", kind="dependency")],
        regression_notes=[],
    )
    original = Artifact(
        **artifact_data(
            impact=impact,
            content=make_story(sources=[SourceRef(kind="rag", ref="doc-ficticio-1")]),
            model_used="modelo-ficticio",
            prompt_version="1",
        )
    )
    restored = Artifact.model_validate_json(original.model_dump_json())
    assert isinstance(restored.content, UserStory)
    assert restored == original


def test_artifact_roundtrips_json_when_test_suite() -> None:
    """CA-00-02: serializar y deserializar conserva el tipo TestSuite."""
    original = Artifact(
        **artifact_data(
            type=ArtifactType.TEST_SUITE,
            status=ArtifactStatus.IN_REVIEW,
            content=make_suite(
                cases=[make_case("CP-1"), make_case("CP-2", rule_ids=["RN-1"])],
                synthetic_data=[{"socio": "socio-ficticio-001"}],
            ),
        )
    )
    restored = Artifact.model_validate_json(original.model_dump_json())
    assert isinstance(restored.content, TestSuite)
    assert restored == original
    assert restored.content.coverage() == original.content.coverage()


# --------------------------------------------------------------------------- JSON Schema


@pytest.mark.parametrize("model", [UserStory, TestSuite, Memory, ImpactAnalysis])
def test_json_schema_generates_when_used_as_llm_output(model: type[BaseModel]) -> None:
    """CA-00-02: los modelos de salida estructurada del LLM generan JSON Schema."""
    schema = model.model_json_schema()
    assert schema["type"] == "object"
    assert schema["title"] == model.__name__
    assert set(schema["required"]) <= set(schema["properties"])


def test_json_schema_includes_id_patterns_when_user_story() -> None:
    """CA-00-02: los patrones de ID se exponen al LLM en el JSON Schema."""
    schema = UserStory.model_json_schema()
    assert schema["$defs"]["AcceptanceCriterion"]["properties"]["id"]["pattern"] == r"^CA-\d+$"
    assert schema["$defs"]["BusinessRule"]["properties"]["id"]["pattern"] == r"^RN-\d+$"
