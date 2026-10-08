"""Pruebas de la fragmentación por encabezados + recursiva con metadatos (T-13, RF-09).

Cubre `core/rag/chunking.py`: estimación de tokens, corte por secciones Markdown, división
recursiva con solapamiento, construcción de `Chunk` con metadatos (RF-10) y uso de la
configuración `rag` de `config/models.yaml`. Las memorias no se fragmentan (SPEC-00 §6).
Todos los datos son sintéticos (Faker es_ES con semilla fija o valores ficticios).
"""

import dataclasses
import hashlib
import re
from itertools import pairwise
from pathlib import Path

import pytest
import yaml
from faker import Faker

from adapters.base import Chunk
from core.config import AppConfig, ModelsConfig, Settings, load_models_config
from core.rag.chunking import (
    Section,
    chunk_document,
    chunk_with_config,
    estimate_tokens,
    split_recursive,
    split_sections,
)
from core.rag.documents import IngestedDocument
from tests.fixtures import MODELS_FIXTURE

ROOT = Path(__file__).resolve().parents[2]
DOC_02 = ROOT / "data" / "seed" / "corpus" / "politicas" / "DOC-02-reglamento-reservas.md"

WORD_RE = re.compile(r"\S+")


# --------------------------------------------------------------------------- utilidades


def _fake() -> Faker:
    """Faker es_ES con semilla fija para que las pruebas sean deterministas."""
    fake = Faker("es_ES")
    fake.seed_instance(20260930)
    return fake


def _make_doc(
    text: str,
    *,
    doc_id: str = "DOC-99",
    title: str = "Documento ficticio de prueba",
    category: str = "politicas",
    source_path: str = "data/seed/corpus/politicas/DOC-99-ficticio.md",
    metadata: dict[str, str] | None = None,
) -> IngestedDocument:
    """Construye un `IngestedDocument` sintético a mano (T-12 se implementa en paralelo)."""
    return IngestedDocument(
        id=doc_id,
        title=title,
        category=category,
        classified_by="metadata",
        source_path=source_path,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
        metadata=metadata or {},
    )


def _unique_words(count: int) -> list[str]:
    """Palabras únicas y ficticias (w0000, w0001…) para rastrear pérdidas y solapes."""
    return [f"w{i:04d}" for i in range(count)]


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _non_empty_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _suffix_prefix_overlap(previous: str, following: str) -> str:
    """Texto más largo que es a la vez sufijo de `previous` y prefijo de `following`.

    Tolera espacios en los bordes (el implementador puede recortar los fragmentos).
    """
    left = previous.rstrip()
    right = following.lstrip()
    for size in range(min(len(left), len(right)), 0, -1):
        if right.startswith(left[-size:]):
            return left[-size:]
    return ""


def _paragraphs_text(paragraphs: int, sentences: int = 6) -> str:
    fake = _fake()
    return "\n\n".join(fake.paragraph(nb_sentences=sentences) for _ in range(paragraphs))


def _strip_front_matter(raw: str) -> tuple[dict[str, object], str]:
    """Separa la cabecera YAML (entre los dos primeros '---') del cuerpo Markdown."""
    _, header, body = raw.split("---", 2)
    return yaml.safe_load(header), body.lstrip("\n")


MULTI_SECTION_MD = (
    "Preámbulo ficticio antes del primer encabezado.\n"
    "\n"
    "# Reglamento ficticio\n"
    "\n"
    "Introducción del reglamento ficticio.\n"
    "\n"
    "## Ámbito\n"
    "\n"
    "Se aplica a la sede ficticia de Villaficticia.\n"
    "\n"
    "## Reglas de negocio\n"
    "\n"
    "1. **RN-FIC-01.** Regla ficticia uno.\n"
    "\n"
    "### Detalle\n"
    "\n"
    "Detalle ficticio de la regla.\n"
    "\n"
    "## Excepciones\n"
    "\n"
    "Excepción ficticia.\n"
)


