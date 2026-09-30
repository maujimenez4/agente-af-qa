"""Diff por campo entre dos versiones de una HU (RF-19, RNF-16).

`diff_stories` es pura y determinista: recorre los campos en el orden de la plantilla
(`UserStory.model_fields`). Los criterios y las reglas se emparejan por ID
(`acceptance_criteria[CA-02]`, `business_rules[RN-01]`), de modo que un elemento añadido tiene
`before=None` y uno eliminado `after=None`. `changes_from_previous` no se compara: explica el
cambio, no es contenido.
"""

import re
from collections.abc import Callable
from typing import Any

from schemas.impact import StoryDiff
from schemas.user_story import AcceptanceCriterion, BusinessRule, UserStory

EXCLUDED_FIELDS = frozenset({"changes_from_previous"})
_ID_NUMBER = re.compile(r"(\d+)$")


def diff_stories(before: UserStory, after: UserStory) -> list[StoryDiff]:
    diffs: list[StoryDiff] = []
    for name in UserStory.model_fields:
        if name in EXCLUDED_FIELDS:
            continue
        old, new = getattr(before, name), getattr(after, name)
        if name == "acceptance_criteria":
            diffs += _diff_by_id(name, old, new, _criterion_text)
        elif name == "business_rules":
            diffs += _diff_by_id(name, old, new, _rule_text)
        else:
            old_text, new_text = _render(name, old), _render(name, new)
            if old_text != new_text:
                diffs.append(StoryDiff(field=name, before=old_text, after=new_text))
    return diffs


def _diff_by_id[T: (AcceptanceCriterion, BusinessRule)](
    name: str, old: list[T], new: list[T], render: Callable[[T], str]
) -> list[StoryDiff]:
    old_by_id = {item.id: render(item) for item in old}
    new_by_id = {item.id: render(item) for item in new}
    diffs = []
    for item_id in sorted(old_by_id.keys() | new_by_id.keys(), key=_id_sort_key):
        before, after = old_by_id.get(item_id), new_by_id.get(item_id)
        if before != after:
            diffs.append(StoryDiff(field=f"{name}[{item_id}]", before=before, after=after))
    return diffs


def _id_sort_key(item_id: str) -> tuple[int, str]:
    match = _ID_NUMBER.search(item_id)
    return (int(match.group(1)) if match else 0, item_id)


def _criterion_text(criterion: AcceptanceCriterion) -> str:
    lines = [criterion.title]
    for keyword, steps in (
        ("Dado", criterion.given),
        ("Cuando", criterion.when),
        ("Entonces", criterion.then),
    ):
        lines += [f"{keyword if i == 0 else 'Y'} {step}" for i, step in enumerate(steps)]
    return "\n".join(lines)


def _rule_text(rule: BusinessRule) -> str:
    return rule.description


def _render(name: str, value: Any) -> str | None:
    """Texto comparable de un campo; `None` si está vacío."""
    if value is None:
        return None
    if name == "sources":
        refs = [f"{ref.kind}:{ref.ref}" for ref in value]
        return "\n".join(f"- {r}" for r in refs) or None
    if isinstance(value, list):
        return "\n".join(f"- {item}" for item in value) or None
    text = str(value.value if hasattr(value, "value") else value)
    return text or None
