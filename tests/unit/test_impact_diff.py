"""Pruebas de `diff_stories` (T-19 · RF-19, RNF-16).

El diff es puro y determinista: recorre los campos en el orden de la plantilla, empareja
CA y RN por ID y compara las fuentes por "kind:ref". Datos 100 % sintéticos (Villaficticia).
"""

from core.impact.diff import diff_stories
from schemas.common import Priority, SourceRef
from schemas.impact import StoryDiff
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory
from tests.fakes.dataset import renewal_story


def _criterion(
    number: int,
    *,
    title: str = "Criterio ficticio de Villaficticia",
    given: list[str] | None = None,
    when: list[str] | None = None,
    then: list[str] | None = None,
) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=f"CA-{number:02d}" if number < 10 else f"CA-{number}",
        title=title,
        given=given or ["una persona socia ficticia de Villaficticia"],
        when=when or ["pulsa «Renovar»"],
        then=then or ["el sistema responde de forma ficticia"],
    )


def _with(story: UserStory, **changes: object) -> UserStory:
    return story.model_copy(update=changes, deep=True)


def _by_field(diffs: list[StoryDiff]) -> dict[str, StoryDiff]:
    return {d.field: d for d in diffs}


# --- Sin cambios -----------------------------------------------------------------------


def test_diff_returns_empty_when_stories_equal() -> None:
    """RF-19: dos versiones idénticas → lista vacía."""
    assert diff_stories(renewal_story(), renewal_story()) == []


def test_diff_returns_empty_when_same_instance() -> None:
    """RF-19 (límite): la misma instancia en ambos lados → lista vacía."""
    story = renewal_story()
    assert diff_stories(story, story) == []


# --- Campos escalares -----------------------------------------------------------------


def test_diff_reports_title_when_title_changes() -> None:
    """RF-19: cambio de título → un StoryDiff con el texto anterior y el nuevo."""
    before = renewal_story()
    after = _with(before, title="Renovar un préstamo en Villaficticia")
    assert diff_stories(before, after) == [
        StoryDiff(
            field="title",
            before="Renovar un préstamo",
            after="Renovar un préstamo en Villaficticia",
        )
    ]


def test_diff_uses_enum_value_when_priority_changes() -> None:
    """RF-19: la prioridad se compara y muestra por su valor ("Must" → "Should")."""
    before = renewal_story()
    after = _with(before, priority=Priority.SHOULD)
    assert diff_stories(before, after) == [
        StoryDiff(field="priority", before="Must", after="Should")
    ]


def test_diff_reports_none_when_optional_scalar_cleared() -> None:
    """RF-19 (límite): un campo opcional que pasa a None → after None."""
    before = renewal_story()
    after = _with(before, jira_key=None)
    assert diff_stories(before, after) == [StoryDiff(field="jira_key", before="DEMO-3", after=None)]


def test_diff_reports_none_before_when_optional_scalar_set() -> None:
    """RF-19 (límite): un campo opcional que antes era None → before None."""
    before = renewal_story(jira_key=None)
    after = renewal_story(jira_key="DEMO-7")
    assert diff_stories(before, after) == [StoryDiff(field="jira_key", before=None, after="DEMO-7")]


# --- Criterios de aceptación ----------------------------------------------------------


def test_diff_reports_added_criterion_with_before_none() -> None:
    """RF-19: CA añadido → field `acceptance_criteria[CA-03]`, before None y texto Gherkin."""
    before = renewal_story()
    new = AcceptanceCriterion(
        id="CA-03",
        title="Renovación rechazada por límite",
        given=["un préstamo ficticio con 2 renovaciones", "sin reservas pendientes"],
        when=["la persona socia pulsa «Renovar»"],
        then=["se muestra un aviso ficticio", "el vencimiento no cambia"],
    )
    after = _with(before, acceptance_criteria=[*before.acceptance_criteria, new])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="acceptance_criteria[CA-03]",
            before=None,
            after=(
                "Renovación rechazada por límite\n"
                "Dado un préstamo ficticio con 2 renovaciones\n"
                "Y sin reservas pendientes\n"
                "Cuando la persona socia pulsa «Renovar»\n"
                "Entonces se muestra un aviso ficticio\n"
                "Y el vencimiento no cambia"
            ),
        )
    ]


def test_diff_reports_removed_criterion_with_after_none() -> None:
    """RF-19: CA eliminado → after None y before con el texto completo del CA."""
    before = renewal_story()
    after = _with(before, acceptance_criteria=before.acceptance_criteria[:1])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="acceptance_criteria[CA-02]",
            before=(
                "Renovación rechazada por reservas\n"
                "Dado un préstamo activo con reservas pendientes\n"
                "Cuando la persona socia pulsa «Renovar»\n"
                "Entonces se muestra el aviso «El ejemplar tiene reservas pendientes»"
            ),
            after=None,
        )
    ]