# --------------------------------------------------------------------------- estimate_tokens


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("x" * 400, 100), ("x" * 401, 101)],
)
def test_estimate_tokens_uses_ceil_of_chars_div_4_for_given_lengths(
    text: str, expected: int
) -> None:
    """RF-09: la estimación de tokens es ceil(len/4) y vale 0 para el texto vacío."""
    assert estimate_tokens(text) == expected


# --------------------------------------------------------------------------- split_sections


def test_split_sections_returns_empty_list_when_markdown_is_empty() -> None:
    """RF-09 (límite): un texto vacío o solo con espacios no produce secciones."""
    assert split_sections("") == []
    assert split_sections("  \n\n \t\n") == []


def test_split_sections_returns_single_root_section_when_there_are_no_headings() -> None:
    """RF-09: sin encabezados todo el texto forma una sección con path vacío."""
    md = "Texto ficticio sin encabezados.\n\nSegundo párrafo ficticio."
    sections = split_sections(md)

    assert len(sections) == 1
    assert sections[0].path == ()
    assert _non_empty_lines(sections[0].text) == _non_empty_lines(md)


def test_split_sections_builds_heading_hierarchy_when_levels_are_nested() -> None:
    """RF-09: path refleja la jerarquía; un '##' nuevo cierra los '###' anteriores."""
    sections = split_sections(MULTI_SECTION_MD)

    assert [s.path for s in sections] == [
        (),
        ("Reglamento ficticio",),
        ("Reglamento ficticio", "Ámbito"),
        ("Reglamento ficticio", "Reglas de negocio"),
        ("Reglamento ficticio", "Reglas de negocio", "Detalle"),
        ("Reglamento ficticio", "Excepciones"),
    ]


def test_split_sections_includes_own_heading_line_when_section_has_heading() -> None:
    """RF-09: el texto de cada sección empieza por su propia línea de encabezado."""
    sections = split_sections(MULTI_SECTION_MD)
    by_path = {s.path: s for s in sections}

    assert by_path[("Reglamento ficticio", "Ámbito")].text.lstrip().startswith("## Ámbito")
    detail = by_path[("Reglamento ficticio", "Reglas de negocio", "Detalle")]
    assert detail.text.lstrip().startswith("### Detalle")
    assert "Detalle ficticio de la regla." in detail.text
    assert "RN-FIC-01" not in detail.text


def test_split_sections_puts_preamble_in_root_section_when_text_precedes_first_heading() -> None:
    """RF-09: el texto anterior al primer encabezado forma una sección con path ()."""
    first = split_sections(MULTI_SECTION_MD)[0]

    assert first.path == ()
    assert "Preámbulo ficticio" in first.text
    assert "#" not in first.text


def test_split_sections_resets_path_when_new_level_one_heading_appears() -> None:
    """RF-09: un nuevo '#' cierra toda la jerarquía anterior."""
    md = "# Primero\n\n## Sub\n\ntexto a\n\n# Segundo\n\ntexto b\n"
    paths = [s.path for s in split_sections(md)]

    assert paths == [("Primero",), ("Primero", "Sub"), ("Segundo",)]


@pytest.mark.parametrize("level", [1, 2, 3, 4, 5, 6])
def test_split_sections_recognizes_atx_heading_when_level_is_between_1_and_6(level: int) -> None:
    """RF-09: se reconocen encabezados ATX de nivel 1 a 6."""
    md = f"Intro ficticia.\n\n{'#' * level} Título ficticio\n\nCuerpo ficticio.\n"
    sections = split_sections(md)

    assert len(sections) == 2
    assert sections[1].path[-1] == "Título ficticio"


def test_split_sections_strips_hashes_and_spaces_from_titles_when_building_path() -> None:
    """RF-09: los títulos del path van sin '#' ni espacios sobrantes."""
    md = "#   Título con espacios   \n\ncuerpo\n\n##  Subtítulo  \n\ncuerpo\n"
    paths = [s.path for s in split_sections(md)]

    assert paths == [("Título con espacios",), ("Título con espacios", "Subtítulo")]


