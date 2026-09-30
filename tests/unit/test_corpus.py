"""Comprueba el corpus piloto sintético del RAG (T-09, D-06)."""

import datetime as dt
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "seed" / "corpus"
README = CORPUS / "README.md"

CATEGORIES = frozenset(
    {
        "normativa",
        "procesos",
        "especificaciones",
        "glosario",
        "arquitectura",
        "manuales",
        "actas",
    }
)
FORBIDDEN_CATEGORY = "memoria"
EPICS = frozenset({"EP-PRESTAMO", "EP-SOCIOS", "EP-CATALOGO", "EP-AVISOS"})
HEADER_TYPES: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "title": str,
    "category": str,
    "version": int,
    "date": dt.date,
    "related": list,
    "epics": list,
}

ID_RE = re.compile(r"^DOC-\d{2}$")
H1_RE = re.compile(r"^# \S", re.MULTILINE)
H2_RE = re.compile(r"^## \S", re.MULTILINE)
TABLE_SEPARATOR_RE = re.compile(r"^\|\s*:?-{3,}:?\s*\|", re.MULTILINE)
NUMBERED_ITEM_RE = re.compile(r"^\s*\d+\.\s+\S", re.MULTILINE)
NUMBERED_RN_RE = re.compile(r"^\s*\d+\.\s+\*{0,2}RN-[A-Z]+-\d+", re.MULTILINE)
ARTICLE_HEADING_RE = re.compile(r"^#{2,6}\s+Artículo \d+", re.MULTILINE)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(
    r"(?<![\d\w])(?:\+34[\s.-]?)?[6-9]\d{2}"
    r"(?:[\s.-]?\d{3}[\s.-]?\d{3}|[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2})(?![\d\w])"
)
DNI_RE = re.compile(r"\b\d{8}[A-Za-z]\b")
NIE_RE = re.compile(r"\b[XYZ]\d{7}[A-Za-z]\b")
URL_RE = re.compile(r"https?://([^/\s)>\]`\"']+)")

MIN_DOCS, MAX_DOCS = 15, 25
MIN_PER_CATEGORY = 2
MIN_WORDS, MAX_WORDS = 300, 1500


class CorpusDocument(NamedTuple):
    """Documento del corpus con su cabecera YAML y su cuerpo Markdown."""

    path: Path
    header: dict[str, Any]
    body: str


