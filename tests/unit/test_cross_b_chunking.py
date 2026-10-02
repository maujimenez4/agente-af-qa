"""Prueba cruzada T-34 (RNF-19): el área A prueba la fragmentación del área B (RF-09).

Cubre huecos de `core/rag/chunking.py` que no prueban `test_rag_chunking.py`: solapamiento
con párrafos medianos, vallas de código mezcladas o sin cerrar, títulos con `#`, encabezados
vacíos o setext, BOM, palabras más largas que el solapamiento y memorias vacías o enormes.
Los defectos confirmados van como `xfail(strict=True)`; el resto fija el comportamiento actual.
Datos 100 % ficticios.
"""

import hashlib
from itertools import pairwise

import pytest

from core.rag.chunking import chunk_document, estimate_tokens, split_recursive, split_sections
from core.rag.documents import MEMORY_CATEGORY, IngestedDocument


def _doc(text: str, *, category: str = "politicas", doc_id: str = "DOC-FIC-01") -> IngestedDocument:
    return IngestedDocument(
        id=doc_id,
        title="Documento ficticio",
        category=category,
        classified_by="metadata",
        source_path="corpus/ficticio/DOC-FIC-01.md",
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )


def _paragraphs(count: int, words: int = 20) -> list[str]:
    """Párrafos de palabras únicas y ficticias (p0w00…); 20 palabras ≈ 30 tokens."""
    return [" ".join(f"p{p}w{i:02d}" for i in range(words)) for p in range(count)]


# --------------------------------------------------------------------------- solapamiento


def test_split_recursive_overlaps_fragments_when_paragraphs_exceed_overlap() -> None:
    """RF-09: con overlap_tokens > 0, fragmentos consecutivos comparten texto.

    10 párrafos de ~30 tokens (más que el solapamiento de 20 y menos que el límite de 100).
    """
    text = "\n\n".join(_paragraphs(10))
    assert all(20 < estimate_tokens(p) < 100 for p in _paragraphs(10))

    fragments = split_recursive(text, chunk_tokens=100, overlap_tokens=20)

    assert len(fragments) >= 2
    for previous, following in pairwise(fragments):
        assert set(previous.split()) & set(following.split())


def test_split_recursive_respects_limit_when_paragraphs_exceed_overlap() -> None:
    """RF-09 (límite): con párrafos medianos ningún fragmento supera chunk_tokens."""
    text = "\n\n".join(_paragraphs(10))

    fragments = split_recursive(text, chunk_tokens=100, overlap_tokens=20)

    assert all(estimate_tokens(f) <= 100 for f in fragments)
    assert {w for f in fragments for w in f.split()} == set(text.split())


def test_split_recursive_keeps_limit_and_coverage_when_word_longer_than_overlap() -> None:
    """RF-09 (límite): una palabra más larga que el solapamiento se corta sin perder texto."""
    long_word = "x" * 200  # 50 tokens > overlap de 10 y > límite de 30
    text = "a " * 50 + long_word + " b" * 50

    fragments = split_recursive(text, chunk_tokens=30, overlap_tokens=10)

    assert len(fragments) >= 3
    assert all(estimate_tokens(f) <= 30 for f in fragments)
    assert all(f in text for f in fragments)
    assert sum(f.count("x") for f in fragments) >= len(long_word)


def test_split_recursive_overlaps_hard_cut_pieces_when_word_longer_than_overlap() -> None:
    """RF-09: al partir una palabra larga se solapa su final con el fragmento siguiente."""
    text = "a " * 50 + "x" * 200 + " b" * 50

    fragments = split_recursive(text, chunk_tokens=30, overlap_tokens=10)

    for previous, following in pairwise(fragments):
        assert _shared_edge(previous, following), "sin solapamiento entre fragmentos"


def _shared_edge(previous: str, following: str) -> str:
    """Texto más largo que es sufijo de `previous` y prefijo de `following`."""
    left, right = previous.rstrip(), following.lstrip()
    for size in range(min(len(left), len(right)), 0, -1):
        if right.startswith(left[-size:]):
            return left[-size:]
    return ""


# --------------------------------------------------------------------------- vallas de código


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-212): un bloque ~~~ se cierra con ``` porque _FENCE alterna sin mirar el "
        "tipo de valla (core/rag/chunking.py:20 y 48-49)"
    ),
)
def test_split_sections_ignores_hash_lines_when_tilde_fence_contains_backticks() -> None:
    """RF-09: dentro de ~~~ … ~~~ una línea ``` no cierra el bloque ni hay encabezados."""
    md = "# A\n\n~~~\ncódigo ficticio\n```\n# comentario ficticio\n~~~\n\n## B\n\ntexto"

    sections = split_sections(md)

    assert [s.path for s in sections] == [("A",), ("A", "B")]
    assert "# comentario ficticio" in sections[0].text


def test_split_sections_keeps_following_headings_in_code_when_fence_never_closes() -> None:
    """RF-09 (comportamiento fijado): una valla sin cerrar llega hasta el final (CommonMark).

    Todos los encabezados posteriores quedan dentro del código de la sección «A».
    """
    md = "# A\n\n```\ncódigo ficticio\n\n## B\n\ntexto b\n\n## C\n\ntexto c"

    sections = split_sections(md)

    assert [s.path for s in sections] == [("A",)]
    assert "## B" in sections[0].text and "## C" in sections[0].text


def test_split_sections_detects_heading_when_tilde_fence_is_closed_by_tilde() -> None:
    """RF-09: un bloque ~~~ bien cerrado oculta sus '#' y no afecta a lo que sigue."""
    md = "# A\n\n~~~\n# comentario ficticio\n~~~\n\n## B\n\ntexto"

    assert [s.path for s in split_sections(md)] == [("A",), ("A", "B")]


# --------------------------------------------------------------------------- títulos


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-212): '# C#' da el título 'C'; _HEADING quita '#' finales aunque no haya "
        "espacio antes (core/rag/chunking.py:19)"
    ),
)
def test_split_sections_keeps_trailing_hash_when_it_is_part_of_the_title() -> None:
    """RF-09: en CommonMark el cierre '#' necesita un espacio delante; '# C#' es «C#»."""
    assert [s.path for s in split_sections("# C#\n\ntexto ficticio")] == [("C#",)]