def test_split_sections_ignores_hash_lines_when_they_are_inside_code_fences() -> None:
    """RF-09: las líneas con '#' dentro de bloques ``` no son encabezados."""
    md = (
        "# Guía ficticia\n"
        "\n"
        "```bash\n"
        "# comentario ficticio, no es un encabezado\n"
        "## tampoco lo es\n"
        "echo hola\n"
        "```\n"
        "\n"
        "## Siguiente\n"
        "\n"
        "texto\n"
    )
    sections = split_sections(md)

    assert [s.path for s in sections] == [("Guía ficticia",), ("Guía ficticia", "Siguiente")]
    assert "# comentario ficticio" in sections[0].text
    assert "## tampoco lo es" in sections[0].text


def test_split_sections_does_not_treat_hash_without_space_as_heading() -> None:
    """RF-09 (negativa): '#etiqueta' al inicio de línea no es un encabezado ATX."""
    md = "# Título\n\n#etiqueta ficticia\n"
    sections = split_sections(md)

    assert len(sections) == 1
    assert "#etiqueta ficticia" in sections[0].text


def test_split_sections_omits_whitespace_only_sections_but_keeps_heading_only_ones() -> None:
    """RF-09: se omiten secciones vacías; una sección con solo su encabezado se conserva."""
    md = "\n   \n\n# Título\n\n## Vacía\n\n## Con texto\n\ncontenido ficticio\n"
    sections = split_sections(md)

    assert [s.path for s in sections] == [
        ("Título",),
        ("Título", "Vacía"),
        ("Título", "Con texto"),
    ]
    assert sections[1].text.strip() == "## Vacía"


def test_split_sections_preserves_all_non_empty_text_when_sections_are_joined() -> None:
    """RF-09: unir los text de las secciones con '\\n' conserva todo el texto no vacío."""
    sections = split_sections(MULTI_SECTION_MD)
    joined = "\n".join(s.text for s in sections)

    assert _non_empty_lines(joined) == _non_empty_lines(MULTI_SECTION_MD)


def test_split_sections_returns_frozen_section_instances() -> None:
    """RF-09: Section es un dataclass inmutable."""
    section = split_sections("# Título\n\ntexto\n")[0]

    assert isinstance(section, Section)
    with pytest.raises(dataclasses.FrozenInstanceError):
        section.text = "otro"  # type: ignore[misc]


# --------------------------------------------------------------------------- split_recursive


def test_split_recursive_returns_text_unchanged_when_it_fits_in_chunk() -> None:
    """RF-09: si el texto cabe en chunk_tokens se devuelve tal cual en una lista."""
    text = "Texto ficticio corto."

    assert split_recursive(text, chunk_tokens=50, overlap_tokens=10) == [text]


def test_split_recursive_returns_text_unchanged_when_size_equals_limit() -> None:
    """RF-09 (límite): estimate_tokens == chunk_tokens todavía cabe en un fragmento."""
    text = "x" * 40  # 10 tokens estimados

    assert split_recursive(text, chunk_tokens=10, overlap_tokens=2) == [text]


def test_split_recursive_splits_text_when_one_char_over_limit() -> None:
    """RF-09 (límite): un token estimado por encima del límite obliga a dividir."""
    text = " ".join(["abcd"] * 9)  # 44 caracteres → 11 tokens

    fragments = split_recursive(text, chunk_tokens=10, overlap_tokens=0)

    assert len(fragments) >= 2
    assert all(estimate_tokens(f) <= 10 for f in fragments)


@pytest.mark.parametrize(("chunk_tokens", "overlap_tokens"), [(100, 20), (60, 0), (200, 50)])
def test_split_recursive_respects_chunk_limit_when_text_is_long(
    chunk_tokens: int, overlap_tokens: int
) -> None:
    """RF-09: ningún fragmento supera chunk_tokens estimados."""
    text = _paragraphs_text(paragraphs=12)
    assert estimate_tokens(text) > chunk_tokens

    fragments = split_recursive(text, chunk_tokens, overlap_tokens)

    assert len(fragments) >= 2
    assert all(estimate_tokens(f) <= chunk_tokens for f in fragments)
    assert all(f.strip() for f in fragments)


