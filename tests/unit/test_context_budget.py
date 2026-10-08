"""Presupuesto de tokens del contexto (T-18: RF-11, RF-14, RF-51; PA-07).

Cubre `core/context/budget.py`: estimación, recorte de incidencias y selección por prioridad
de Jira + RAG sin superar el presupuesto. Funciones puras; datos 100 % ficticios.
"""

import pytest

from adapters.base import Chunk, IssueDetail, IssueLink, IssueSummary, RetrievedChunk
from core.context.budget import (
    CHARS_PER_TOKEN,
    CHUNK_OVERHEAD_TOKENS,
    ISSUE_OVERHEAD_TOKENS,
    TRUNCATION_MARK,
    BudgetReport,
    apply_budget,
    chunk_tokens,
    estimate_tokens,
    issue_tokens,
    truncate_issue,
)
from schemas.common import SourceRef

# --- utilidades --------------------------------------------------------------------------


def make_issue(
    key: str,
    description_chars: int = 40,
    comments: list[str] | None = None,
    summary: str = "Resumen ficticio de prueba",
) -> IssueDetail:
    return IssueDetail(
        key=key,
        summary=summary,
        issue_type="Story",
        status="Por hacer",
        description_text="d" * description_chars,
        comments=comments or [],
    )


def make_chunk(chunk_id: str, content_chars: int, category: str = "politicas") -> RetrievedChunk:
    chunk = Chunk(
        id=chunk_id,
        document_id=f"doc-{chunk_id}",
        ordinal=0,
        content="c" * content_chars,
        metadata={"category": category},
    )
    return RetrievedChunk(chunk=chunk, score=0.5, source=SourceRef(kind="rag", ref=chunk_id))


def total_tokens(issues: list[IssueDetail], chunks: list[RetrievedChunk]) -> int:
    return sum(issue_tokens(i) for i in issues) + sum(chunk_tokens(c) for c in chunks)


# --- estimate_tokens / issue_tokens --------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", 0), ("a", 1), ("abc", 1), ("abcd", 2), ("x" * 300, 100), ("x" * 301, 101)],
)
def test_estimate_tokens_rounds_up_three_chars_per_token(text: str, expected: int) -> None:
    """PA-07 · PA-114: estimación ≈ 3 caracteres por token (qwen3 mide ~3,2 en español),
    redondeando hacia arriba."""
    assert CHARS_PER_TOKEN == 3
    assert estimate_tokens(text) == expected


def test_issue_tokens_counts_key_summary_description_and_comments() -> None:
    """PA-07: el coste de una incidencia incluye clave, resumen, descripción y comentarios."""
    without = make_issue("DEMO-1", 100)
    with_comments = make_issue("DEMO-1", 100, comments=["comentario ficticio " * 10])
    assert issue_tokens(with_comments) > issue_tokens(without)
    expected = estimate_tokens(" ".join(["DEMO-1", without.summary, without.description_text]))
    assert issue_tokens(without) == expected + ISSUE_OVERHEAD_TOKENS


def test_issue_tokens_counts_subtasks_links_and_labels() -> None:
    """Revisión de seguridad de T-18: también cuenta lo que se serializa hacia el LLM."""
    base = make_issue("DEMO-1", 100)
    rich = base.model_copy(
        update={
            "subtasks": [
                IssueSummary(
                    key="DEMO-9",
                    summary="Caso ficticio " * 20,
                    issue_type="Subtarea",
                    status="Por hacer",
                )
            ],
            "links": [IssueLink(link_type="relates to", key="DEMO-2")],
            "labels": ["etiqueta-ficticia"],
        }
    )
    assert issue_tokens(rich) > issue_tokens(base)


def test_chunk_tokens_adds_overhead() -> None:
    chunk = make_chunk("c1", 400)
    assert chunk_tokens(chunk) == estimate_tokens(chunk.chunk.content) + CHUNK_OVERHEAD_TOKENS


# --- truncate_issue ------------------------------------------------------------------------


def test_truncate_issue_adds_mark_and_drops_comments_when_too_long() -> None:
    """PA-07: el recorte añade «[…]» al final de la descripción y quita los comentarios."""
    issue = make_issue("DEMO-3", 4000, comments=["uno ficticio", "dos ficticio"])
    trimmed = truncate_issue(issue, 100)
    assert trimmed.description_text.endswith(TRUNCATION_MARK)
    assert "[…]" in TRUNCATION_MARK
    assert trimmed.comments == []
    assert len(trimmed.description_text) < len(issue.description_text)
    assert trimmed.key == issue.key
    assert trimmed.summary == issue.summary


