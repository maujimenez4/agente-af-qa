"""Pruebas de adapters/llm/repairs.py (T-58 · RNF-09, RNF-10, RNF-12).

Reparación determinista de IDs (`CA-NN`, `RN-NN`, `CP-NN`) sin volver a llamar al LLM. Los
datos son sintéticos de la biblioteca ficticia de Villaficticia; los IDs «raros» reproducen lo
que devolvieron los modelos locales en las mediciones (`RN-RES-01`…, `RN-02a`, `CA-NUEVO`).
"""

import copy
from typing import Any

import pytest

from adapters.llm.repairs import MAX_ORIGINAL_SHOWN, REPAIRS, IdChange, repair_ids
from schemas.quality import QualityReport
from schemas.test_case import TestSuite
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.llm import renewal_test_suite

# --- Ayudas -----------------------------------------------------------------------------------


def story_data(
    *, rules: list[str] | None = None, criteria: list[str] | None = None
) -> dict[str, Any]:
    """HU sintética de renovación como JSON decodificado, con los IDs indicados."""
    data = dataset.renewal_story(jira_key=None).model_dump(mode="json")
    if rules is not None:
        data["business_rules"] = [
            {"id": rule_id, "description": f"Regla ficticia {n}"}
            for n, rule_id in enumerate(rules, start=1)
        ]
    if criteria is not None:
        template = data["acceptance_criteria"][0]
        data["acceptance_criteria"] = [
            {**template, "id": criterion_id, "title": f"Criterio ficticio {n}"}
            for n, criterion_id in enumerate(criteria, start=1)
        ]
    return data


def suite_data() -> dict[str, Any]:
    return renewal_test_suite().model_dump(mode="json")


def rule_ids(data: dict[str, Any]) -> list[str]:
    return [rule["id"] for rule in data["business_rules"]]


def criterion_ids(data: dict[str, Any]) -> list[str]:
    return [criterion["id"] for criterion in data["acceptance_criteria"]]


# --- Registro ----------------------------------------------------------------------------------


def test_registry_covers_user_story_and_test_suite_when_loaded() -> None:
    """A · T-58: el registro repara CA/RN en la HU y CP (más refs) en la suite."""
    story = REPAIRS[UserStory]
    suite = REPAIRS[TestSuite]

    assert {(spec.items, spec.prefix) for spec in story.lists} == {
        ("acceptance_criteria", "CA"),
        ("business_rules", "RN"),
    }
    assert [(spec.items, spec.id_field, spec.prefix) for spec in suite.lists] == [
        ("cases", "internal_id", "CP")
    ]
    assert set(suite.ref_lists) == {("cases", "criterion_ids"), ("cases", "rule_ids")}


# --- UserStory ---------------------------------------------------------------------------------


def test_repair_renumbers_rules_when_all_use_source_ids() -> None:
    """A · T-58: RN-RES-01…RN-RES-10 → RN-01…RN-10 y el original queda en la descripción."""
    originals = [f"RN-RES-{n:02d}" for n in range(1, 11)]
    data = story_data(rules=originals)

    changes = repair_ids(UserStory, data)

    assert rule_ids(data) == [f"RN-{n:02d}" for n in range(1, 11)]
    assert changes == [
        IdChange("RN", original, f"RN-{n:02d}") for n, original in enumerate(originals, start=1)
    ]
    for n, rule in enumerate(data["business_rules"], start=1):
        assert rule["description"] == f"Regla ficticia {n} (ref. original: RN-RES-{n:02d})"
    UserStory.model_validate(data)  # la salida reparada valida contra el esquema