def test_split_recursive_loses_no_words_when_text_is_split() -> None:
    """RF-09: cada palabra del original aparece en algún fragmento."""
    text = _paragraphs_text(paragraphs=10)

    fragments = split_recursive(text, chunk_tokens=80, overlap_tokens=15)
    fragment_words = {w for f in fragments for w in _words(f)}

    assert set(_words(text)) <= fragment_words


def test_split_recursive_keeps_word_order_when_text_is_split() -> None:
    """RF-09: la secuencia original de palabras se recupera en orden en los fragmentos."""
    words = _unique_words(600)
    text = " ".join(words)

    fragments = split_recursive(text, chunk_tokens=50, overlap_tokens=10)
    seen: list[str] = []
    for fragment in fragments:
        for word in _words(fragment):
            if word not in seen:
                seen.append(word)

    assert seen == words


def test_split_recursive_returns_contiguous_substrings_when_text_is_split() -> None:
    """RF-09: cada fragmento es un trozo contiguo del original (sin reordenar ni inventar)."""
    text = _paragraphs_text(paragraphs=10)

    fragments = split_recursive(text, chunk_tokens=70, overlap_tokens=10)

    for fragment in fragments:
        assert fragment.strip() in text


def test_split_recursive_overlaps_consecutive_fragments_when_overlap_is_positive() -> None:
    """RF-09: el inicio del fragmento i+1 repite el final del fragmento i (≈ overlap_tokens)."""
    overlap_tokens = 20
    text = " ".join(_unique_words(800))

    fragments = split_recursive(text, chunk_tokens=100, overlap_tokens=overlap_tokens)

    assert len(fragments) >= 3
    for previous, following in pairwise(fragments):
        shared = _suffix_prefix_overlap(previous, following)
        assert re.search(r"w\d{4}", shared), "sin solapamiento entre fragmentos consecutivos"
        assert estimate_tokens(shared) <= 2 * overlap_tokens


def test_split_recursive_has_no_overlap_when_overlap_is_zero() -> None:
    """RF-09 (límite): con overlap_tokens=0 los fragmentos consecutivos no comparten palabras."""
    text = " ".join(_unique_words(800))

    fragments = split_recursive(text, chunk_tokens=100, overlap_tokens=0)

    assert len(fragments) >= 3
    for previous, following in pairwise(fragments):
        assert not set(_words(previous)) & set(_words(following))


def test_split_recursive_prefers_paragraph_boundaries_when_paragraphs_fit() -> None:
    """RF-09: el primer separador es '\\n\\n'; si cada párrafo cabe, no se corta dentro de uno."""
    paragraphs = [" ".join(f"p{p}w{i:02d}" for i in range(20)) for p in range(8)]
    text = "\n\n".join(paragraphs)  # cada párrafo ≈ 40 tokens

    fragments = split_recursive(text, chunk_tokens=60, overlap_tokens=0)

    assert all(estimate_tokens(f) <= 60 for f in fragments)
    for fragment in fragments:
        for block in fragment.strip().split("\n\n"):
            assert block.strip() in paragraphs


def test_split_recursive_hard_cuts_by_characters_when_no_separator_exists() -> None:
    """RF-09: sin separadores se recurre a un corte duro por caracteres."""
    text = "".join(chr(ord("a") + i % 26) for i in range(1000))  # 250 tokens, sin espacios

    fragments = split_recursive(text, chunk_tokens=50, overlap_tokens=10)

    assert len(fragments) >= 5
    assert all(0 < estimate_tokens(f) <= 50 for f in fragments)
    assert text.startswith(fragments[0])
    assert text.endswith(fragments[-1])
    assert all(f in text for f in fragments)