def test_truncate_issue_keeps_description_without_mark_when_it_fits() -> None:
    """PA-07: si la descripción cabe, no se marca; los comentarios sí se quitan."""
    issue = make_issue("DEMO-3", 20, comments=["comentario ficticio " * 50])
    trimmed = truncate_issue(issue, 100)
    assert trimmed.description_text == issue.description_text
    assert TRUNCATION_MARK not in trimmed.description_text
    assert trimmed.comments == []


def test_truncate_issue_does_not_mutate_original() -> None:
    """PA-07: el recorte devuelve una copia; la incidencia original no cambia."""
    issue = make_issue("DEMO-3", 4000, comments=["comentario ficticio"])
    truncate_issue(issue, 50)
    assert len(issue.description_text) == 4000
    assert issue.comments == ["comentario ficticio"]


@pytest.mark.parametrize("max_tokens", [60, 100, 257])
def test_truncate_issue_fits_within_max_tokens_for_typical_summary(max_tokens: int) -> None:
    """PA-07 (límite): con el resumen del dataset, la incidencia recortada cabe en el máximo."""
    trimmed = truncate_issue(make_issue("DEMO-3", 5000), max_tokens)
    assert issue_tokens(trimmed) <= max_tokens


@pytest.mark.parametrize("max_tokens", [60, 100])
def test_truncate_issue_fits_within_max_tokens_when_header_is_multiple_of_four(
    max_tokens: int,
) -> None:
    """PA-07 (límite): «DEMO-3 R» (8 caracteres) no debe hacer que el recorte se pase."""
    trimmed = truncate_issue(make_issue("DEMO-3", 5000, summary="R"), max_tokens)
    assert issue_tokens(trimmed) <= max_tokens


# --- apply_budget: garantías generales -------------------------------------------------------


@pytest.mark.parametrize("budget", [120, 300, 800, 2000, 6000])
def test_apply_budget_never_exceeds_budget_when_origin_fits(budget: int) -> None:
    """PA-07 · PA-442: el total de Jira + RAG no supera el presupuesto salvo por el origen, que
    entra entero aunque no quepa; entonces no entra ninguna fuente opcional."""
    issues = [make_issue(f"DEMO-{n}", 900) for n in range(1, 8)]
    chunks = [make_chunk(f"c{n}", 700) for n in range(10)]
    origin_cost = issue_tokens(issues[0])  # ≈ 309 tokens
    sel_issues, sel_chunks, report = apply_budget(issues, chunks, budget)
    assert sel_issues[0] == issues[0]  # entero
    assert report.used <= max(budget, origin_cost)
    if origin_cost > budget:
        assert (sel_issues, sel_chunks, report.used) == ([issues[0]], [], origin_cost)
    assert total_tokens(sel_issues, sel_chunks) == report.used
    assert report.budget == budget


def test_apply_budget_origin_always_enters_first() -> None:
    """PA-07: la primera incidencia (el origen) siempre entra y en primera posición."""
    issues = [make_issue("DEMO-3", 40), make_issue("DEMO-1", 40)]
    sel_issues, _, _ = apply_budget(issues, [], 1000)
    assert sel_issues[0].key == "DEMO-3"


def test_apply_budget_keeps_origin_whole_when_it_exceeds_budget() -> None:
    """PA-442 (antes PA-07 lo recortaba): si el origen no cabe, entra entero (sin marca y con
    sus comentarios), su coste cuenta y ya no entra ninguna fuente opcional."""
    origin = make_issue("DEMO-3", 8000, comments=["comentario ficticio"])
    sel_issues, sel_chunks, report = apply_budget([origin], [make_chunk("c1", 40)], 400)
    assert sel_issues == [origin]
    assert not sel_issues[0].description_text.endswith(TRUNCATION_MARK)
    assert sel_issues[0].comments == ["comentario ficticio"]
    assert sel_chunks == []
    assert report.truncated_issues == 0
    assert report.dropped_chunks == 1
    assert report.used == issue_tokens(origin) > 400


def test_apply_budget_origin_fits_whole_even_if_larger_than_jira_share() -> None:
    """PA-07: el origen puede usar más de la cuota de Jira si cabe en el presupuesto."""
    origin = make_issue("DEMO-3", 2400)  # ≈ 608 tokens > 500 (cuota de Jira)
    sel_issues, _, report = apply_budget([origin], [], 1000)
    assert sel_issues[0].description_text == origin.description_text
    assert report.truncated_issues == 0


