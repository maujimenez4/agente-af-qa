"""Validación de una suite de QA frente a su HU (RF-22, RF-24, RF-25; sincronización del día 6).

- Cada caso referencia CA y RN que existen en la HU, y todo CA tiene al menos un caso.
- Hay al menos un caso positivo y uno negativo (decisión de T-26).
- Las citas apuntan solo a fuentes recibidas (RF-21, RNF-14).
- Los datos sintéticos no parecen datos personales reales (RF-25). Los mensajes nunca repiten el
  valor sospechoso.
"""

import re

from adapters.errors import AgentError
from core.functional.citations import citation_errors
from core.functional.context import CitableSource
from core.personal_data import personal_data_kind
from schemas.test_case import TestCaseType, TestSuite
from schemas.user_story import UserStory

REQUIRED_TYPES = (TestCaseType.POSITIVE, TestCaseType.NEGATIVE)

_SAFE_KEY = re.compile(r"[A-Za-z_][\w]{0,40}")


class CoverageError(AgentError):
    """La suite no cubre la HU o no es válida tras el reintento; mensaje en español."""


def coverage_errors(suite: TestSuite, story: UserStory) -> list[str]:
    criteria = {c.id for c in story.acceptance_criteria}
    rules = {r.id for r in story.business_rules}
    errors: list[str] = []
    for case in suite.cases:
        unknown = [i for i in case.criterion_ids if i not in criteria]
        unknown += [i for i in case.rule_ids if i not in rules]
        if unknown:
            errors.append(
                f"{case.internal_id} referencia CA/RN que no existen en la HU: {', '.join(unknown)}"
            )
    covered = suite.coverage()
    missing = [c.id for c in story.acceptance_criteria if not covered.get(c.id)]
    if missing:
        errors.append(f"criterios sin ningún caso de prueba: {', '.join(missing)}")
    types = {case.type for case in suite.cases}
    absent = [t.value for t in REQUIRED_TYPES if t not in types]
    if absent:
        errors.append(f"faltan casos de tipo: {', '.join(absent)}")
    return errors


def personal_data_errors(suite: TestSuite) -> list[str]:
    """Todo texto de la suite que acabaría en Jira: datos, casos, riesgos y estrategia (RF-25)."""
    errors: list[str] = []
    for where, value in _texts(suite):
        if kind := _personal_data_kind(value):
            errors.append(f"{where} parece un {kind} real; usa un valor ficticio")
    return errors


def _texts(suite: TestSuite) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for index, row in enumerate(suite.synthetic_data):
        for position, (key, value) in enumerate(row.items()):
            # La clave la elige el LLM: se revisa y solo se muestra si tiene forma de nombre.
            shown = key if _SAFE_KEY.fullmatch(key) else f"<clave {position + 1}>"
            texts.append((f"synthetic_data[{index}] (clave {shown})", key))
            texts.append((f"synthetic_data[{index}].{shown}", value))
    for name in ("risks", "dependencies", "impact_areas"):
        texts += [(f"{name}[{i}]", text) for i, text in enumerate(getattr(suite, name))]
    texts.append(("strategy_md", suite.strategy_md))
    for case in suite.cases:
        texts.append((f"{case.internal_id}.title", case.title))
        texts += [
            (f"{case.internal_id}.preconditions[{i}]", text)
            for i, text in enumerate(case.preconditions)
        ]
        for i, step in enumerate(case.steps):
            texts += [
                (f"{case.internal_id}.steps[{i}].{name}", text)
                for name, text in (
                    ("action", step.action),
                    ("data", step.data),
                    ("expected", step.expected),
                )
                if text
            ]
        if case.gherkin:
            texts.append((f"{case.internal_id}.gherkin", case.gherkin))
    return texts


def suite_errors(suite: TestSuite, story: UserStory, sources: list[CitableSource]) -> list[str]:
    return [
        *coverage_errors(suite, story),
        *citation_errors(suite, sources),
        *personal_data_errors(suite),
    ]


# PA-142: un único detector, lineal, en `core/personal_data.py`. Se conserva el nombre
# privado porque `core/memory/generator.py` lo importa así (PA-250).
_personal_data_kind = personal_data_kind