def test_split_recursive_cuts_markdown_table_between_rows_when_table_is_long() -> None:
    """RF-09: una tabla Markdown larga se corta entre filas, nunca en mitad de una fila."""
    fake = _fake()
    header = "| Código | Descripción | Sede |\n|---|---|---|"
    rows = [
        f"| RN-FIC-{i:03d} | {fake.sentence(nb_words=6)} | Sede ficticia {i % 4} |"
        for i in range(60)
    ]
    text = header + "\n" + "\n".join(rows)
    valid_lines = set(header.splitlines()) | set(rows)

    fragments = split_recursive(text, chunk_tokens=120, overlap_tokens=20)

    assert len(fragments) >= 2
    assert all(estimate_tokens(f) <= 120 for f in fragments)
    for fragment in fragments:
        for line in _non_empty_lines(fragment):
            assert line.strip() in valid_lines, f"fila cortada: {line!r}"
    covered = {line.strip() for f in fragments for line in _non_empty_lines(f)}
    assert set(rows) <= covered


def test_split_recursive_cuts_single_row_when_row_alone_exceeds_limit() -> None:
    """RF-09 (límite): una fila que sola supera el límite sí se corta, respetando el máximo."""
    long_row = "| " + " ".join(_unique_words(120)) + " |"  # ≈ 180 tokens
    text = "| a | b |\n|---|---|\n" + long_row + "\n| c | d |"

    fragments = split_recursive(text, chunk_tokens=50, overlap_tokens=5)

    assert all(estimate_tokens(f) <= 50 for f in fragments)
    fragment_words = {w for f in fragments for w in _words(f)}
    assert set(_words(long_row)) <= fragment_words


@pytest.mark.parametrize(
    ("chunk_tokens", "overlap_tokens"),
    [(0, 0), (-5, 0), (10, -1), (10, 10), (10, 11)],
)
def test_split_recursive_raises_value_error_when_parameters_are_invalid(
    chunk_tokens: int, overlap_tokens: int
) -> None:
    """RF-09 (error): chunk_tokens <= 0, overlap < 0 u overlap >= chunk_tokens → ValueError."""
    long_text = _paragraphs_text(paragraphs=5)

    with pytest.raises(ValueError):
        split_recursive(long_text, chunk_tokens, overlap_tokens)


def test_split_recursive_raises_value_error_even_when_text_is_short() -> None:
    """RF-09 (error): los parámetros se validan aunque el texto quepa en un fragmento."""
    with pytest.raises(ValueError):
        split_recursive("corto", chunk_tokens=10, overlap_tokens=10)


# --------------------------------------------------------------------------- chunk_document