def test_apply_budget_respects_priority_order_of_issues() -> None:
    """PA-07: con sitio limitado, entran las primeras por prioridad y se descartan las últimas."""
    issues = [make_issue(f"DEMO-{n}", 360) for n in range(1, 7)]  # ≈ 98 tokens cada una
    sel_issues, _, report = apply_budget(issues, [], 600)  # cuota de Jira = 300
    keys = [i.key for i in sel_issues]
    assert keys == [f"DEMO-{n}" for n in range(1, len(keys) + 1)]
    assert len(keys) < len(issues)
    assert report.dropped_issues + len(keys) == len(issues)


def test_apply_budget_counts_dropped_issues_in_report() -> None:
    """PA-07: las incidencias que no caben (sitio < 60 tokens) se descartan y se cuentan."""
    issues = [make_issue("DEMO-1", 360), make_issue("DEMO-2", 2000), make_issue("DEMO-3", 2000)]
    sel_issues, _, report = apply_budget(issues, [], 220)  # cuota 110: queda < 60 tras el origen
    assert [i.key for i in sel_issues] == ["DEMO-1"]
    assert report.dropped_issues == 2
    assert report.truncated_issues == 0


def test_apply_budget_truncates_secondary_issue_when_room_is_useful() -> None:
    """PA-07: una incidencia secundaria se recorta si quedan ≥ 60 tokens en la cuota de Jira."""
    issues = [make_issue("DEMO-1", 40), make_issue("DEMO-2", 4000, comments=["ficticio"])]
    sel_issues, _, report = apply_budget(issues, [], 1000)  # cuota 500
    assert [i.key for i in sel_issues] == ["DEMO-1", "DEMO-2"]
    assert sel_issues[1].description_text.endswith(TRUNCATION_MARK)
    assert sel_issues[1].comments == []
    assert report.truncated_issues == 1
    assert sum(issue_tokens(i) for i in sel_issues) <= 500


def test_apply_budget_drops_chunks_that_do_not_fit_and_counts_them() -> None:
    """PA-07: los fragmentos que no caben se descartan (sin recortar) y se cuentan."""
    chunks = [make_chunk("c1", 400), make_chunk("c2", 400), make_chunk("c3", 400)]
    issue = make_issue("DEMO-1", 20)
    budget = issue_tokens(issue) + 2 * chunk_tokens(chunks[0])  # caben justo dos fragmentos
    _, sel_chunks, report = apply_budget([issue], chunks, budget)
    assert [c.chunk.id for c in sel_chunks] == ["c1", "c2"]
    assert report.dropped_chunks == 1
    assert all(len(c.chunk.content) == 400 for c in sel_chunks)


def test_apply_budget_keeps_later_small_chunk_after_dropping_big_one() -> None:
    """PA-07: un fragmento grande que no cabe no impide que entre uno pequeño posterior."""
    chunks = [make_chunk("grande", 4000), make_chunk("pequeño", 40)]
    _, sel_chunks, report = apply_budget([], chunks, 100)
    assert [c.chunk.id for c in sel_chunks] == ["pequeño"]
    assert report.dropped_chunks == 1


def test_apply_budget_keeps_chunk_priority_order_memories_first() -> None:
    """RF-51: el orden de entrada de los fragmentos (memorias primero) se conserva."""
    chunks = [make_chunk("memo", 40, "memoria"), make_chunk("norma", 40)]
    _, sel_chunks, _ = apply_budget([], chunks, 1000)
    assert [c.chunk.id for c in sel_chunks] == ["memo", "norma"]


# --- apply_budget: reparto jira_share ----------------------------------------------------------


def test_apply_budget_unused_jira_share_goes_to_rag() -> None:
    """PA-07: lo que Jira no usa de su cuota pasa al RAG."""
    chunks = [make_chunk(f"c{n}", 400) for n in range(9)]  # 100 tokens cada uno
    sel_issues, sel_chunks, report = apply_budget([make_issue("DEMO-1", 20)], chunks, 1000)
    jira_used = sum(issue_tokens(i) for i in sel_issues)
    rag_used = sum(estimate_tokens(c.chunk.content) for c in sel_chunks)
    assert jira_used < 100
    assert rag_used > 500  # más de la mitad del presupuesto
    assert report.used <= 1000


def test_apply_budget_jira_share_caps_secondary_issues() -> None:
    """PA-07: las incidencias secundarias no pasan de `jira_share` del presupuesto."""
    issues = [make_issue(f"DEMO-{n}", 360) for n in range(1, 20)]
    sel_issues, _, _ = apply_budget(issues, [], 2000, jira_share=0.25)
    assert sum(issue_tokens(i) for i in sel_issues) <= 500