def test_repair_keeps_valid_ids_when_list_mixes_valid_and_invalid() -> None:
    """A · T-58 (caso phi4): los válidos intactos y RN-02a recibe RN-10 (mayor válido + 1)."""
    data = story_data(rules=["RN-01", "RN-02", "RN-04", "RN-02a", "RN-06", "RN-07", "RN-09"])

    changes = repair_ids(UserStory, data)

    assert rule_ids(data) == ["RN-01", "RN-02", "RN-04", "RN-10", "RN-06", "RN-07", "RN-09"]
    assert changes == [IdChange("RN", "RN-02a", "RN-10")]
    untouched = [r for r in data["business_rules"] if r["id"] != "RN-10"]
    assert all("ref. original" not in r["description"] for r in untouched)
    assert data["business_rules"][3]["description"].endswith("(ref. original: RN-02a)")
    UserStory.model_validate(data)


def test_repair_numbers_new_criterion_after_existing_when_evolving() -> None:
    """A · T-58: en una evolución con CA-01…CA-03, «CA-NUEVO» pasa a CA-04."""
    data = story_data(criteria=["CA-01", "CA-02", "CA-03", "CA-NUEVO"])

    changes = repair_ids(UserStory, data)

    assert criterion_ids(data) == ["CA-01", "CA-02", "CA-03", "CA-04"]
    assert changes == [IdChange("CA", "CA-NUEVO", "CA-04")]
    assert (
        data["acceptance_criteria"][3]["title"] == "Criterio ficticio 4 (ref. original: CA-NUEVO)"
    )


def test_repair_assigns_in_order_of_appearance_when_several_invalid() -> None:
    """A · T-58: los inválidos reciben números correlativos en el orden en que aparecen."""
    data = story_data(criteria=["CA-X", "CA-02", "CA1", "CA-07", "criterio"])

    repair_ids(UserStory, data)

    assert criterion_ids(data) == ["CA-08", "CA-02", "CA-09", "CA-07", "CA-10"]


def test_repair_repairs_criteria_and_rules_in_the_same_story() -> None:
    """A · T-58: CA y RN se reparan a la vez, cada lista con su propia numeración."""
    data = story_data(criteria=["CA-RES-01", "CA-01"], rules=["RN-RES-01"])

    changes = repair_ids(UserStory, data)

    assert criterion_ids(data) == ["CA-02", "CA-01"]
    assert rule_ids(data) == ["RN-01"]
    assert {change.prefix for change in changes} == {"CA", "RN"}


def test_repair_uses_two_digits_and_grows_beyond_when_max_is_high() -> None:
    """A · T-58 (límite): 2 cifras mínimo; si el mayor válido es RN-99, sigue RN-100."""
    data = story_data(rules=["RN-99", "RN-X"])

    repair_ids(UserStory, data)

    assert rule_ids(data) == ["RN-99", "RN-100"]


def test_repair_returns_empty_and_leaves_data_when_all_ids_valid() -> None:
    """A · T-58: con todos los IDs válidos no hay cambios ni se toca el texto."""
    data = story_data()
    before = copy.deepcopy(data)

    assert repair_ids(UserStory, data) == []
    assert data == before


def test_repair_does_not_break_when_criterion_title_is_empty() -> None:
    """A · T-58 (límite): un CA sin texto se renumera sin añadir la referencia ni lanzar."""
    data = story_data(criteria=["CA-01", "CA-NUEVO"])
    data["acceptance_criteria"][1]["title"] = ""

    changes = repair_ids(UserStory, data)

    assert criterion_ids(data) == ["CA-01", "CA-02"]
    assert data["acceptance_criteria"][1]["title"] == ""
    assert changes == [IdChange("CA", "CA-NUEVO", "CA-02")]


@pytest.mark.parametrize("text", [None, 7, "   "], ids=["sin-clave", "no-texto", "en-blanco"])
def test_repair_does_not_break_when_text_field_missing_or_not_text(text: Any) -> None:
    """A · T-58 (límite): sin campo de texto utilizable, se renumera igualmente sin lanzar."""
    data = story_data(rules=["RN-RES-01"])
    if text is None:
        del data["business_rules"][0]["description"]
    else:
        data["business_rules"][0]["description"] = text

    changes = repair_ids(UserStory, data)

    assert rule_ids(data) == ["RN-01"]
    assert len(changes) == 1