def test_chunk_document_returns_chunk_models_with_ids_and_ordinals() -> None:
    """RF-09/RF-10: ordinal desde 0, id '<doc>#<ordinal>', document_id y sin embedding."""
    doc = _make_doc(MULTI_SECTION_MD)

    chunks = chunk_document(doc, chunk_tokens=650, overlap_tokens=80)

    assert chunks
    assert all(isinstance(c, Chunk) for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert [c.id for c in chunks] == [f"DOC-99#{i}" for i in range(len(chunks))]
    assert all(c.document_id == "DOC-99" for c in chunks)
    assert all(c.embedding is None for c in chunks)
    assert all(c.content.strip() for c in chunks)


def test_chunk_document_keeps_one_chunk_per_section_when_sections_fit() -> None:
    """RF-09: primero se corta por encabezados; una sección que cabe es un único chunk."""
    doc = _make_doc(MULTI_SECTION_MD)

    chunks = chunk_document(doc, chunk_tokens=650, overlap_tokens=80)
    sections = split_sections(MULTI_SECTION_MD)

    assert len(chunks) == len(sections)
    for chunk, section in zip(chunks, sections, strict=True):
        assert chunk.content.strip() == section.text.strip()


def test_chunk_document_sets_section_breadcrumb_or_none_when_path_is_empty() -> None:
    """RF-10: section = ' > '.join(path); None para el preámbulo sin encabezado."""
    doc = _make_doc(MULTI_SECTION_MD)

    sections = [c.section for c in chunk_document(doc, chunk_tokens=650, overlap_tokens=80)]

    assert sections == [
        None,
        "Reglamento ficticio",
        "Reglamento ficticio > Ámbito",
        "Reglamento ficticio > Reglas de negocio",
        "Reglamento ficticio > Reglas de negocio > Detalle",
        "Reglamento ficticio > Excepciones",
    ]


def test_chunk_document_fills_metadata_when_document_has_extra_metadata() -> None:
    """RF-10: metadata incluye category, title, source, section y las claves de doc.metadata."""
    doc = _make_doc(
        MULTI_SECTION_MD,
        metadata={"version": "3", "related_key": "PRJ-123", "epics": "EP-FICTICIA"},
    )

    chunks = chunk_document(doc, chunk_tokens=650, overlap_tokens=80)

    for chunk in chunks:
        assert chunk.metadata["category"] == "politicas"
        assert chunk.metadata["title"] == "Documento ficticio de prueba"
        assert chunk.metadata["source"] == "data/seed/corpus/politicas/DOC-99-ficticio.md"
        assert chunk.metadata["version"] == "3"
        assert chunk.metadata["related_key"] == "PRJ-123"
        assert chunk.metadata["epics"] == "EP-FICTICIA"
        assert all(isinstance(v, str) for v in chunk.metadata.values())
        if chunk.section is None:
            assert "section" not in chunk.metadata
        else:
            assert chunk.metadata["section"] == chunk.section


def test_chunk_document_splits_long_section_keeping_section_and_limit() -> None:
    """RF-09: una sección larga se divide recursivamente; todos sus chunks conservan la sección."""
    body = _paragraphs_text(paragraphs=15)
    md = f"# Manual ficticio\n\n## Procedimiento largo\n\n{body}\n\n## Cierre\n\nFin ficticio.\n"
    doc = _make_doc(md, category="documentacion")

    chunks = chunk_document(doc, chunk_tokens=100, overlap_tokens=20)
    long_chunks = [c for c in chunks if c.section == "Manual ficticio > Procedimiento largo"]

    assert len(long_chunks) >= 2
    assert all(estimate_tokens(c.content) <= 100 for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].section == "Manual ficticio > Cierre"
    covered = {w for c in long_chunks for w in _words(c.content)}
    assert set(_words(body)) <= covered


def test_chunk_document_returns_single_chunk_when_category_is_memoria() -> None:
    """SPEC-00 §6: las memorias no se fragmentan aunque superen chunk_tokens."""
    body = _paragraphs_text(paragraphs=20)
    md = f"# Memoria PRJ-123\n\n## Resumen\n\n{body}\n\n## Decisiones\n\nDecisión ficticia.\n"
    doc = _make_doc(
        md,
        doc_id="MEM-PRJ-123",
        title="Memoria PRJ-123",
        category="memoria",
        source_path="data/memory/PRJ-123.md",
        metadata={"related_key": "PRJ-123"},
    )
    assert estimate_tokens(md) > 100

    chunks = chunk_document(doc, chunk_tokens=100, overlap_tokens=20)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.ordinal == 0
    assert chunk.id == "MEM-PRJ-123#0"
    assert chunk.document_id == "MEM-PRJ-123"
    assert chunk.content.strip() == md.strip()
    assert chunk.metadata["category"] == "memoria"
    assert chunk.metadata["related_key"] == "PRJ-123"
    assert chunk.metadata["source"] == "data/memory/PRJ-123.md"


def test_chunk_document_returns_no_chunks_when_text_is_blank() -> None:
    """RF-09 (límite): un documento sin texto no genera chunks vacíos."""
    doc = _make_doc("   \n\n  ")

    assert chunk_document(doc, chunk_tokens=650, overlap_tokens=80) == []


def test_chunk_document_is_deterministic_when_called_twice() -> None:
    """RF-09: la misma entrada produce los mismos chunks (reindexado idempotente)."""
    doc = _make_doc(MULTI_SECTION_MD + "\n" + _paragraphs_text(paragraphs=8))

    first = chunk_document(doc, chunk_tokens=100, overlap_tokens=20)
    second = chunk_document(doc, chunk_tokens=100, overlap_tokens=20)

    assert first == second


def test_chunk_document_raises_value_error_when_parameters_are_invalid() -> None:
    """RF-09 (error): parámetros de fragmentación inválidos → ValueError."""
    doc = _make_doc(MULTI_SECTION_MD)

    with pytest.raises(ValueError):
        chunk_document(doc, chunk_tokens=50, overlap_tokens=50)


# --------------------------------------------------------------------------- chunk_with_config


def test_chunk_with_config_uses_rag_settings_when_default_models_config(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-09: chunk_with_config usa rag.chunk_tokens=650 y overlap_tokens=80 de models.yaml."""
    config = AppConfig(Settings(_env_file=None), load_models_config(MODELS_FIXTURE))
    assert config.models.rag.chunk_tokens == 650
    assert config.models.rag.overlap_tokens == 80
    doc = _make_doc(MULTI_SECTION_MD + "\n" + _paragraphs_text(paragraphs=30))

    chunks = chunk_with_config(doc, config)

    assert chunks == chunk_document(doc, chunk_tokens=650, overlap_tokens=80)
    assert all(estimate_tokens(c.content) <= 650 for c in chunks)


def test_chunk_with_config_follows_modified_rag_settings_when_config_changes(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """RF-09: si cambia la configuración rag, cambia la fragmentación."""
    base: ModelsConfig = load_models_config(MODELS_FIXTURE)
    models = base.model_copy(
        update={"rag": base.rag.model_copy(update={"chunk_tokens": 100, "overlap_tokens": 20})}
    )
    config = AppConfig(Settings(_env_file=None), models)
    doc = _make_doc(MULTI_SECTION_MD + "\n" + _paragraphs_text(paragraphs=30))

    chunks = chunk_with_config(doc, config)

    assert chunks == chunk_document(doc, chunk_tokens=100, overlap_tokens=20)
    assert all(estimate_tokens(c.content) <= 100 for c in chunks)
    assert len(chunks) > len(chunk_document(doc, chunk_tokens=650, overlap_tokens=80))


# --------------------------------------------------------------------------- corpus piloto


def _doc_02() -> IngestedDocument:
    header, body = _strip_front_matter(DOC_02.read_text(encoding="utf-8"))
    return _make_doc(
        body,
        doc_id=str(header["id"]),
        title=str(header["title"]),
        category="politicas",
        source_path=DOC_02.relative_to(ROOT).as_posix(),
        metadata={"version": str(header["version"])},
    )


def test_chunk_document_splits_corpus_reglamento_by_sections_when_default_sizes() -> None:
    """RF-09/RF-10: DOC-02 del corpus se fragmenta por secciones con 650/80 tokens."""
    doc = _doc_02()

    chunks = chunk_document(doc, chunk_tokens=650, overlap_tokens=80)

    assert chunks
    assert all(c.section is not None for c in chunks)
    assert all(c.section.startswith("Reglamento de reservas") for c in chunks if c.section)
    rules = [c for c in chunks if c.section == "Reglamento de reservas > Reglas de negocio"]
    assert rules
    assert any("RN-RES-02" in c.content for c in rules)
    assert all(estimate_tokens(c.content) <= 650 for c in chunks)
    assert all(c.metadata["category"] == "politicas" for c in chunks)
    assert all(c.metadata["source"].endswith("DOC-02-reglamento-reservas.md") for c in chunks)
    assert all(c.document_id == "DOC-02" for c in chunks)


def test_chunk_document_generates_more_chunks_for_corpus_when_sizes_are_smaller() -> None:
    """RF-09: con 100/20 tokens DOC-02 genera más chunks y ninguno supera 100 tokens."""
    doc = _doc_02()

    default_chunks = chunk_document(doc, chunk_tokens=650, overlap_tokens=80)
    small_chunks = chunk_document(doc, chunk_tokens=100, overlap_tokens=20)

    assert len(small_chunks) > len(default_chunks)
    assert all(estimate_tokens(c.content) <= 100 for c in small_chunks)
    assert [c.ordinal for c in small_chunks] == list(range(len(small_chunks)))
    covered = {w for c in small_chunks for w in _words(c.content)}
    assert set(_words(doc.text)) <= covered