def test_apply_budget_jira_share_zero_leaves_everything_to_rag_except_origin() -> None:
    """PA-07 (límite): con cuota 0, solo entra el origen de Jira; el resto va al RAG."""
    issues = [make_issue("DEMO-1", 40), make_issue("DEMO-2", 40)]
    chunks = [make_chunk("c1", 400)]
    sel_issues, sel_chunks, report = apply_budget(issues, chunks, 500, jira_share=0.0)
    assert [i.key for i in sel_issues] == ["DEMO-1"]
    assert report.dropped_issues == 1
    assert [c.chunk.id for c in sel_chunks] == ["c1"]


def test_apply_budget_full_jira_share_never_exceeds_budget() -> None:
    """PA-07 (límite) · PA-442: con `jira_share=1.0`, una incidencia opcional enorme se recorta
    y el total tampoco supera el presupuesto (el origen pequeño cabe)."""
    origin = make_issue("DEMO-3", 20, summary="R")
    other = make_issue("DEMO-4", 8000, summary="R")  # "DEMO-4 R" = 8 caracteres
    sel_issues, _, report = apply_budget([origin, other], [], 100, jira_share=1.0)
    assert [i.key for i in sel_issues] == ["DEMO-3", "DEMO-4"]
    assert sel_issues[1].description_text.endswith(TRUNCATION_MARK)
    assert report.truncated_issues == 1
    assert report.used <= 100


# --- apply_budget: casos extremos -------------------------------------------------------------


def test_apply_budget_empty_inputs_return_empty_report() -> None:
    """PA-07 (límite): sin incidencias ni fragmentos, el informe está a cero."""
    issues, chunks, report = apply_budget([], [], 6000)
    assert issues == []
    assert chunks == []
    assert report == BudgetReport(budget=6000, used=0)


def test_apply_budget_extremely_small_budget_keeps_only_whole_origin() -> None:
    """PA-07 (límite) · PA-442: con presupuesto mínimo, solo queda el origen, entero; nada más."""
    issues = [make_issue("DEMO-3", 4000, comments=["ficticio"]), make_issue("DEMO-1", 40)]
    chunks = [make_chunk("c1", 40)]
    sel_issues, sel_chunks, report = apply_budget(issues, chunks, 10)
    assert sel_issues == [issues[0]]
    assert sel_issues[0].comments == ["ficticio"]
    assert not sel_issues[0].description_text.endswith(TRUNCATION_MARK)
    assert sel_chunks == []
    assert report.dropped_issues == 1
    assert report.dropped_chunks == 1
    assert report.truncated_issues == 0


def test_apply_budget_budget_below_origin_header_still_includes_origin() -> None:
    """PA-07 (límite) · PA-442: aunque ni la clave y el resumen quepan, el origen entra entero."""
    origin = make_issue("DEMO-3", 4000)
    sel_issues, sel_chunks, report = apply_budget([origin], [], 1)
    assert sel_issues == [origin]
    assert sel_chunks == []
    assert report.truncated_issues == 0
    assert report.used == issue_tokens(origin)


def test_apply_budget_origin_cost_leaves_less_room_for_optional_sources() -> None:
    """PA-442: el coste del origen cuenta: una incidencia que cabría sola en la cuota de Jira
    se recorta tras un origen grande, y los fragmentos solo entran si caben en lo que queda."""
    origin = make_issue("DEMO-3", 900)  # ≈ 309 tokens
    other = make_issue("DEMO-4", 900)
    chunks = [make_chunk("c1", 300), make_chunk("c2", 3000)]  # ≈ 100 y ≈ 1000 tokens
    sel_issues, sel_chunks, report = apply_budget([origin, other], chunks, 1000)  # cuota 500
    assert sel_issues[0] == origin
    assert issue_tokens(other) <= 500  # sola habría cabido entera
    assert sel_issues[1].description_text.endswith(TRUNCATION_MARK)
    assert issue_tokens(origin) + issue_tokens(sel_issues[1]) <= 500
    assert [c.chunk.id for c in sel_chunks] == ["c1"]
    assert report.dropped_chunks == 1
    assert report.used <= 1000


def test_apply_budget_without_origin_truncates_the_first_issue_too() -> None:
    """PA-442 (límite): con una necesidad (`has_origin=False`) no hay origen: la primera
    incidencia es opcional y se recorta como las demás."""
    first = make_issue("DEMO-3", 8000)
    sel_issues, _, report = apply_budget([first], [], 400, has_origin=False)
    assert [i.key for i in sel_issues] == ["DEMO-3"]
    assert sel_issues[0].description_text.endswith(TRUNCATION_MARK)
    assert report.truncated_issues == 1
    assert report.used <= 200
