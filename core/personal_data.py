"""Detector común de datos que parecen personales (RF-25, CLAUDE.md principio 3; PA-142).

Lo usan la validación de la suite (`core/qa/validation.py`), la memoria (`core/memory/`), la
evidencia de la ejecución (`core/graph/execution.py`) y la HU (`core/functional/writer.py` y la
edición manual, PA-451/PA-452). También el detector de secretos (`SECRET`), común a la memoria y
a la HU desde PA-452. Tiempo lineal en la longitud del texto:
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


# Formas habituales de secretos: no deben llegar a Jira ni a la memoria, que se reindexa en el RAG.
# Se movió aquí desde `core/memory/generator.py` (PA-452) para que la HU use el mismo detector.
SECRET = re.compile(
    r"(?i)\bbearer\s+[\w.~+/-]{12,}"
    r"|\bauthorization\s*:\s*basic\s+[A-Za-z0-9+/]{12,}={0,2}"  # PA-226
    r"|\beyJ[\w-]{8,}\.[\w-]{8,}\."
    r"|\b(?:sk|gsk|gh[pousr]|glpat|xox[abprs])[-_][\w-]{16,}"  # PA-226: GitHub, Slack…
    r"|\bgithub_pat_\w{22,}|\bAIza[\w-]{30,}"  # PA-226: GitHub y Google
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|-----BEGIN [A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----"  # PA-226 (también PGP)
    r"|\b[a-z][\w+.-]*://[^\s:/@]+:[^\s@]+@"  # cadena de conexión con credenciales
    r"|(?<![a-z0-9])pin\s*[:=]?\s*\d{4,12}\b"  # PA-226: «PIN: 1234», «PIN 4821»
    # PA-218: tras «contraseña:» solo cuenta un valor que lo parezca: con dígitos o símbolos,
    # con una mayúscula en medio (frase de paso, «CorrectoCaballo») o de 16 letras o más.
    # «La contraseña: mínimo ocho caracteres» es una regla de negocio, no un secreto.
    # PA-226: más palabras clave, también tras «_» («client_secret»). Lookahead y valor acotados
    # a 64 caracteres: sin el tope, una entrada adversaria era cuadrática (ReDoS).
    # Palabras de credencial fuerte: el guion también delata un secreto («correcto-caballo»).
    r"|(?<![a-z0-9])(?:api[_ -]?key|(?:client|api)[_ -]?secret|clave[_ ]api|password|passwd"
    r"|pwd|pass|contraseña|secreto|secret)\s*[:=]\s*"
    r"(?:(?=\S{0,64}[\d_\-+/=@#$%&*!~])\S{6,64}|(?-i:(?=\S{0,64}[a-zà-ÿ][A-Z]))\S{6,64}"
    r"|\w{16,64})"
    # Palabras ambiguas en español («clave», «token», «credencial»): el guion no cuenta
    # («Clave: identificador-del-carné» es texto de negocio).
    r"|(?<![a-z0-9])(?:clave|token|credencial(?:es)?)\s*[:=]\s*"
    r"(?:(?=\S{0,64}[\d_+/=@#$%&*!~])\S{6,64}|(?-i:(?=\S{0,64}[a-zà-ÿ][A-Z]))\S{6,64}"
    r"|\w{16,64})"
)


def looks_like_secret(text: str) -> bool:
    """Si el texto parece contener un secreto (token, clave, cadena de conexión…). Nunca devuelve
    el valor encontrado."""
    return SECRET.search(text) is not None