def test_diff_reports_modified_criterion_when_given_changes() -> None:
    """RF-19: cambio en `given` de un CA → un único diff de ese CA."""
    before = renewal_story()
    changed = before.acceptance_criteria[0].model_copy(
        update={"given": ["un préstamo activo con menos de 3 renovaciones"]}
    )
    after = _with(before, acceptance_criteria=[changed, before.acceptance_criteria[1]])
    diffs = diff_stories(before, after)
    assert [d.field for d in diffs] == ["acceptance_criteria[CA-01]"]
    assert diffs[0].before is not None and diffs[0].after is not None
    assert "Dado un préstamo activo con menos de 2 renovaciones" in diffs[0].before
    assert "Y sin reservas pendientes" in diffs[0].before
    assert "Dado un préstamo activo con menos de 3 renovaciones" in diffs[0].after
    assert "sin reservas pendientes" not in diffs[0].after


def test_diff_reports_modified_criterion_when_when_changes() -> None:
    """RF-19: cambio en `when` de un CA → diff con la línea «Cuando» nueva."""
    before = renewal_story()
    changed = before.acceptance_criteria[1].model_copy(
        update={"when": ["la persona socia pulsa «Ampliar plazo»"]}
    )
    after = _with(before, acceptance_criteria=[before.acceptance_criteria[0], changed])
    diffs = diff_stories(before, after)
    assert [d.field for d in diffs] == ["acceptance_criteria[CA-02]"]
    assert "Cuando la persona socia pulsa «Ampliar plazo»" in (diffs[0].after or "")


def test_diff_reports_modified_criterion_when_then_changes() -> None:
    """RF-19: cambio en `then` de un CA → diff con la línea «Entonces» nueva."""
    before = renewal_story()
    changed = before.acceptance_criteria[0].model_copy(
        update={"then": ["el vencimiento se amplía 14 días"]}
    )
    after = _with(before, acceptance_criteria=[changed, before.acceptance_criteria[1]])
    diffs = diff_stories(before, after)
    assert [d.field for d in diffs] == ["acceptance_criteria[CA-01]"]
    assert diffs[0].before is not None and diffs[0].after is not None
    assert diffs[0].before.endswith("Entonces el vencimiento se amplía 21 días")
    assert diffs[0].after.endswith("Entonces el vencimiento se amplía 14 días")


def test_diff_reports_modified_criterion_when_title_changes() -> None:
    """RF-19: el título del CA forma parte de su texto comparable."""
    before = renewal_story()
    changed = before.acceptance_criteria[0].model_copy(update={"title": "Renovación ficticia"})
    after = _with(before, acceptance_criteria=[changed, before.acceptance_criteria[1]])
    diffs = diff_stories(before, after)
    assert [d.field for d in diffs] == ["acceptance_criteria[CA-01]"]
    assert (diffs[0].after or "").startswith("Renovación ficticia\nDado ")


def test_diff_ignores_criterion_order_when_ids_match() -> None:
    """RF-19: los CA se emparejan por ID; reordenarlos no genera diff."""
    before = renewal_story()
    after = _with(before, acceptance_criteria=list(reversed(before.acceptance_criteria)))
    assert diff_stories(before, after) == []


def test_diff_orders_criteria_numerically_when_ids_mixed() -> None:
    """RF-19: orden por número de ID (CA-2 antes que CA-10), no alfabético."""
    before = _with(renewal_story(), acceptance_criteria=[_criterion(1)])
    after = _with(
        before,
        acceptance_criteria=[_criterion(1), _criterion(10), _criterion(2), _criterion(9)],
    )
    fields = [d.field for d in diff_stories(before, after)]
    assert fields == [
        "acceptance_criteria[CA-02]",
        "acceptance_criteria[CA-09]",
        "acceptance_criteria[CA-10]",
    ]


def test_diff_orders_unpadded_ids_numerically() -> None:
    """RF-19 (límite): IDs sin ceros a la izquierda → CA-2 antes que CA-10."""
    base = _criterion(1)
    before = _with(renewal_story(), acceptance_criteria=[base])
    after = _with(
        before,
        acceptance_criteria=[
            base,
            base.model_copy(update={"id": "CA-10"}),
            base.model_copy(update={"id": "CA-2"}),
        ],
    )
    fields = [d.field for d in diff_stories(before, after)]
    assert fields == ["acceptance_criteria[CA-2]", "acceptance_criteria[CA-10]"]


# --- Reglas de negocio -----------------------------------------------------------------


def test_diff_reports_added_rule_with_description() -> None:
    """RF-19: RN añadida → before None y after = descripción."""
    before = renewal_story()
    rule = BusinessRule(id="RN-03", description="Regla ficticia de Villaficticia.")
    after = _with(before, business_rules=[*before.business_rules, rule])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="business_rules[RN-03]", before=None, after="Regla ficticia de Villaficticia."
        )
    ]


