"""Validación del seed de Jira `data/seed/jira/seed-villaficticia.csv` (T-15, D-06).

Comprueba el formato importable (cabecera, columnas, tipos y jerarquía), la ausencia de PII,
los vínculos «relates to» (RF-19), el prefijo `[HU-XX]` (R-05), la ausencia de subtareas (D-09),
la coherencia con `tests/fakes/dataset.py` y la mezcla de HU completas e incompletas (RF-18).
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

from tests.fakes.dataset import EPIC, STORIES, renewal_story

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "data" / "seed" / "jira" / "seed-villaficticia.csv"

EXPECTED_HEADER = [
    "Issue ID",
    "Parent",
    "Issue Type",
    "Summary",
    "Description",
    "Priority",
    "Labels",
    "Labels",
    'Link "Relates"',
]
SEED_LABEL = "seed-villaficticia"
EPIC_TYPE = "Epic"
STORY_TYPE = "Story"
FAKE_EPIC_ISSUE_ID = "1"
FAKE_STORY_ISSUE_IDS = {"2": "DEMO-2", "3": "DEMO-3", "4": "DEMO-4"}
RENEWAL_ISSUE_ID = "3"

HU_SUMMARY_RE = re.compile(r"^\[HU-\d{2}\] \S")
HU_ID_RE = re.compile(r"HU-\d{2}")
CA_HEADING_RE = re.compile(r"^h3\. (CA-\d+) · (.+)$", re.MULTILINE)
RN_DEFINITION_RE = re.compile(r"^\* \*(RN-\d+)\*:", re.MULTILINE)
TEMPLATE_SECTIONS = (
    "h2. Historia de usuario",
    "h2. Objetivo de negocio",
    "h2. Alcance",
    "h2. Criterios de aceptación",
    "h2. Reglas de negocio",
    "h2. Dependencias",
)
ACCEPTANCE_SECTION = "h2. Criterios de aceptación"
GHERKIN_BLOCK_RE = re.compile(r"\{code\}\n(Escenario: .+?)\{code\}", re.DOTALL)

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "teléfono (9+ dígitos seguidos)": re.compile(r"\d{9,}"),
    "teléfono (con separadores)": re.compile(r"(?<!\d)(?:\d[\s.-]?){8}\d(?!\d)"),
    "prefijo +34": re.compile(r"\+\s?34"),
    "DNI": re.compile(r"\b\d{8}[A-Z]\b"),
    "NIE": re.compile(r"\b[XYZ]\d{7}[A-Z]\b"),
    "URL http": re.compile(r"(?i)https?://"),
}


@dataclass(frozen=True)
class SeedRow:
    """Fila del CSV con las columnas con nombre (las dos `Labels` se agrupan)."""

    issue_id: str
    parent: str
    issue_type: str
    summary: str
    description: str
    priority: str
    labels: tuple[str, ...]
    relates: str

    def cells(self) -> tuple[str, ...]:
        return (
            self.issue_id,
            self.parent,
            self.issue_type,
            self.summary,
            self.description,
            self.priority,
            *self.labels,
            self.relates,
        )


@cache
def read_raw() -> tuple[tuple[str, ...], ...]:
    """Lee el CSV en UTF-8 con `csv.reader` (la cabecera tiene `Labels` duplicada)."""
    with CSV_PATH.open(encoding="utf-8", newline="") as handle:
        return tuple(tuple(row) for row in csv.reader(handle))


def to_row(raw: tuple[str, ...]) -> SeedRow:
    return SeedRow(
        issue_id=raw[0],
        parent=raw[1],
        issue_type=raw[2],
        summary=raw[3],
        description=raw[4],
        priority=raw[5],
        labels=(raw[6], raw[7]),
        relates=raw[8],
    )


@cache
def seed_rows() -> tuple[SeedRow, ...]:
    return tuple(to_row(raw) for raw in read_raw()[1:])


def rows_by_id() -> dict[str, SeedRow]:
    return {row.issue_id: row for row in seed_rows()}


def epics() -> list[SeedRow]:
    return [row for row in seed_rows() if row.issue_type == EPIC_TYPE]


def stories() -> list[SeedRow]:
    return [row for row in seed_rows() if row.issue_type == STORY_TYPE]


def full_text() -> str:
    return "\n".join(cell for row in seed_rows() for cell in row.cells())


def story_ids() -> list[str]:
    return [row.issue_id for row in stories()]


def complete_story_ids() -> list[str]:
    return [row.issue_id for row in stories() if CA_HEADING_RE.search(row.description)]


def numbers_before(word: str, text: str) -> list[int]:
    return [int(match) for match in re.findall(rf"(\d+)\s+{word}\b", text)]


def sentences_with(fragment: str, text: str) -> list[str]:
    return [s for s in re.split(r"[.\n]", text) if fragment in s.lower()]


# --- Criterio 1: lectura, cabecera y número de columnas -----------------------------------


def test_csv_reads_as_utf8_when_opened_with_csv_module() -> None:
    """Criterio 1 (D-06): el CSV existe y se decodifica en UTF-8 sin errores."""
    assert CSV_PATH.is_file(), f"No existe el seed en {CSV_PATH}"
    assert len(read_raw()) > 1, "El CSV no tiene filas de datos"


def test_csv_has_no_bom_when_read_as_bytes() -> None:
    """Criterio 1 (D-06): sin BOM, para que la primera columna sea exactamente `Issue ID`."""
    assert not CSV_PATH.read_bytes().startswith(b"\xef\xbb\xbf")


def test_header_matches_expected_when_parsed() -> None:
    """Criterio 1 (D-06): la cabecera es exactamente la esperada (con `Labels` duplicada)."""
    assert list(read_raw()[0]) == EXPECTED_HEADER


def test_all_rows_have_header_width_when_parsed() -> None:
    """Criterio 1 (D-06): todas las filas tienen el mismo número de columnas que la cabecera."""
    width = len(EXPECTED_HEADER)
    bad = {index: len(raw) for index, raw in enumerate(read_raw()) if len(raw) != width}
    assert not bad, f"Filas con un número de columnas distinto de {width}: {bad}"


def test_multiline_descriptions_are_single_cells_when_parsed() -> None:
    """Criterio 1 (D-06): las descripciones multilínea entre comillas quedan en una celda."""
    assert any("\n" in row.description for row in stories())
    assert len(seed_rows()) == 17


# --- Criterio 2: tipos de incidencia --------------------------------------------------------


def test_epic_count_in_range_when_counted() -> None:
    """Criterio 2 (D-06): hay entre 3 y 4 épicas."""
    assert 3 <= len(epics()) <= 4, f"Épicas: {len(epics())}"


def test_story_count_in_range_when_counted() -> None:
    """Criterio 2 (D-06): hay entre 10 y 15 HU."""
    assert 10 <= len(stories()) <= 15, f"HU: {len(stories())}"


def test_only_epic_and_story_types_when_listed() -> None:
    """Criterio 2 (D-09): solo hay `Epic` y `Story`; en particular, ninguna subtarea."""
    types = Counter(row.issue_type for row in seed_rows())
    assert set(types) <= {EPIC_TYPE, STORY_TYPE}, f"Tipos no permitidos: {types}"
    assert not any("sub" in t.lower() for t in types), "El CSV no debe llevar subtareas (D-09)"


def test_epic_issue_ids_are_expected_when_listed() -> None:
    """Criterio 2 (D-06): las épicas son los Issue ID 1, 6, 10 y 14."""
    assert [row.issue_id for row in epics()] == ["1", "6", "10", "14"]


# --- Criterio 3: jerarquía e Issue ID -------------------------------------------------------


def test_issue_ids_are_numeric_when_listed() -> None:
    """Criterio 3 (D-06): todos los Issue ID son numéricos."""
    non_numeric = [row.issue_id for row in seed_rows() if not row.issue_id.isdigit()]
    assert not non_numeric, f"Issue ID no numéricos: {non_numeric}"


def test_issue_ids_are_unique_when_listed() -> None:
    """Criterio 3 (D-06): los Issue ID no se repiten."""
    duplicated = [k for k, n in Counter(r.issue_id for r in seed_rows()).items() if n > 1]
    assert not duplicated, f"Issue ID repetidos: {duplicated}"


def test_epics_have_no_parent_when_listed() -> None:
    """Criterio 3 (D-06): las épicas no tienen Parent."""
    with_parent = [row.issue_id for row in epics() if row.parent]
    assert not with_parent, f"Épicas con Parent: {with_parent}"


@pytest.mark.parametrize("issue_id", story_ids())
def test_story_parent_is_existing_epic_when_set(issue_id: str) -> None:
    """Criterio 3 (D-06): cada HU tiene un Parent que existe y es una épica."""
    by_id = rows_by_id()
    parent = by_id[issue_id].parent
    assert parent, f"La HU {issue_id} no tiene Parent"
    assert parent in by_id, f"El Parent {parent} de la HU {issue_id} no existe"
    assert by_id[parent].issue_type == EPIC_TYPE, f"El Parent {parent} no es una épica"


# --- Criterio 4: vínculos «relates to» (RF-19) ----------------------------------------------


def test_relates_links_point_to_other_existing_issues_when_set() -> None:
    """Criterio 4 (RF-19): cada vínculo apunta a un Issue ID existente distinto de sí mismo."""
    by_id = rows_by_id()
    for row in seed_rows():
        if not row.relates:
            continue
        assert row.relates in by_id, f"{row.issue_id} enlaza con {row.relates}, que no existe"
        assert row.relates != row.issue_id, f"{row.issue_id} se enlaza consigo mismo"


def test_relates_links_count_at_least_two_when_counted() -> None:
    """Criterio 4 (RF-19): hay al menos 2 vínculos para poder analizar el impacto."""
    links = [row for row in seed_rows() if row.relates]
    assert len(links) >= 2, f"Vínculos: {len(links)}"


def test_relates_links_match_readme_when_listed() -> None:
    """Criterio 4 (RF-19): los 6 vínculos coinciden con la tabla del README."""
    links = {(row.issue_id, row.relates) for row in seed_rows() if row.relates}
    expected = {("3", "2"), ("5", "2"), ("12", "2"), ("17", "2"), ("15", "3"), ("16", "3")}
    assert links == expected


# --- Criterio 5: prefijo [HU-XX] (R-05) ----------------------------------------------------


@pytest.mark.parametrize("issue_id", story_ids())
def test_story_summary_has_hu_prefix_when_story(issue_id: str) -> None:
    """Criterio 5 (R-05): el título de la HU empieza por `[HU-XX] ` seguido de texto."""
    summary = rows_by_id()[issue_id].summary
    assert HU_SUMMARY_RE.match(summary), f"Título sin prefijo [HU-XX]: {summary!r}"
    assert len(HU_ID_RE.findall(summary)) == 1, f"El título repite el ID: {summary!r}"


def test_story_hu_ids_are_unique_when_listed() -> None:
    """Criterio 5 (R-05): ningún ID `HU-XX` se repite entre HU."""
    ids = [HU_ID_RE.findall(row.summary)[0] for row in stories()]
    duplicated = [k for k, n in Counter(ids).items() if n > 1]
    assert not duplicated, f"IDs de HU repetidos: {duplicated}"


def test_epic_summary_has_no_hu_prefix_when_epic() -> None:
    """Criterio 5 (R-05): las épicas no llevan el prefijo `[HU-XX]`."""
    prefixed = [row.summary for row in epics() if HU_ID_RE.search(row.summary)]
    assert not prefixed, f"Épicas con prefijo de HU: {prefixed}"


# --- Criterio 6: etiquetas ------------------------------------------------------------------


def test_all_rows_have_seed_label_when_listed() -> None:
    """Criterio 6 (D-06): todas las filas llevan `seed-villaficticia` (para deshacer)."""
    missing = [row.issue_id for row in seed_rows() if SEED_LABEL not in row.labels]
    assert not missing, f"Filas sin la etiqueta {SEED_LABEL}: {missing}"


def test_labels_have_no_whitespace_when_listed() -> None:
    """Criterio 6 (D-06): las etiquetas no contienen espacios (Jira las partiría)."""
    bad = [
        (row.issue_id, label)
        for row in seed_rows()
        for label in row.labels
        if re.search(r"\s", label)
    ]
    assert not bad, f"Etiquetas con espacios: {bad}"


def test_story_theme_label_matches_parent_when_story() -> None:
    """Criterio 6 (README): la etiqueta temática de cada HU coincide con la de su épica."""
    by_id = rows_by_id()
    bad = [row.issue_id for row in stories() if row.labels[1] != by_id[row.parent].labels[1]]
    assert not bad, f"HU con etiqueta temática distinta de su épica: {bad}"


# --- Criterio 7: sin PII ni URLs ------------------------------------------------------------


@pytest.mark.parametrize("kind", list(PII_PATTERNS))
def test_no_pii_in_any_cell_when_scanned(kind: str) -> None:
    """Criterio 7 (principio 3, RGPD): ninguna celda contiene PII ni URLs `http`."""
    pattern = PII_PATTERNS[kind]
    hits = [
        (row.issue_id, match.group(0))
        for row in seed_rows()
        for cell in row.cells()
        for match in pattern.finditer(cell)
    ]
    assert not hits, f"Posible {kind} en el seed: {hits}"


@pytest.mark.parametrize(
    ("kind", "sample"),
    [
        ("email", "persona.ficticia@example.invalid"),
        ("teléfono (9+ dígitos seguidos)", "600000000"),
        ("teléfono (con separadores)", "600 00 00 00"),
        ("prefijo +34", "+34 600"),
        ("DNI", "00000000T"),
        ("NIE", "X0000000T"),
        ("URL http", "https://ejemplo.invalid"),
    ],
)
def test_pii_pattern_detects_sample_when_present(kind: str, sample: str) -> None:
    """Criterio 7: control negativo, cada patrón de PII detecta un valor ficticio."""
    assert PII_PATTERNS[kind].search(sample)


# --- Criterio 8: coherencia con tests/fakes/dataset.py y reglas del dominio ----------------


def test_first_epic_matches_fake_epic_when_compared() -> None:
    """Criterio 8: la épica con Issue ID 1 tiene el mismo summary que `EPIC`."""
    epic = rows_by_id()[FAKE_EPIC_ISSUE_ID]
    assert epic.issue_type == EPIC_TYPE
    assert epic.summary == EPIC.summary


@pytest.mark.parametrize(("issue_id", "fake_key"), sorted(FAKE_STORY_ISSUE_IDS.items()))
def test_story_matches_fake_story_when_compared(issue_id: str, fake_key: str) -> None:
    """Criterio 8: las HU 2, 3 y 4 equivalen a DEMO-2, DEMO-3 y DEMO-4 y cuelgan de la 1."""
    row = rows_by_id()[issue_id]
    assert row.summary == STORIES[fake_key].summary
    assert row.parent == FAKE_EPIC_ISSUE_ID


@pytest.mark.parametrize(
    ("word", "expected"),
    [("reservas activas", 3), ("horas", 48), ("renovaciones", 2)],
)
def test_domain_number_is_consistent_when_mentioned(word: str, expected: int) -> None:
    """Criterio 8: todo número seguido de la expresión coincide con la regla y aparece."""
    numbers = numbers_before(word, full_text())
    assert numbers, f"La regla «{word}» no aparece en el seed"
    wrong = [n for n in numbers if n != expected]
    assert not wrong, f"Valores incoherentes antes de «{word}»: {wrong} (se esperaba {expected})"


def test_loan_duration_is_21_days_when_mentioned() -> None:
    """Criterio 8: en cada frase con «préstamo dura» los días son 21, y aparece al menos una."""
    sentences = sentences_with("préstamo dura", full_text())
    assert sentences, "La regla de duración del préstamo no aparece en el seed"
    for sentence in sentences:
        days = numbers_before("días", sentence)
        assert days, f"Frase sin número de días: {sentence!r}"
        assert set(days) == {21}, f"Duración incoherente: {sentence!r}"


def test_renewal_extends_21_days_when_mentioned() -> None:
    """Criterio 8: el texto recoge que el vencimiento «se amplía 21 días»."""
    assert "se amplía 21 días" in full_text()


def test_domain_checks_tolerate_written_and_symbolic_days_when_scanned() -> None:
    """Criterio 8 (límite): «tres días naturales» y «N días» no se leen como duraciones."""
    text = full_text()
    assert "tres días naturales" in text
    assert "N días" in text
    assert all("préstamo dura" not in s.lower() for s in sentences_with("n días", text))


# --- Criterio 9: estructura de las HU completas e incompletas (RF-18) -----------------------


def test_complete_stories_exist_when_listed() -> None:
    """Criterio 9 (RF-18): las HU completas son las del README (HU-01, 02, 05, 08, 09, 11, 12)."""
    assert complete_story_ids() == ["2", "3", "7", "11", "12", "15", "16"]


@pytest.mark.parametrize("issue_id", complete_story_ids())
def test_complete_story_has_template_sections_when_complete(issue_id: str) -> None:
    """Criterio 9: cada HU completa contiene las secciones de la plantilla."""
    description = rows_by_id()[issue_id].description
    missing = [section for section in TEMPLATE_SECTIONS if section not in description]
    assert not missing, f"La HU {issue_id} no tiene las secciones: {missing}"


@pytest.mark.parametrize("issue_id", complete_story_ids())
def test_complete_story_has_unique_ca_and_rn_ids_when_complete(issue_id: str) -> None:
    """Criterio 9 (trazabilidad): los IDs de CA y RN no se repiten dentro de la HU."""
    description = rows_by_id()[issue_id].description
    ca_ids = [ca_id for ca_id, _ in CA_HEADING_RE.findall(description)]
    rn_ids = RN_DEFINITION_RE.findall(description)
    assert ca_ids, f"La HU {issue_id} no define CA"
    assert rn_ids, f"La HU {issue_id} no define RN"
    assert len(ca_ids) == len(set(ca_ids)), f"CA repetidos en {issue_id}: {ca_ids}"
    assert len(rn_ids) == len(set(rn_ids)), f"RN repetidos en {issue_id}: {rn_ids}"


@pytest.mark.parametrize("issue_id", complete_story_ids())
def test_complete_story_criteria_are_gherkin_when_complete(issue_id: str) -> None:
    """Criterio 9 (RF-16): cada escenario de una HU completa tiene Dado, Cuando y Entonces."""
    description = rows_by_id()[issue_id].description
    scenarios = GHERKIN_BLOCK_RE.findall(description)
    assert len(scenarios) == len(CA_HEADING_RE.findall(description))
    for scenario in scenarios:
        for keyword in ("Dado ", "Cuando ", "Entonces "):
            assert f"  {keyword}" in scenario, f"Falta «{keyword.strip()}» en {issue_id}"


def test_renewal_story_contains_fake_ca_titles_when_compared() -> None:
    """Criterio 9: HU-02 incluye CA-01 y CA-02 con los títulos de `renewal_story()`."""
    headings = dict(CA_HEADING_RE.findall(rows_by_id()[RENEWAL_ISSUE_ID].description))
    for criterion in renewal_story().acceptance_criteria:
        assert headings.get(criterion.id) == criterion.title, f"{criterion.id} no coincide"


def test_renewal_story_contains_fake_rn_descriptions_when_compared() -> None:
    """Criterio 9: HU-02 incluye RN-01 y RN-02 con las descripciones de `renewal_story()`."""
    description = rows_by_id()[RENEWAL_ISSUE_ID].description
    for rule in renewal_story().business_rules:
        assert f"*{rule.id}*: {rule.description}" in description, f"{rule.id} no coincide"


def test_some_story_lacks_acceptance_section_when_incomplete() -> None:
    """Criterio 9 (RF-18): hay al menos una HU sin sección «Criterios de aceptación»."""
    incomplete = [row.issue_id for row in stories() if ACCEPTANCE_SECTION not in row.description]
    assert incomplete, "Todas las HU tienen CA: falta una HU incompleta a propósito"