def test_split_sections_removes_closing_hashes_when_preceded_by_space() -> None:
    """RF-09: '## Título ##' (cierre ATX con espacio) da «Título»."""
    md = "# Raíz\n\n## Título ficticio ##\n\ntexto"

    assert split_sections(md)[-1].path == ("Raíz", "Título ficticio")


def test_split_sections_keeps_inner_hash_when_title_contains_hash() -> None:
    """RF-09: un '#' en mitad del título se conserva."""
    assert split_sections("# Guía de C# ficticia\n\ntexto")[0].path == ("Guía de C# ficticia",)


def test_chunk_document_builds_trailing_separator_when_heading_is_empty() -> None:
    """RF-09 (comportamiento fijado): '## ' vacío añade un título vacío y la ruta «A > »."""
    chunks = chunk_document(_doc("# A\n\n## \n\ntexto ficticio"), 100, 10)

    assert [c.section for c in chunks] == ["A", "A > "]


def test_split_sections_ignores_bare_hashes_when_heading_has_no_space() -> None:
    """RF-09 (comportamiento fijado): '##' sin espacio ni título no se trata como encabezado."""
    sections = split_sections("# A\n\n##\n\ntexto ficticio")

    assert [s.path for s in sections] == [("A",)]
    assert "##" in sections[0].text


def test_split_sections_ignores_setext_headings() -> None:
    """RF-09 (comportamiento fijado): solo se reconocen encabezados ATX, no los setext."""
    md = "Título ficticio\n===============\n\ntexto\n\nSubtítulo\n---------\n\nmás texto"

    sections = split_sections(md)

    assert [s.path for s in sections] == [()]
    assert "===" in sections[0].text


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-212): "
        "un BOM inicial impide reconocer el primer encabezado; _HEADING exige "
        "'#' en la columna 0 (core/rag/chunking.py:19)"
    ),
)
def test_split_sections_recognizes_first_heading_when_text_starts_with_bom() -> None:
    """RF-09: '\\ufeff# Título' sigue siendo el encabezado «Título»."""
    assert split_sections("﻿# Título ficticio\n\ntexto")[0].path == ("Título ficticio",)


# --------------------------------------------------------------------------- memorias


def test_chunk_document_returns_single_empty_chunk_when_memory_is_empty() -> None:
    """SPEC-00 §6 (comportamiento fijado): una memoria vacía da 1 fragmento sin contenido."""
    chunks = chunk_document(_doc("", category=MEMORY_CATEGORY), 100, 10)

    assert len(chunks) == 1
    assert chunks[0].content == ""
    assert chunks[0].id == "DOC-FIC-01#0"


def test_chunk_document_returns_single_chunk_over_limit_when_memory_is_huge() -> None:
    """SPEC-00 §6 (comportamiento fijado): una memoria enorme no se fragmenta."""
    text = "# Memoria ficticia\n\n" + "\n\n".join(_paragraphs(400))

    chunks = chunk_document(_doc(text, category=MEMORY_CATEGORY), 100, 10)

    assert len(chunks) == 1
    assert chunks[0].content == text
    assert estimate_tokens(chunks[0].content) > 100
    assert chunks[0].section is None


def test_overlap_does_not_glue_words_across_paragraphs() -> None:
    """PA-211: el solapamiento conserva el salto de párrafo; ninguna palabra sale pegada."""
    paragraphs = _paragraphs(10)
    valid = {word for paragraph in paragraphs for word in paragraph.split()}
    fragments = split_recursive("\n\n".join(paragraphs), 100, 20)
    assert len(fragments) >= 2
    assert all(set(fragment.split()) <= valid for fragment in fragments)


def test_table_rows_still_do_not_overlap_partially() -> None:
    """PA-211 (límite): una fila de tabla nunca se parte para solapar."""
    rows = [f"| f{n:02d} | " + " ".join(f"c{n}x{i}" for i in range(18)) + " |" for n in range(8)]
    fragments = split_recursive("\n".join(rows), 100, 20)
    for fragment in fragments:
        for line in fragment.splitlines():
            assert line.startswith("|") and line.endswith("|")