def test_diff_reports_removed_rule_with_after_none() -> None:
    """RF-19: RN eliminada → after None y before = descripción."""
    before = renewal_story()
    after = _with(before, business_rules=before.business_rules[1:])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="business_rules[RN-01]",
            before="Máximo 2 renovaciones por préstamo.",
            after=None,
        )
    ]


def test_diff_reports_modified_rule_when_description_changes() -> None:
    """RF-19: RN modificada → before y after con ambas descripciones."""
    before = renewal_story()
    changed = BusinessRule(id="RN-01", description="Máximo 3 renovaciones por préstamo.")
    after = _with(before, business_rules=[changed, before.business_rules[1]])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="business_rules[RN-01]",
            before="Máximo 2 renovaciones por préstamo.",
            after="Máximo 3 renovaciones por préstamo.",
        )
    ]


def test_diff_orders_rules_numerically_when_ids_mixed() -> None:
    """RF-19: RN-2 antes que RN-10."""
    before = _with(renewal_story(), business_rules=[])
    after = _with(
        before,
        business_rules=[
            BusinessRule(id="RN-10", description="Regla ficticia diez."),
            BusinessRule(id="RN-2", description="Regla ficticia dos."),
        ],
    )
    fields = [d.field for d in diff_stories(before, after)]
    assert fields == ["business_rules[RN-2]", "business_rules[RN-10]"]


# --- Listas de texto -------------------------------------------------------------------


def test_diff_renders_list_as_bullets_when_item_added() -> None:
    """RF-19: listas de texto como viñetas «- x»; añadir un elemento → diff de la lista."""
    before = renewal_story()
    after = _with(
        before,
        scope_includes=[*before.scope_includes, "Renovación desde la app ficticia"],
    )
    assert diff_stories(before, after) == [
        StoryDiff(
            field="scope_includes",
            before="- Renovación desde la ficha del préstamo",
            after="- Renovación desde la ficha del préstamo\n- Renovación desde la app ficticia",
        )
    ]


def test_diff_renders_list_as_bullets_when_item_removed() -> None:
    """RF-19: quitar un elemento de una lista → before con ambos, after con el restante."""
    before = _with(renewal_story(), scope_includes=["Alcance ficticio A", "Alcance ficticio B"])
    after = _with(before, scope_includes=["Alcance ficticio B"])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="scope_includes",
            before="- Alcance ficticio A\n- Alcance ficticio B",
            after="- Alcance ficticio B",
        )
    ]


def test_diff_reports_after_none_when_list_emptied() -> None:
    """RF-19 (límite): vaciar una lista → after None."""
    before = renewal_story()
    after = _with(before, scope_includes=[])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="scope_includes",
            before="- Renovación desde la ficha del préstamo",
            after=None,
        )
    ]


def test_diff_reports_before_none_when_list_filled_from_empty() -> None:
    """RF-19 (límite): lista vacía que recibe elementos → before None."""
    before = renewal_story()
    after = _with(before, open_questions=["¿Aplica en la sede ficticia de Villaficticia?"])
    assert diff_stories(before, after) == [
        StoryDiff(
            field="open_questions",
            before=None,
            after="- ¿Aplica en la sede ficticia de Villaficticia?",
        )
    ]


def test_diff_detects_list_reordering() -> None:
    """RF-19: en las listas de texto el orden es contenido; reordenar genera diff."""
    before = _with(renewal_story(), assumptions=["Supuesto ficticio 1", "Supuesto ficticio 2"])
    after = _with(before, assumptions=["Supuesto ficticio 2", "Supuesto ficticio 1"])
    assert [d.field for d in diff_stories(before, after)] == ["assumptions"]


# --- Fuentes ---------------------------------------------------------------------------


def test_diff_ignores_source_excerpt_changes() -> None:
    """RF-19 / RF-21: las fuentes se comparan por «kind:ref»; cambiar el excerpt no genera diff."""
    before = _with(
        renewal_story(), sources=[SourceRef(kind="jira", ref="DEMO-2", excerpt="Cita ficticia A")]
    )
    after = _with(before, sources=[SourceRef(kind="jira", ref="DEMO-2", excerpt="Cita ficticia B")])
    assert diff_stories(before, after) == []