@pytest.mark.parametrize("bad_id", [5, None, "", "   ", ["RN-01"]], ids=repr)
def test_repair_skips_id_when_not_a_non_empty_string(bad_id: Any) -> None:
    """A · T-58 (error): un ID no string o vacío no se repara y no se lanza (lo valida pydantic)."""
    data = story_data(rules=["RN-01"])
    data["business_rules"].append({"id": bad_id, "description": "Regla ficticia rara"})

    assert repair_ids(UserStory, data) == []
    assert data["business_rules"][1]["id"] == bad_id


def test_repair_skips_element_when_id_key_missing() -> None:
    """A · T-58 (error): un elemento sin clave `id` se ignora."""
    data = story_data(rules=["RN-01"])
    data["business_rules"].append({"description": "Regla ficticia sin id"})

    assert repair_ids(UserStory, data) == []


@pytest.mark.parametrize(
    "value", ["no es una lista", {"id": "RN-RES-01"}, 3, None], ids=["str", "dict", "int", "none"]
)
def test_repair_returns_empty_when_list_is_not_a_list(value: Any) -> None:
    """A · T-58 (error): si `business_rules` no es una lista, no hay cambios ni excepción."""
    data = story_data()
    data["business_rules"] = value

    assert repair_ids(UserStory, data) == []
    assert data["business_rules"] == value


def test_repair_ignores_non_dict_items_inside_list() -> None:
    """A · T-58 (error): elementos que no son objetos se dejan tal cual; el resto se repara."""
    data = story_data(rules=["RN-RES-01"])
    data["business_rules"] = ["RN-RES-02", *data["business_rules"], 42]

    changes = repair_ids(UserStory, data)

    assert data["business_rules"][0] == "RN-RES-02"
    assert data["business_rules"][1]["id"] == "RN-01"
    assert data["business_rules"][2] == 42
    assert changes == [IdChange("RN", "RN-RES-01", "RN-01")]


def test_repair_returns_empty_when_lists_missing() -> None:
    """A · T-58 (límite): un objeto sin las listas del esquema no cambia."""
    assert repair_ids(UserStory, {}) == []
    assert repair_ids(TestSuite, {"story_jira_key": "DEMO-3"}) == []


@pytest.mark.parametrize("data", [None, [], ["RN-RES-01"], "texto", 3, 2.5, True], ids=repr)
def test_repair_returns_empty_when_data_is_not_a_dict(data: Any) -> None:
    """A · T-58 (error): `data` que no es un objeto → [] sin lanzar."""
    assert repair_ids(UserStory, data) == []
    assert repair_ids(TestSuite, data) == []


def test_repair_returns_empty_when_schema_not_registered() -> None:
    """A · T-58: un esquema sin entrada en REPAIRS no se repara y no se modifica."""
    data: dict[str, Any] = {"business_rules": [{"id": "RN-RES-01", "description": "x"}]}
    before = copy.deepcopy(data)

    assert QualityReport not in REPAIRS
    assert repair_ids(QualityReport, data) == []
    assert data == before


# --- Recorte del original ---------------------------------------------------------------------


def test_repair_truncates_original_to_40_chars_and_removes_line_breaks() -> None:
    """A · T-58 (límite): el original mostrado se recorta a 40 y no lleva saltos de línea."""
    weird = "RN-\nRES   regla\tcopiada del reglamento ficticio de Villaficticia\r\n2026"
    data = story_data(rules=[weird])

    changes = repair_ids(UserStory, data)

    assert MAX_ORIGINAL_SHOWN == 40
    shown = changes[0].original
    assert len(shown) <= 40
    assert "\n" not in shown and "\r" not in shown and "\t" not in shown
    assert shown == " ".join(weird.split())[:40]
    description = data["business_rules"][0]["description"]
    assert description.endswith(f"(ref. original: {shown})")
    assert "\n" not in description


