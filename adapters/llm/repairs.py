"""Reparación determinista de IDs en la salida estructurada, sin volver a llamar al LLM (T-58).

Los modelos pequeños copian los identificadores de las fuentes (`RN-RES-01`, `CA1`…) y el
esquema exige `RN-NN`, `CA-NN` y `CP-NN`. Antes de gastar un reintento, `repair_ids` renumera
los IDs con otro formato:

- un ID con formato válido no se toca (así se respetan los IDs que ya existían al evolucionar);
- los no válidos reciben, en orden de aparición, el siguiente número libre por encima del mayor
  válido de su lista, con dos cifras;
- el ID original se conserva al final del texto del elemento: «… (ref. original: RN-RES-01)».

En las suites, las referencias a la HU (`criterion_ids`, `rule_ids`) solo se normalizan si son
variantes con número (`CA1`, `ca_02` → `CA-01`, `CA-02`); el resto se deja para el reintento.

Solo importa `schemas/`. El registro `REPAIRS` dice qué listas se reparan en cada esquema.
"""

import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from schemas.test_case import CASE_ID, TestSuite
from schemas.user_story import CRITERION_ID, RULE_ID, UserStory

MAX_ORIGINAL_SHOWN = 40
_NUMBERED_REF = re.compile(r"^\s*(CA|RN)[\s_-]*0*(\d{1,3})\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class IdList:
    """Una lista del JSON cuyos elementos llevan un ID con prefijo."""

    items: str  # clave de la lista en el objeto raíz
    id_field: str
    prefix: str  # «CA», «RN» o «CP»
    pattern: str
    text_field: str  # donde se conserva el ID original


@dataclass(frozen=True)
class IdChange:
    prefix: str
    original: str
    new: str


@dataclass(frozen=True)
class RepairSpec:
    lists: tuple[IdList, ...]
    ref_lists: tuple[tuple[str, str], ...] = ()  # (lista, campo de referencias) a normalizar


REPAIRS: dict[type[BaseModel], RepairSpec] = {
    UserStory: RepairSpec(
        lists=(
            IdList("acceptance_criteria", "id", "CA", CRITERION_ID, "title"),
            IdList("business_rules", "id", "RN", RULE_ID, "description"),
        )
    ),
    TestSuite: RepairSpec(
        lists=(IdList("cases", "internal_id", "CP", CASE_ID, "title"),),
        ref_lists=(("cases", "criterion_ids"), ("cases", "rule_ids")),
    ),
}


def repair_ids(schema: type[BaseModel], data: Any) -> list[IdChange]:
    """Renumera en `data` (JSON ya decodificado) los IDs con otro formato; devuelve los cambios.

    Modifica `data` en el sitio. Lista vacía si el esquema no tiene reparación o no hay nada que
    reparar; nunca lanza por una estructura inesperada (la valida después pydantic).
    """
    spec = REPAIRS.get(schema)
    if spec is None or not isinstance(data, dict):
        return []
    changes: list[IdChange] = []
    for id_list in spec.lists:
        changes += _repair_list(data.get(id_list.items), id_list)
    for items, field in spec.ref_lists:
        changes += _normalize_refs(data.get(items), field)
    return changes


def _repair_list(items: Any, spec: IdList) -> list[IdChange]:
    if not isinstance(items, list):
        return []
    pattern = re.compile(spec.pattern)
    elements = [item for item in items if isinstance(item, dict)]
    valid = [e[spec.id_field] for e in elements if _is_valid(e.get(spec.id_field), pattern)]
    next_number = max((int(v.split("-", 1)[1]) for v in valid), default=0) + 1
    changes: list[IdChange] = []
    for element in elements:
        original = element.get(spec.id_field)
        if _is_valid(original, pattern) or not isinstance(original, str) or not original.strip():
            continue
        new = f"{spec.prefix}-{next_number:02d}"
        next_number += 1
        element[spec.id_field] = new
        shown = " ".join(original.split())[:MAX_ORIGINAL_SHOWN]
        text = element.get(spec.text_field)
        if isinstance(text, str) and text.strip():
            element[spec.text_field] = f"{text.rstrip()} (ref. original: {shown})"
        changes.append(IdChange(spec.prefix, shown, new))
    return changes


def _normalize_refs(items: Any, field: str) -> list[IdChange]:
    if not isinstance(items, list):
        return []
    changes: list[IdChange] = []
    for element in items:
        refs = element.get(field) if isinstance(element, dict) else None
        if not isinstance(refs, list):
            continue
        for index, ref in enumerate(refs):
            if not isinstance(ref, str) or re.fullmatch(r"(CA|RN)-\d+", ref):
                continue
            if match := _NUMBERED_REF.match(ref):
                prefix = match.group(1).upper()
                new = f"{prefix}-{int(match.group(2)):02d}"
                refs[index] = new
                changes.append(IdChange(prefix, ref[:MAX_ORIGINAL_SHOWN], new))
    return changes


def _is_valid(value: Any, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and bool(pattern.fullmatch(value))