def test_diff_reports_sources_when_ref_changes() -> None:
    """RF-19 / RF-21: cambiar la ref de una fuente → diff con viñetas «- kind:ref»."""
    before = _with(
        renewal_story(),
        sources=[
            SourceRef(kind="jira", ref="DEMO-2", excerpt="Cita ficticia"),
            SourceRef(kind="rag", ref="reglamento-villaficticia"),
        ],
    )
    after = _with(
        before,
        sources=[
            SourceRef(kind="jira", ref="DEMO-4", excerpt="Cita ficticia"),
            SourceRef(kind="rag", ref="reglamento-villaficticia"),
        ],
    )
    assert diff_stories(before, after) == [
        StoryDiff(
            field="sources",
            before="- jira:DEMO-2\n- rag:reglamento-villaficticia",
            after="- jira:DEMO-4\n- rag:reglamento-villaficticia",
        )
    ]


def test_diff_reports_sources_when_kind_changes() -> None:
    """RF-19: mismo ref con otro tipo de fuente → diff."""
    before = _with(renewal_story(), sources=[SourceRef(kind="rag", ref="memoria-DEMO-2")])
    after = _with(before, sources=[SourceRef(kind="memory", ref="memoria-DEMO-2")])
    assert diff_stories(before, after) == [
        StoryDiff(field="sources", before="- rag:memoria-DEMO-2", after="- memory:memoria-DEMO-2")
    ]


def test_diff_reports_after_none_when_sources_emptied() -> None:
    """RF-19 (límite): quitar todas las fuentes → after None."""
    before = _with(renewal_story(), sources=[SourceRef(kind="jira", ref="DEMO-2")])
    after = _with(before, sources=[])
    assert diff_stories(before, after) == [
        StoryDiff(field="sources", before="- jira:DEMO-2", after=None)
    ]


# --- Exclusiones, orden y pureza -------------------------------------------------------


def test_diff_ignores_changes_from_previous() -> None:
    """RF-19: `changes_from_previous` explica el cambio, no es contenido; no genera diff."""
    before = renewal_story()
    after = _with(before, changes_from_previous=["Se amplía el plazo (cambio ficticio)."])
    assert diff_stories(before, after) == []


def test_diff_excludes_changes_from_previous_when_other_fields_change() -> None:
    """RF-19: aunque cambien otros campos, `changes_from_previous` nunca aparece."""
    before = renewal_story()
    after = _with(
        before,
        title="Renovar un préstamo ficticio",
        changes_from_previous=["Nuevo título ficticio."],
    )
    assert [d.field for d in diff_stories(before, after)] == ["title"]


def test_diff_follows_template_field_order() -> None:
    """RF-19 / RNF-16: el resultado sigue el orden de `UserStory.model_fields`."""
    before = renewal_story()
    after = _with(
        before,
        open_questions=["¿Pregunta ficticia?"],
        priority=Priority.COULD,
        business_rules=[BusinessRule(id="RN-01", description="Regla ficticia modificada.")],
        acceptance_criteria=[
            before.acceptance_criteria[0].model_copy(update={"title": "Título ficticio"}),
            before.acceptance_criteria[1],
        ],
        scope_excludes=[],
        title="Título ficticio de HU",
        internal_id="HU-99",
    )
    fields = [d.field for d in diff_stories(before, after)]
    assert fields == [
        "internal_id",
        "title",
        "scope_excludes",
        "acceptance_criteria[CA-01]",
        "business_rules[RN-01]",
        "business_rules[RN-02]",
        "priority",
        "open_questions",
    ]
    template = list(UserStory.model_fields)
    base_names = [f.split("[", 1)[0] for f in fields]
    assert base_names == sorted(base_names, key=template.index)


def test_diff_is_deterministic_when_called_twice() -> None:
    """RNF-16: dos llamadas con las mismas entradas → mismo resultado."""
    before = renewal_story()
    after = _with(
        before,
        title="Otro título ficticio",
        business_rules=[],
        scope_includes=[],
        acceptance_criteria=[_criterion(3), _criterion(12)],
    )
    first = diff_stories(before, after)
    second = diff_stories(before, after)
    assert first == second
    assert first  # hay cambios que comparar


def test_diff_does_not_mutate_inputs() -> None:
    """RNF-16: función pura; no modifica las HU de entrada."""
    before = renewal_story()
    after = _with(
        before,
        title="Título ficticio",
        acceptance_criteria=[_criterion(5)],
        business_rules=[],
        sources=[SourceRef(kind="jira", ref="DEMO-2", excerpt="Cita ficticia")],
    )
    before_dump, after_dump = before.model_dump(), after.model_dump()
    diff_stories(before, after)
    assert before.model_dump() == before_dump
    assert after.model_dump() == after_dump


def test_diff_is_symmetric_when_arguments_swapped() -> None:
    """RF-19: invertir los argumentos intercambia before y after en cada diff."""
    before = renewal_story()
    after = _with(before, title="Título ficticio", business_rules=before.business_rules[:1])
    forward = diff_stories(before, after)
    backward = diff_stories(after, before)
    assert [(d.field, d.after, d.before) for d in backward] == [
        (d.field, d.before, d.after) for d in forward
    ]