def test_repair_keeps_original_whole_when_exactly_40_chars() -> None:
    """A · T-58 (límite): un original de 40 caracteres justos se muestra entero."""
    original = "RN-" + "X" * 37
    assert len(original) == 40
    data = story_data(rules=[original])

    changes = repair_ids(UserStory, data)

    assert changes[0].original == original


# --- TestSuite ---------------------------------------------------------------------------------


def test_repair_renumbers_invalid_case_ids_when_suite() -> None:
    """A · T-58: CP inválidos → siguiente libre por encima del mayor válido, con el original."""
    data = suite_data()
    template = data["cases"][0]
    data["cases"] = [
        {**template, "internal_id": "CP1", "title": "Caso ficticio A"},
        {**template, "internal_id": "CP-03", "title": "Caso ficticio B"},
        {**template, "internal_id": "TC-RES-02", "title": "Caso ficticio C"},
    ]

    changes = repair_ids(TestSuite, data)

    assert [case["internal_id"] for case in data["cases"]] == ["CP-04", "CP-03", "CP-05"]
    assert data["cases"][0]["title"] == "Caso ficticio A (ref. original: CP1)"
    assert data["cases"][1]["title"] == "Caso ficticio B"
    assert IdChange("CP", "TC-RES-02", "CP-05") in changes


def test_repair_normalizes_numbered_refs_when_suite() -> None:
    """A · T-58: refs «CA1», «ca_02», «RN 3» → CA-01, CA-02, RN-03; las válidas no se tocan."""
    data = suite_data()
    data["cases"][0]["criterion_ids"] = ["CA1", "ca_02", "CA-01"]
    data["cases"][0]["rule_ids"] = ["RN 3", "RN-02"]

    changes = repair_ids(TestSuite, data)

    assert data["cases"][0]["criterion_ids"] == ["CA-01", "CA-02", "CA-01"]
    assert data["cases"][0]["rule_ids"] == ["RN-03", "RN-02"]
    assert [(c.original, c.new) for c in changes] == [
        ("CA1", "CA-01"),
        ("ca_02", "CA-02"),
        ("RN 3", "RN-03"),
    ]
    TestSuite.model_validate(data)


@pytest.mark.parametrize("ref", ["CA-RES-01", "criterio uno", "CA", "CA-1000x"])
def test_repair_leaves_unnumbered_refs_for_retry_when_suite(ref: str) -> None:
    """A · T-58: refs sin número reconocible (p. ej. «CA-RES-01») se dejan para el reintento."""
    data = suite_data()
    data["cases"][0]["criterion_ids"] = [ref]

    assert repair_ids(TestSuite, data) == []
    assert data["cases"][0]["criterion_ids"] == [ref]


def test_repair_ignores_refs_that_are_not_strings_or_lists() -> None:
    """A · T-58 (error): refs no string, o listas de refs que no son listas, no hacen lanzar."""
    data = suite_data()
    data["cases"][0]["criterion_ids"] = [1, None, "CA1"]
    data["cases"][1]["rule_ids"] = "RN 3"
    data["cases"].append("caso-no-objeto")

    changes = repair_ids(TestSuite, data)

    assert data["cases"][0]["criterion_ids"] == [1, None, "CA-01"]
    assert data["cases"][1]["rule_ids"] == "RN 3"
    assert changes == [IdChange("CA", "CA1", "CA-01")]


def test_repair_does_not_touch_story_lists_when_schema_is_suite() -> None:
    """A · T-58: con TestSuite solo se miran `cases`; las listas de HU no se reparan."""
    data = suite_data()
    data["business_rules"] = [{"id": "RN-RES-01", "description": "x"}]

    repair_ids(TestSuite, data)

    assert data["business_rules"][0]["id"] == "RN-RES-01"


# --- Defectos ---------------------------------------------------------------------------------


def test_repair_renumbers_id_when_it_has_trailing_newline() -> None:
    """A · T-58 (límite): «RN-01\\n» no es válido para el esquema y debería repararse."""
    data = story_data(rules=["RN-01\n"])

    changes = repair_ids(UserStory, data)

    assert changes
    UserStory.model_validate(data)
