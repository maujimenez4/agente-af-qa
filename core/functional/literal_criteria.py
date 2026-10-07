"""CA y RN tal como vienen en la HU de Jira, sin que el modelo los reescriba (PA-432).

Las HU del corpus traen sus criterios y reglas con formato fijo (así llegan desde ADF):

    ## Criterios de aceptación
    ### CA-01 · Título
    ```
    Escenario: Título
      Dado …
      Cuando …
      Entonces …
      Y …
    ```
    ## Reglas de negocio
    - RN-01: texto

Si las dos secciones se leen **completas y sin ambigüedad**, la estructuración usa esos CA y RN
literales en lugar de los del modelo. Si cualquier CA o RN no se puede leer con seguridad, no se
usa ninguno (se quedan los del modelo para todos, sin mezclar).
"""

import re

from schemas.user_story import AcceptanceCriterion, BusinessRule

_CRITERIA_TITLE = "criterios de aceptación"
_RULES_TITLE = "reglas de negocio"
# Sin `(.+?)\s*$`: con muchos espacios seguidos daba un retroceso cuadrático (security-reviewer).
# Las líneas llegan ya sin espacios en los extremos y cada grupo se recorta al usarlo.
_SECTION = re.compile(r"^##\s+(.+)$")
_CRITERION = re.compile(r"^###\s+(CA-\d+)\s*[·:\-–—]\s*(.+)$")
_RULE = re.compile(r"^-\s+(RN-\d+)\s*:\s*(.+)$")
_STEP = re.compile(r"^(Dado|Cuando|Entonces|Y)\s+(.+)$")
MAX_LINE_CHARS = 2000  # una línea más larga no es un CA ni una RN: no se lee
_KEYWORDS = {"Dado": "given", "Cuando": "when", "Entonces": "then"}
_ORDER = ("given", "when", "then")


def literal_criteria(text: str) -> tuple[list[AcceptanceCriterion], list[BusinessRule]] | None:
    """Los CA y las RN del texto, o `None` si falta alguna sección o algo no se lee seguro."""
    sections = _sections(text)
    criteria_lines = sections.get(_CRITERIA_TITLE)
    rules_lines = sections.get(_RULES_TITLE)
    if criteria_lines is None or rules_lines is None:
        return None
    criteria = _criteria(criteria_lines)
    rules = _rules(rules_lines)
    if not criteria or rules is None:
        return None
    ids = [c.id for c in criteria] + [r.id for r in rules]
    if len(ids) != len(set(ids)):
        return None
    return criteria, rules


def _sections(text: str) -> dict[str, list[str]]:
    """Líneas de cada sección `## …`; una sección repetida invalida la lectura."""
    found: dict[str, list[str]] = {}
    current: list[str] | None = None
    repeated = False
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if len(line) > MAX_LINE_CHARS:
            return {}
        if match := _SECTION.match(line):
            title = match.group(1).strip().lower()
            repeated = repeated or title in found
            current = found.setdefault(title, [])
        elif current is not None:
            current.append(line)
    if repeated:
        return {}
    return found


def _criteria(lines: list[str]) -> list[AcceptanceCriterion] | None:
    """Cada `### CA-NN · título` con un bloque de código de Gherkin; si algo no encaja, `None`."""
    criteria: list[AcceptanceCriterion] = []
    current: dict | None = None
    in_block = False
    blocks = 0  # bloques de Gherkin del CA actual: más de uno es ambiguo
    last: str | None = None
    for raw in lines:
        line = raw.strip()
        if line.startswith("```"):
            if current is None:
                return None
            if not in_block:
                blocks += 1
                if blocks > 1:
                    return None
            in_block = not in_block
            continue
        if in_block:
            if not line or line.lower().startswith("escenario"):
                continue
            step = _STEP.match(line)
            if step is None or current is None:
                return None
            keyword, sentence = step.group(1), step.group(2).strip()
            if keyword == "Y":
                if last is None:
                    return None
                current[last].append(sentence)
                continue
            name = _KEYWORDS[keyword]
            if last is not None and _ORDER.index(name) < _ORDER.index(last):
                return None
            current[name].append(sentence)
            last = name
            continue
        if not line:
            continue
        heading = _CRITERION.match(line)
        if heading is None:
            return None  # texto suelto fuera de un bloque: no se lee con seguridad
        if current is not None and (built := _criterion(current)) is None:
            return None
        if current is not None:
            criteria.append(built)  # type: ignore[arg-type]
        current = {
            "id": heading.group(1),
            "title": heading.group(2).strip(),
            "given": [],
            "when": [],
            "then": [],
        }
        last, blocks = None, 0
    if in_block:
        return None
    if current is not None:
        built = _criterion(current)
        if built is None:
            return None
        criteria.append(built)
    return criteria


def _criterion(fields: dict) -> AcceptanceCriterion | None:
    if not (fields["given"] and fields["when"] and fields["then"]):
        return None
    return AcceptanceCriterion(**fields)


def _rules(lines: list[str]) -> list[BusinessRule] | None:
    rules: list[BusinessRule] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        match = _RULE.match(line)
        if match is None:
            return None
        rules.append(BusinessRule(id=match.group(1), description=match.group(2).strip()))
    return rules or None  # una sección de reglas vacía tampoco se lee con seguridad