def _split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Separa la cabecera YAML entre `---` del cuerpo del documento."""
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.DOTALL)
    if match is None:
        return {}, text
    header = yaml.safe_load(match.group(1))
    return (header if isinstance(header, dict) else {}), match.group(2)


@cache
def _load_documents() -> tuple[CorpusDocument, ...]:
    """Carga los documentos del corpus (`*/*.md`), sin el README de la raíz."""
    documents = []
    for path in sorted(CORPUS.glob("*/*.md")):
        header, body = _split_front_matter(path.read_text(encoding="utf-8"))
        documents.append(CorpusDocument(path=path, header=header, body=body))
    return tuple(documents)


def _doc_ids() -> list[str]:
    return [doc.path.stem for doc in _load_documents()]


def _all_markdown_files() -> list[Path]:
    return sorted(CORPUS.rglob("*.md"))


@cache
def _normativa_text() -> str:
    """Texto conjunto de la normativa sin marcas de negrita."""
    bodies = [doc.body for doc in _load_documents() if doc.path.parent.name == "normativa"]
    return "\n".join(bodies).replace("**", "")


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


DOCUMENTS = _load_documents()
DOC_PARAMS = pytest.mark.parametrize("doc", DOCUMENTS, ids=_doc_ids())
MD_PARAMS = pytest.mark.parametrize(
    "path", _all_markdown_files(), ids=lambda p: p.relative_to(CORPUS).as_posix()
)


# 1. Tamaño y distribución por categorías


def test_corpus_size_within_range() -> None:
    """El corpus tiene entre 15 y 25 documentos."""
    assert MIN_DOCS <= len(DOCUMENTS) <= MAX_DOCS, (
        f"El corpus tiene {len(DOCUMENTS)} documentos; se esperan entre {MIN_DOCS} y {MAX_DOCS}"
    )


def test_every_category_has_minimum_documents() -> None:
    """Cada una de las 7 categorías tiene al menos 2 documentos."""
    counts = Counter(doc.path.parent.name for doc in DOCUMENTS)
    short = {cat: counts.get(cat, 0) for cat in CATEGORIES if counts.get(cat, 0) < MIN_PER_CATEGORY}
    assert not short, f"Categorías con menos de {MIN_PER_CATEGORY} documentos: {short}"


def test_no_folders_outside_allowed_categories() -> None:
    """No hay carpetas en el corpus fuera de las 7 categorías válidas."""
    folders = {p.name for p in CORPUS.iterdir() if p.is_dir()}
    assert folders <= CATEGORIES, f"Carpetas no permitidas: {sorted(folders - CATEGORIES)}"


# 2. Cabeceras


@DOC_PARAMS
def test_header_has_all_keys_with_correct_types(doc: CorpusDocument) -> None:
    """La cabecera tiene todas las claves obligatorias con el tipo correcto."""
    missing = set(HEADER_TYPES) - set(doc.header)
    assert not missing, f"{doc.path.name}: faltan claves {sorted(missing)}"
    for key, expected in HEADER_TYPES.items():
        value = doc.header[key]
        assert isinstance(value, expected), (
            f"{doc.path.name}: '{key}' es {type(value).__name__}, se esperaba {expected}"
        )
    assert not isinstance(doc.header["version"], bool), f"{doc.path.name}: 'version' no es int"
    assert doc.header["title"].strip(), f"{doc.path.name}: 'title' vacío"


@DOC_PARAMS
def test_header_id_matches_pattern_and_filename(doc: CorpusDocument) -> None:
    """El id sigue el patrón DOC-NN y el nombre del archivo empieza por `<id>-`."""
    doc_id = str(doc.header.get("id"))
    assert ID_RE.match(doc_id), f"{doc.path.name}: id '{doc_id}' no cumple DOC-NN"
    assert doc.path.name.startswith(f"{doc_id}-"), (
        f"{doc.path.name}: el nombre debe empezar por '{doc_id}-'"
    )


def test_header_ids_are_unique() -> None:
    """Los ids de los documentos son únicos."""
    counts = Counter(doc.header.get("id") for doc in DOCUMENTS)
    duplicated = sorted(str(i) for i, n in counts.items() if n > 1)
    assert not duplicated, f"Ids duplicados: {duplicated}"


@DOC_PARAMS
def test_header_category_matches_folder(doc: CorpusDocument) -> None:
    """La categoría de la cabecera coincide con la carpeta y es válida."""
    category = doc.header.get("category")
    assert category == doc.path.parent.name, (
        f"{doc.path.name}: category '{category}' distinta de la carpeta '{doc.path.parent.name}'"
    )
    assert category in CATEGORIES, f"{doc.path.name}: categoría '{category}' no válida"


@DOC_PARAMS
def test_header_related_points_to_existing_other_documents(doc: CorpusDocument) -> None:
    """`related` solo contiene ids existentes y nunca el propio documento."""
    existing = {d.header.get("id") for d in DOCUMENTS}
    related = doc.header.get("related") or []
    unknown = [r for r in related if r not in existing]
    assert not unknown, f"{doc.path.name}: related apunta a ids inexistentes {unknown}"
    assert doc.header.get("id") not in related, f"{doc.path.name}: related se referencia a sí mismo"


@DOC_PARAMS
def test_header_epics_not_empty_and_allowed(doc: CorpusDocument) -> None:
    """`epics` no está vacío y solo contiene épicas permitidas."""
    epics = doc.header.get("epics") or []
    assert epics, f"{doc.path.name}: epics vacío"
    invalid = [e for e in epics if e not in EPICS]
    assert not invalid, f"{doc.path.name}: épicas no permitidas {invalid}"


@DOC_PARAMS
def test_header_date_is_valid(doc: CorpusDocument) -> None:
    """`date` es una fecha válida (no un texto ni una fecha con hora)."""
    value = doc.header.get("date")
    assert isinstance(value, dt.date) and not isinstance(value, dt.datetime), (
        f"{doc.path.name}: date '{value}' no es una fecha válida"
    )


# 3. Categoría prohibida


def test_no_memoria_folder_or_category() -> None:
    """La categoría `memoria` no aparece ni como carpeta ni como `category`."""
    assert not (CORPUS / FORBIDDEN_CATEGORY).exists(), "Existe la carpeta prohibida 'memoria'"
    offenders = [d.path.name for d in DOCUMENTS if d.header.get("category") == FORBIDDEN_CATEGORY]
    assert not offenders, f"Documentos con category 'memoria': {offenders}"


# 4. Estructura


@DOC_PARAMS
def test_body_has_single_h1_and_some_h2(doc: CorpusDocument) -> None:
    """Cada documento tiene exactamente un `# ` y al menos un `## `."""
    h1_count = len(H1_RE.findall(doc.body))
    assert h1_count == 1, f"{doc.path.name}: {h1_count} encabezados de nivel 1"
    assert H2_RE.search(doc.body), f"{doc.path.name}: no tiene encabezados de nivel 2"


@DOC_PARAMS
def test_body_word_count_within_range(doc: CorpusDocument) -> None:
    """El cuerpo tiene entre 300 y 1500 palabras."""
    words = len(doc.body.split())
    assert MIN_WORDS <= words <= MAX_WORDS, (
        f"{doc.path.name}: {words} palabras; se esperan entre {MIN_WORDS} y {MAX_WORDS}"
    )


def test_at_least_two_documents_with_tables() -> None:
    """Al menos 2 documentos contienen tablas Markdown."""
    with_tables = [d.path.name for d in DOCUMENTS if TABLE_SEPARATOR_RE.search(d.body)]
    assert len(with_tables) >= 2, f"Solo {len(with_tables)} documentos con tablas"


def _has_numbered_rules(body: str) -> bool:
    if NUMBERED_RN_RE.search(body):
        return True
    return bool(ARTICLE_HEADING_RE.search(body) and NUMBERED_ITEM_RE.search(body))


def test_at_least_two_documents_with_numbered_rules() -> None:
    """Al menos 2 documentos tienen listas numeradas de reglas (RN- o «Artículo N»)."""
    with_rules = [d.path.name for d in DOCUMENTS if _has_numbered_rules(d.body)]
    assert len(with_rules) >= 2, f"Solo {len(with_rules)} documentos con reglas numeradas"


# 5. Datos personales y URLs


@MD_PARAMS
def test_markdown_has_no_personal_data(path: Path) -> None:
    """Ningún .md del corpus (incluido el README) contiene emails, teléfonos, DNI ni NIE."""
    text = path.read_text(encoding="utf-8")
    for label, pattern in (
        ("email", EMAIL_RE),
        ("teléfono", PHONE_RE),
        ("DNI", DNI_RE),
        ("NIE", NIE_RE),
    ):
        found = pattern.findall(text)
        assert not found, f"{path.name}: posible {label} {found}"


def _is_fictitious_domain(host: str) -> bool:
    domain = host.split(":")[0].lower().rstrip(".")
    return (
        domain.endswith(".invalid")
        or domain.endswith(".example")
        or domain in {"example.com", "example.org", "example.net"}
        or domain.endswith((".example.com", ".example.org", ".example.net"))
    )


@MD_PARAMS
def test_markdown_urls_use_fictitious_domains(path: Path) -> None:
    """Todas las URLs http(s) usan dominios `.invalid` o `example`."""
    hosts = URL_RE.findall(path.read_text(encoding="utf-8"))
    real = [h for h in hosts if not _is_fictitious_domain(h)]
    assert not real, f"{path.name}: URLs con dominio no ficticio {real}"


@pytest.mark.parametrize(
    "host",
    ["api.villaficticia.invalid", "example.com", "docs.example.org", "portal.example"],
)
def test_fictitious_domain_accepted(host: str) -> None:
    """El helper de dominios acepta dominios ficticios."""
    assert _is_fictitious_domain(host)


@pytest.mark.parametrize("host", ["villaficticia.es", "example.com.es", "notexample.com"])
def test_real_domain_rejected(host: str) -> None:
    """El helper de dominios rechaza dominios que podrían ser reales."""
    assert not _is_fictitious_domain(host)


@pytest.mark.parametrize(
    "text", ["600000000", "600 000 000", "+34 900.00.00.00", "700-000-000", "+34600000000"]
)
def test_phone_pattern_detects_spanish_numbers(text: str) -> None:
    """El patrón de teléfonos detecta números españoles en sus formatos habituales."""
    assert PHONE_RE.search(text)


@pytest.mark.parametrize("text", ["2026-04-20", "500000000", "RN-SAN-02", "DOC-12"])
def test_phone_pattern_ignores_non_phones(text: str) -> None:
    """El patrón de teléfonos no marca fechas, ids ni números que no empiezan por 6-9."""
    assert not PHONE_RE.search(text)


# 6. Reglas clave de la normativa


@pytest.mark.parametrize(
    "phrase",
    [
        "3 reservas activas",
        "48 horas",
        "21 días",
        "2 renovaciones",
        "reservas pendientes",
        "12 meses",
    ],
)
def test_normativa_contains_key_rule(phrase: str) -> None:
    """La normativa recoge las reglas clave del dominio."""
    assert phrase in _normativa_text(), f"La normativa no contiene «{phrase}»"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (r"(\d+) reservas activas", "3"),
        (r"(\d+) horas", "48"),
        (r"(\d+) renovaciones", "2"),
        (r"duración del préstamo es de (\d+) días", "21"),
        (r"amplía el préstamo (\d+) días", "21"),
    ],
)
def test_normativa_values_are_consistent(pattern: str, expected: str) -> None:
    """La normativa no se contradice: cada regla clave tiene un único valor."""
    values = re.findall(pattern, _normativa_text(), flags=re.IGNORECASE)
    assert values, f"La normativa no contiene ninguna aparición de «{pattern}»"
    wrong = sorted(set(values) - {expected})
    assert not wrong, f"«{pattern}» toma valores {wrong}; solo se admite {expected}"


def test_normativa_has_no_superseded_values() -> None:
    """Los valores antiguos (p. ej. «72 horas») no aparecen en la normativa."""
    assert "72 horas" not in _normativa_text(), "La normativa contiene el valor antiguo «72 horas»"


@cache
def _non_actas_text() -> str:
    """Texto conjunto de todo el corpus salvo las actas, que pueden citar valores antiguos."""
    bodies = [doc.body for doc in _load_documents() if doc.path.parent.name != "actas"]
    return "\n".join(bodies).replace("**", "")


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        (r"(\d+) reservas activas", "3"),
        (r"(\d+) horas", "48"),
        (r"(\d+) renovaciones", "2"),
    ],
)
def test_corpus_values_are_consistent_outside_actas(pattern: str, expected: str) -> None:
    """Fuera de las actas, las reglas clave solo toman su valor vigente."""
    values = re.findall(pattern, _non_actas_text(), flags=re.IGNORECASE)
    wrong = sorted(set(values) - {expected})
    assert not wrong, f"«{pattern}» vale {wrong} fuera de las actas; solo se admite {expected}"


@pytest.mark.parametrize(
    "phrase",
    [
        "72 horas",  # plazo de recogida anterior a DOC-19
        "horas desde el aviso",  # el bloqueo empieza con la disponibilidad (RN-RES-05)
        "de la última renovación",  # la renovación suma 21 días al vencimiento vigente
        "24 meses",  # el historial es de 12 meses (DEMO-4 en tests/fakes/dataset.py)
    ],
)
def test_corpus_has_no_contradicting_phrases_outside_actas(phrase: str) -> None:
    """Fuera de las actas no aparecen formulaciones que contradicen las reglas vigentes."""
    assert phrase not in _non_actas_text(), f"El corpus contiene «{phrase}» fuera de las actas"


# 7. Coherencia con el README


def test_readme_lists_every_document_id() -> None:
    """Todos los ids de documento aparecen en el README del corpus."""
    readme = _readme_text()
    missing = [str(d.header.get("id")) for d in DOCUMENTS if str(d.header.get("id")) not in readme]
    assert not missing, f"Ids ausentes en el README: {missing}"


def test_readme_mentions_every_epic() -> None:
    """Todas las épicas usadas en los documentos aparecen en el README."""
    readme_epics = set(re.findall(r"EP-[A-Z]+", _readme_text()))
    used = {e for d in DOCUMENTS for e in (d.header.get("epics") or [])}
    missing = sorted(used - readme_epics)
    assert not missing, f"Épicas ausentes en el README: {missing}"


@pytest.mark.parametrize("key", ["DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"])
def test_readme_mentions_demo_keys(key: str) -> None:
    """El README menciona las claves DEMO-1 a DEMO-4 del dataset de los fakes."""
    assert re.search(rf"\b{key}\b", _readme_text()), f"El README no menciona {key}"
