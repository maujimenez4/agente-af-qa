"""Detector común de datos que parecen personales (RF-25, CLAUDE.md principio 3; PA-142).

Lo usan la validación de la suite (`core/qa/validation.py`), la memoria (`core/memory/`) y la
evidencia de la ejecución (`core/graph/execution.py`). Tiempo lineal en la longitud del texto:
el email se busca solo en cada `@` (un carácter de parte local justo antes y el dominio anclado
justo después, sin recortarlo); recorrer el texto con `EMAIL` era cuadrático con tramos largos
sin `@` o con dominios largos. DNI, NIE, IBAN y teléfono ya son lineales. Nunca devuelve el
valor encontrado, solo su tipo.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
FICTITIOUS_DOMAIN = re.compile(r"(^|\.)(example\.(com|org|net)|example|invalid)$", re.IGNORECASE)
# Teléfonos españoles de 9 cifras (3-3-3 o 3-2-2-2). Los grupos 3-3-3 con punto se dejan fuera
# porque es el formato de los importes («700.000.000 €»).
PHONE = re.compile(
    r"(?<![\w.,])(?:\+34[ .-]?)?[6-9]\d{2}"
    r"(?:[ -]?\d{3}[ -]?\d{3}|[ .-]?\d{2}[ .-]?\d{2}[ .-]?\d{2})"
    r"(?![\w.,]*\d)"
)
DNI = re.compile(r"\b\d{8}[ -]?[A-Za-z]\b")
NIE = re.compile(r"\b[XYZxyz][ -]?\d{7}[ -]?[A-Za-z]\b")
IBAN = re.compile(r"\bES\d{2}(?:[\s-]?\d{4}){5}\b", re.IGNORECASE)

# Lo mismo que `EMAIL`, por partes y anclado en cada `@`.
LOCAL_CHAR = re.compile(r"[\w.+-]")
DOMAIN = re.compile(r"[\w-]+(?:\.[\w-]+)+")


def personal_data_kind(text: str) -> str | None:
    """Tipo del primer dato que parece personal («email», «documento de identidad», «IBAN»,
    «teléfono») o None. Los emails de dominios reservados (example.com, .invalid) son ficticios.
    """
    if _has_real_email(text):
        return "email"
    if DNI.search(text) or NIE.search(text):
        return "documento de identidad"
    if IBAN.search(text):
        return "IBAN"
    if PHONE.search(text):
        return "teléfono"
    return None


def _has_real_email(text: str) -> bool:
    """Alguna `@` con parte local delante y un dominio no reservado detrás.

    Cada `@` mira un carácter antes y su dominio después (que acaba, como muy tarde, en la
    siguiente `@`), así que el coste total es lineal. Como `EMAIL.finditer`, un email ficticio
    consume su dominio: no sirve de parte local al siguiente (`a@x.invalid@…`).
    """
    consumed = 0
    for at in re.finditer("@", text):
        before = at.start() - 1
        if before < consumed or not LOCAL_CHAR.match(text, before):
            continue
        domain = DOMAIN.match(text, at.end())
        if domain is None:
            continue
        if not FICTITIOUS_DOMAIN.search(domain.group()):
            return True
        consumed = domain.end()
    return False
