"""Prueba cruzada T-35 (RNF-19): el área B prueba `core/context/` del área A (T-14, T-18, T-51,
T-53, PA-69).

Cubre RF-14 y §6.1 (JQL de texto, de palabras clave y de vínculos, sin inyección), RF-11 y PA-07
(presupuesto de 6000 tokens con margen y reserva del texto de la necesidad), RF-21 (fuentes
excluidas antes del presupuesto y del par norma ↔ acta, hueco de `top_k` relleno; filas
«Fuentes excluidas» y «Arranque guiado» del anexo §11 de SPEC-00) y T-53 (`similar_stories`,
`NOT_STORIES`, `RELATED_PAIRS`).

Se centra en los bordes que `test_jira_jql.py`, `test_context_*.py`, `test_review_contract.py`
y `test_cross_b_guided_start.py` no fijan: operadores de Lucene y `ORDER BY` en el texto,
espacios Unicode, recorte a 200 con separadores, claves de proyecto inyectadas, documentos con
varios fragmentos excluidos, fuentes enormes, reserva mayor que el presupuesto, excluir todo,
excluir el acta, subtareas en el contexto de una necesidad y tipos de incidencia en otro idioma.

Solo fakes de `tests/fakes/` (con espías finos definidos aquí); sin red ni LLM. Datos 100 %
ficticios. Los defectos confirmados van como `xfail(strict=True)` con su PA; el resto fija el
comportamiento.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import pytest

from adapters.base import Chunk, IssueDetail, IssueLink, IssueSummary, RetrievedChunk
from core.context.budget import TRUNCATION_MARK, estimate_tokens, issue_tokens
from core.context.jql import (
    MAX_KEYWORD_CHARS,
    MAX_TEXT_CHARS,
    any_keyword_jql,
    keywords,
    linked_issues_jql,
    text_search_jql,
)
from core.context.service import (
    MAX_LINKED,
    MAX_NEED_CANDIDATES,
    NOT_STORIES,
    RELATED_PAIRS,
    ContextService,
)
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.vector_store import FakeVectorStore

STORY_ORIGIN = {"kind": "story", "key": "DEMO-3"}
LUCENE_SPECIAL = set('+-&|!(){}[]^~*?:\\/"')
LUCENE_OPERATORS = {"AND", "OR", "NOT"}
INVALID_PROJECTS = [
    'DEMO" OR project = "OTRO',
    "DEMO) OR (project = OTRO",
    "DEMO ORDER BY key",
    "DEMO\x00",
    "DEMO\r\n",
    "ＤＥＭＯ",  # letras de ancho completo
    "DEMÓ",
    "-DEMO",
]


# --- espías sobre los fakes ------------------------------------------------------------------


@dataclass
class SpyTracker(FakeIssueTracker):
    """FakeIssueTracker que registra `get_issue` y `search` (y puede fijar sus resultados)."""

    get_calls: list[str] = field(default_factory=list)
    searches: list[tuple[str, int]] = field(default_factory=list)
    search_results: list[IssueSummary] | None = None

    def get_issue(self, key: str) -> IssueDetail:
        self.get_calls.append(key)
        return super().get_issue(key)

    def search(self, jql: str, limit: int = 50) -> list[IssueSummary]:
        self.searches.append((jql, limit))
        if self.search_results is not None:
            return list(self.search_results)
        return super().search(jql, limit)


@dataclass
class SpyStore(FakeVectorStore):
    calls: list[dict[str, Any]] = field(default_factory=list)

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        self.calls.append({"k": k, "filters": filters})
        return super().search(query_vector, query_text, k, filters, memory_boost)


# --- utilidades --------------------------------------------------------------------------------


def jql_literal(jql: str) -> str:
    """Contenido del literal de `text ~ "…"` tal como lo lee el analizador de JQL."""
    start = jql.index('text ~ "') + len('text ~ "')
    chars: list[str] = []
    index = start
    while index < len(jql):
        char = jql[index]
        if char == "\\":
            chars.append(jql[index + 1])
            index += 2
            continue
        if char == '"':
            return "".join(chars)
        chars.append(char)
        index += 1
    pytest.fail("El literal JQL no está cerrado.")


def jql_outside_literal(jql: str) -> str:
    """La JQL sin el literal de texto: lo que el analizador interpreta como sintaxis."""
    start = jql.index('text ~ "') + len("text ~ ")
    literal_len = len(_raw_literal(jql, start))
    return jql[:start] + jql[start + literal_len :]


def _raw_literal(jql: str, start: int) -> str:
    index = start + 1
    while jql[index] != '"':
        index += 2 if jql[index] == "\\" else 1
    return jql[start : index + 1]


def lucene_unescape(value: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\":
            index += 1
        chars.append(value[index])
        index += 1
    return "".join(chars)


def unescaped_specials(lucene: str) -> list[str]:
    """Caracteres especiales de Lucene que quedan sin escapar."""
    found: list[str] = []
    index = 0
    while index < len(lucene):
        if lucene[index] == "\\":
            index += 2
            continue
        if lucene[index] in LUCENE_SPECIAL:
            found.append(lucene[index])
        index += 1
    return found


def add_chunk(
    store: FakeVectorStore,
    embeddings: FakeEmbeddingProvider,
    chunk_id: str,
    document_id: str,
    category: str,
    content: str,
    *,
    doc_id: str | None = None,
    related: str = "",
) -> None:
    metadata = {"category": category, "doc_id": doc_id or document_id}
    if related:
        metadata["related"] = related
    (vector,) = embeddings.embed([content])
    ordinal = int(chunk_id.rsplit("#", 1)[-1]) if "#" in chunk_id else 0
    store.upsert(
        [
            Chunk(
                id=chunk_id,
                document_id=document_id,
                ordinal=ordinal,
                content=content,
                embedding=vector,
                metadata=metadata,
            )
        ]
    )


def make_service(
    tracker: FakeIssueTracker | None = None,
    store: FakeVectorStore | None = None,
    embeddings: FakeEmbeddingProvider | None = None,
    *,
    top_k: int = 6,
    token_budget: int = 6000,
    project_key: str | None = None,
) -> ContextService:
    return ContextService(
        tracker if tracker is not None else SpyTracker(),
        embeddings or FakeEmbeddingProvider(),
        store if store is not None else SpyStore(),
        top_k=top_k,
        memory_boost=1.0,
        token_budget=token_budget,
        project_key=project_key,
    )


def story(key: str, title: str, issue_type: str = "Story", **extra: Any) -> IssueDetail:
    return IssueDetail(key=key, summary=title, issue_type=issue_type, status="Por hacer", **extra)


def summary(key: str, title: str, issue_type: str = "Story") -> IssueSummary:
    return IssueSummary(key=key, summary=title, issue_type=issue_type, status="Por hacer")


def refs(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.chunk.metadata.get("doc_id") or c.chunk.document_id for c in chunks]


def norm_minutes_corpus() -> tuple[FakeEmbeddingProvider, SpyStore]:
    """Norma (politicas) ↔ acta (documentacion) ficticias; el acta tiene una `ref` de fichero."""
    embeddings, store = FakeEmbeddingProvider(), SpyStore()
    add_chunk(
        store,
        embeddings,
        "DOC-A#0",
        "DOC-A",
        "politicas",
        "Norma ficticia: las reservas quedan bloqueadas cuarenta y ocho horas en mostrador.",
        related="DOC-B",
    )
    add_chunk(
        store,
        embeddings,
        "acta-ficticia.pdf#0",
        "acta-ficticia.pdf",
        "documentacion",
        "Acta ficticia de la comisión: acuerdo sobre plazos y calendario anual.",
        doc_id="DOC-B",
        related="DOC-A",
    )
    return embeddings, store


# === JQL: text_search_jql (RF-14, §6.1, §11) ===================================================


@pytest.mark.parametrize(
    "text",
    [
        "renovar ORDER BY key",
        'x" ORDER BY created ASC --',
        "préstamo AND project = OTRO",
        'x\\" OR issuetype = Epic OR text ~ "y',
    ],
)
def test_text_search_jql_keeps_order_by_and_operators_inside_literal(text: str) -> None:
    """RF-14 (seguridad): `ORDER BY`, `AND`, `OR` y comillas del texto no salen del literal;
    dentro, `AND`/`OR`/`NOT` quedan en minúsculas como palabras (PA-168)."""
    jql = text_search_jql("DEMO", text)

    outside = jql_outside_literal(jql)
    assert outside == 'project = "DEMO" AND text ~  ORDER BY updated DESC'
    expected = re.sub(r"\b(AND|OR|NOT)\b", lambda m: m.group(1).lower(), text)
    assert lucene_unescape(jql_literal(jql)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("renovar\r\npréstamo", "renovar préstamo"),
        ("renovar\u2028préstamo", "renovar préstamo"),  # separador de línea Unicode
        ("renovar\u00a0\u3000préstamo", "renovar préstamo"),  # NBSP y espacio ideográfico
        ("\x1crenovar\x1fpréstamo\x85", "renovar préstamo"),  # separadores de control
    ],
)
def test_text_search_jql_collapses_unicode_line_breaks_and_spaces(text: str, expected: str) -> None:
    """RF-14: saltos de línea y espacios Unicode se colapsan; la JQL queda en una línea."""
    jql = text_search_jql("DEMO", text)

    assert jql_literal(jql) == expected
    assert "\n" not in jql and "\r" not in jql and "\u2028" not in jql


@pytest.mark.parametrize(
    "text",
    ["renov*", "préstamo~2", "*", "~", "C:\\ruta\\ficticia", "a/b/c", 'fin\\"', "\\\\"],
)
def test_text_search_jql_escapes_wildcards_fuzzy_and_backslashes(text: str) -> None:
    """RF-14: `*`, `~`, `/` y `\\` llegan escapados (sin comodines ni búsqueda difusa)."""
    lucene = jql_literal(text_search_jql("DEMO", text))

    assert unescaped_specials(lucene) == []
    assert lucene_unescape(lucene) == text


def test_text_search_jql_truncates_unicode_by_code_points() -> None:
    """RF-14 (límite): el recorte a 200 cuenta caracteres, no bytes (ñ, emoji)."""
    text = "ñ" * 150 + "\U0001f4da" * 100

    lucene = jql_literal(text_search_jql("DEMO", text))

    assert len(lucene) == MAX_TEXT_CHARS
    assert lucene == "ñ" * 150 + "\U0001f4da" * 50


def test_text_search_jql_truncates_after_collapsing_whitespace() -> None:
    """RF-14 (límite): los espacios sobrantes no consumen el cupo de 200 caracteres."""
    text = "a" + " " * 500 + "b" * 300

    assert jql_literal(text_search_jql("DEMO", text)) == "a " + "b" * (MAX_TEXT_CHARS - 2)


@pytest.mark.parametrize("project", INVALID_PROJECTS)
def test_text_search_jql_rejects_injected_project_key(project: str) -> None:
    """RF-14, §11 (seguridad): una clave de proyecto inyectada o no ASCII → ValueError."""
    with pytest.raises(ValueError, match="Clave de proyecto no válida"):
        text_search_jql(project, "renovar")


@pytest.mark.parametrize("text", ["préstamo AND", "NOT", "OR renovar", "renovar AND NOT"])
def test_text_search_jql_neutralizes_lucene_boolean_operators(text: str) -> None:
    """RF-14: la búsqueda por texto libre trata «AND», «OR» y «NOT» como palabras, no como
    operadores (el buscador de la API, `api/app.py`, la usa con lo que escribe la persona)."""
    lucene = jql_literal(text_search_jql("DEMO", text))

    assert not set(lucene.split()) & LUCENE_OPERATORS


# === JQL: any_keyword_jql y keywords (RF-14, §6.1) =============================================


def test_any_keyword_jql_word_with_newline_and_specials_stays_single_literal() -> None:
    """RF-14 (seguridad): una palabra con salto de línea, `*` y comillas no rompe el literal."""
    jql = any_keyword_jql("DEMO", ['renov*\n"x" OR project = OTRO', "préstamo"])

    lucene = jql_literal(jql)
    assert jql_outside_literal(jql) == 'project = "DEMO" AND text ~ '
    assert unescaped_specials(lucene) == []
    assert lucene_unescape(lucene) == 'renov* "x" OR project = OTRO OR préstamo'


@pytest.mark.parametrize("project", INVALID_PROJECTS)
def test_any_keyword_jql_rejects_injected_project_key(project: str) -> None:
    """RF-14, §11 (seguridad): misma validación de la clave de proyecto que la búsqueda simple."""
    with pytest.raises(ValueError, match="Clave de proyecto no válida"):
        any_keyword_jql(project, ["renovar"])


def test_any_keyword_jql_with_keywords_never_emits_uppercase_operators() -> None:
    """RF-14: `keywords` pasa a minúsculas; «AND», «ORDER» o «NOTA» no llegan como operadores."""
    words = keywords("ORDER BY renovar AND NOTA OR préstamo NOT")

    lucene = jql_literal(any_keyword_jql("DEMO", words))

    assert words == ["order", "renovar", "nota", "préstamo"]
    assert lucene.split()[1::2] == ["OR"] * (len(words) - 1)  # solo el «OR» que añade el núcleo


def test_any_keyword_jql_long_terms_stay_within_max_text_chars() -> None:
    """RF-14 (límite): con 8 palabras de 40 caracteres el texto no pasa de 200 antes de escapar."""
    words = [chr(ord("a") + n) * MAX_KEYWORD_CHARS for n in range(8)]

    lucene = jql_literal(any_keyword_jql("DEMO", words))

    assert len(lucene) <= MAX_TEXT_CHARS


def test_any_keyword_jql_truncation_does_not_leave_dangling_or() -> None:
    """RF-14 (límite): seis palabras de 36 letras (alcanzable desde `keywords`) no acaban en
    «OR»; el recorte debe quitar términos completos."""
    words = keywords(" ".join(chr(ord("b") + n) * 36 for n in range(6)))
    assert len(words) == 6

    tokens = jql_literal(any_keyword_jql("DEMO", words)).split()

    assert tokens[-1] != "OR"
    assert all(t == "OR" or t in words for t in tokens)


def test_keywords_deduplicates_after_truncating_long_words() -> None:
    """RF-14 (límite): «sin repetir» también tras recortar a MAX_KEYWORD_CHARS."""
    prefix = "reglamentointerbibliotecarioficticio" + "x" * 4  # 40 caracteres
    words = keywords(f"{prefix}uno {prefix}dos renovar")

    assert len(words) == len(set(words))


def test_keywords_same_result_for_nfd_and_nfc_text() -> None:
    """RF-14: el mismo texto en NFD y en NFC da las mismas palabras clave."""
    text = "renovación del préstamo vencido"
    nfd = unicodedata.normalize("NFD", text)
    assert nfd != text

    assert keywords(nfd) == keywords(text)


# === JQL: linked_issues_jql ===================================================================


@pytest.mark.parametrize("key", ["DEMO_X-12", "AB-1", "DEMO-0007"])
def test_linked_issues_jql_accepts_ascii_issue_keys(key: str) -> None:
    """RF-14: claves válidas (con `_` y ceros) se aceptan tal cual."""
    assert linked_issues_jql(key) == f"issue in linkedIssues({key}) ORDER BY key"


@pytest.mark.parametrize("key", ["DEMO-3 OR key = OTRO-1", "DEMO-3)", "DEMO-3\x00", "DÉMO-3"])
def test_linked_issues_jql_rejects_injected_keys(key: str) -> None:
    """RF-14, §11 (seguridad): espacios, paréntesis, nulos o letras no ASCII → ValueError."""
    with pytest.raises(ValueError, match="Clave de incidencia no válida"):
        linked_issues_jql(key)


@pytest.mark.parametrize("key", ["DEMO-\u0661\u0662", "DEMO-\uff13"])
def test_linked_issues_jql_rejects_non_ascii_digits(key: str) -> None:
    """RF-14, §11: solo dígitos ASCII en el número de la clave."""
    with pytest.raises(ValueError):
        linked_issues_jql(key)


# === Presupuesto en gather (RF-11, PA-07) =====================================================


def test_gather_reserves_need_text_tokens_from_budget() -> None:
    """PA-07: el presupuesto informado es 6000 menos los tokens del texto de la necesidad."""
    context = make_service().gather({"kind": "need", "text": "r" * 400}, None)

    assert context.budget.budget == 6000 - estimate_tokens("r" * 400)  # /3 desde PA-114


def test_gather_with_zero_sources_reports_empty_context() -> None:
    """PA-07 (límite): sin Jira (sin proyecto) ni RAG (almacén vacío) todo queda a cero."""
    context = make_service().gather({"kind": "need", "text": "renovar préstamo"}, None)

    assert context.jira == [] and context.rag == []
    assert context.budget.used == 0
    assert (context.budget.dropped_chunks, context.budget.dropped_issues) == (0, 0)


def test_gather_need_text_larger_than_budget_leaves_no_rag() -> None:
    """PA-07 (límite): si la reserva supera el presupuesto, queda 0 y no entra ningún fragmento."""
    embeddings, store = FakeEmbeddingProvider(), SpyStore()
    add_chunk(store, embeddings, "GLO-1#0", "GLO-1", "glosarios", "reservas bloqueadas ficticio")
    text = "reservas bloqueadas " * 1500  # ≈ 10 000 tokens > 6000

    context = make_service(store=store, embeddings=embeddings).gather(
        {"kind": "need", "text": text}, None
    )

    assert context.budget.budget == 0
    assert context.rag == []
    assert context.budget.dropped_chunks == 1
    assert context.budget.used == 0


def test_gather_drops_huge_chunk_and_keeps_smaller_one() -> None:
    """PA-07: un fragmento enorme no entra y no impide que entre otro pequeño."""
    embeddings, store = FakeEmbeddingProvider(), SpyStore()
    add_chunk(store, embeddings, "BIG#0", "BIG", "glosarios", "reservas bloqueadas " * 5000)
    add_chunk(store, embeddings, "SMALL#0", "SMALL", "glosarios", "reservas bloqueadas ficticio")

    context = make_service(store=store, embeddings=embeddings, top_k=2).gather(
        {"kind": "need", "text": "reservas bloqueadas"}, None
    )

    assert refs(context.rag) == ["SMALL"]
    assert context.budget.dropped_chunks == 1
    assert context.budget.used <= context.budget.budget


def test_gather_huge_origin_is_kept_whole_and_leaves_no_room() -> None:
    """PA-07 · PA-442: un origen con 200 000 caracteres entra entero (sin marca); como se come
    el presupuesto, no entra ninguna fuente opcional (la guarda de la ventana decide después
    si cabe en el modelo)."""
    tracker = SpyTracker()
    origin = story("DEMO-70", "HU ficticia enorme", description_text="d" * 200_000)

    context = make_service(tracker).gather({"kind": "story", "key": "DEMO-70"}, origin)

    assert context.jira == [origin]
    assert not context.jira[0].description_text.endswith(TRUNCATION_MARK)
    assert context.rag == []
    assert context.budget.truncated_issues == 0
    assert context.budget.used == issue_tokens(origin) > 6000


def test_gather_excluded_issue_space_is_reused_by_next_issue() -> None:
    """RF-21 (T-51): la exclusión va antes del presupuesto; su hueco lo aprovecha la siguiente."""
    tracker = SpyTracker()
    tracker.issues["DEMO-71"] = story(
        "DEMO-71", "Vínculo ficticio enorme", description_text="d" * 8000
    )
    tracker.issues["DEMO-72"] = story("DEMO-72", "Vínculo ficticio pequeño", description_text="p")
    links = [IssueLink(link_type="relates to", key=k) for k in ("DEMO-71", "DEMO-72")]
    origin = story("DEMO-70", "HU ficticia de origen", links=links)
    service = make_service(tracker, token_budget=600)  # cuota de Jira = 300

    before = service.gather({"kind": "story", "key": "DEMO-70"}, origin)
    after = service.gather({"kind": "story", "key": "DEMO-70"}, origin, excluded=["DEMO-71"])

    assert [i.key for i in before.jira] == ["DEMO-70", "DEMO-71"]
    assert before.budget.dropped_issues == 1
    assert [i.key for i in after.jira] == ["DEMO-70", "DEMO-72"]
    assert after.budget.truncated_issues == 0


def test_gather_linked_issue_with_many_subtasks_respects_budget() -> None:
    """PA-07: con 200 subtareas en una HU vinculada, el total sigue sin pasar de 1000 tokens."""
    tracker = SpyTracker()
    subtasks = [
        summary(f"DEMO-{n}", f"Caso de prueba ficticio {n} de renovación", "Subtarea")
        for n in range(200, 400)
    ]
    tracker.issues["DEMO-73"] = story("DEMO-73", "HU ficticia con casos", subtasks=subtasks)
    origin = story(
        "DEMO-70", "HU ficticia", links=[IssueLink(link_type="relates to", key="DEMO-73")]
    )

    context = make_service(tracker, token_budget=1000).gather(
        {"kind": "story", "key": "DEMO-70"}, origin
    )

    assert sum(issue_tokens(i) for i in context.jira) <= 1000
    assert context.budget.used <= 1000


def test_gather_need_first_match_is_not_forced_beyond_budget() -> None:
    """PA-07: con una necesidad, las HU relacionadas son secundarias y respetan el presupuesto."""
    tracker = SpyTracker()

    context = make_service(tracker, token_budget=40, project_key="DEMO").gather(
        {"kind": "need", "text": "renovaciones"}, None
    )

    assert context.budget.used <= context.budget.budget


# === Fuentes excluidas en el RAG (RF-21, T-51) ===============================================


def test_gather_excluded_document_with_several_chunks_still_fills_top_k() -> None:
    """RF-21 (§11 «Fuentes excluidas»): excluir un documento de 4 fragmentos deja 3 de otros."""
    embeddings, store = FakeEmbeddingProvider(), SpyStore()
    for n in range(4):
        content = f"reservas bloqueadas mostrador ficticio parte {n}"
        add_chunk(store, embeddings, f"EXC#{n}", "EXC", "glosarios", content)
    for n in range(1, 5):
        content = f"reservas otro documento ficticio distinto {n}"
        add_chunk(store, embeddings, f"OTR-{n}#0", f"OTR-{n}", "glosarios", content)
    service = make_service(store=store, embeddings=embeddings, top_k=3)
    origin = {"kind": "need", "text": "reservas bloqueadas mostrador"}
    assert refs(service.gather(origin, None).rag) == ["EXC"] * 3  # control: EXC copa el top

    rag = service.gather(origin, None, excluded=["EXC"]).rag

    assert "EXC" not in refs(rag)
    assert len(rag) == 3


def test_gather_excluding_minutes_keeps_norm_without_searching_minutes() -> None:
    """RF-21 (T-51): excluir el acta deja la norma y no se busca el acta por el par."""
    embeddings, store = norm_minutes_corpus()
    service = make_service(store=store, embeddings=embeddings, top_k=1)
    origin = {"kind": "need", "text": "reservas bloqueadas cuarenta ocho horas mostrador"}
    assert refs(service.gather(origin, None).rag) == ["DOC-A", "DOC-B"]  # control
    store.calls.clear()

    rag = service.gather(origin, None, excluded=["DOC-B"]).rag

    assert refs(rag) == ["DOC-A"]
    assert all(call["filters"] is None for call in store.calls)


def test_gather_excluding_minutes_by_file_ref_also_blocks_pair() -> None:
    """RF-21 (T-51): el acta excluida por su `ref` (fichero) tampoco entra por el par."""
    embeddings, store = norm_minutes_corpus()
    service = make_service(store=store, embeddings=embeddings, top_k=1)
    origin = {"kind": "need", "text": "reservas bloqueadas cuarenta ocho horas mostrador"}

    rag = service.gather(origin, None, excluded=["acta-ficticia.pdf"]).rag

    assert refs(rag) == ["DOC-A"]


def test_gather_excluding_norm_by_doc_id_excludes_all_its_chunks_and_pair() -> None:
    """RF-21 (T-51): excluir la norma (por `doc_id`) quita sus fragmentos y no trae el acta."""
    embeddings, store = norm_minutes_corpus()
    add_chunk(
        store,
        embeddings,
        "norma.md#1",
        "norma.md",
        "politicas",
        "Norma ficticia, segunda parte: reservas bloqueadas en mostrador.",
        doc_id="DOC-A",
        related="DOC-B",
    )
    service = make_service(store=store, embeddings=embeddings, top_k=6)

    rag = service.gather(
        {"kind": "need", "text": "reservas bloqueadas mostrador"}, None, excluded=["DOC-A"]
    ).rag

    assert "DOC-A" not in refs(rag)
    assert refs(rag) == ["DOC-B"]  # el acta solo entra por su propia puntuación, no por el par


def test_gather_excluding_everything_keeps_only_origin() -> None:
    """RF-21 (límite): excluir todas las fuentes deja solo el origen; nada del RAG."""
    tracker = SpyTracker()
    embeddings, store = norm_minutes_corpus()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)
    excluded = ["DEMO-1", "DEMO-2", "DEMO-4", "DOC-A", "DOC-B", "DEMO-3"]

    context = make_service(tracker, store, embeddings).gather(STORY_ORIGIN, origin, excluded)

    assert [i.key for i in context.jira] == ["DEMO-3"]  # el origen nunca se excluye
    assert context.rag == []
    assert context.budget.used == issue_tokens(origin)


def test_gather_excluding_parent_epic_keeps_siblings() -> None:
    """RF-21 (T-51): excluir la épica padre quita la épica, no sus otras HU hijas."""
    tracker = SpyTracker()
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)

    context = make_service(tracker).gather(STORY_ORIGIN, origin, excluded=["DEMO-1"])

    assert [i.key for i in context.jira] == ["DEMO-3", "DEMO-2", "DEMO-4"]


def test_gather_excluded_link_slot_is_not_refilled_by_sixth_link() -> None:
    """RF-14, RF-21 · comportamiento fijado: el tope de 5 vínculos se aplica antes de excluir;
    excluir uno no trae el sexto (la SPEC solo exige el relleno en `top_k` del RAG)."""
    tracker = SpyTracker()
    for n in range(10, 16):
        tracker.issues[f"DEMO-{n}"] = story(f"DEMO-{n}", f"Vínculo ficticio {n}")
    links = [IssueLink(link_type="relates to", key=f"DEMO-{n}") for n in range(10, 16)]
    origin = story("DEMO-60", "HU ficticia con seis vínculos", links=links)

    context = make_service(tracker).gather(
        {"kind": "story", "key": "DEMO-60"}, origin, excluded=["DEMO-10"]
    )

    assert MAX_LINKED == 5
    assert [i.key for i in context.jira] == ["DEMO-60", "DEMO-11", "DEMO-12", "DEMO-13", "DEMO-14"]


# === Contexto de Jira: vínculos y hermanas (RF-14, T-18) ======================================


def test_gather_duplicate_and_self_links_are_not_repeated() -> None:
    """RF-14: un vínculo repetido, a sí misma o a su épica no duplica incidencias."""
    tracker = SpyTracker()
    links = [
        IssueLink(link_type="relates to", key="DEMO-2"),
        IssueLink(link_type="blocks", key="DEMO-2"),
        IssueLink(link_type="relates to", key="DEMO-3"),
        IssueLink(link_type="relates to", key="DEMO-1"),
    ]
    origin = tracker.issues["DEMO-3"].model_copy(update={"links": links}, deep=True)

    keys = [i.key for i in make_service(tracker).gather(STORY_ORIGIN, origin).jira]

    assert keys == ["DEMO-3", "DEMO-1", "DEMO-2", "DEMO-4"]


def test_gather_siblings_arrive_as_summary_without_get_issue() -> None:
    """RF-14 (eficiencia): con 30 hermanas solo se pide el detalle de la épica y del vínculo."""
    tracker = SpyTracker()
    for n in range(100, 130):
        tracker.issues[f"DEMO-{n}"] = story(
            f"DEMO-{n}", f"HU hermana ficticia {n}", parent_key="DEMO-1", description_text="x" * 50
        )
    origin = tracker.issues["DEMO-3"].model_copy(deep=True)

    context = make_service(tracker, token_budget=100_000).gather(STORY_ORIGIN, origin)

    assert sorted(tracker.get_calls) == ["DEMO-1", "DEMO-2"]
    siblings = [i for i in context.jira if i.key.startswith("DEMO-1") and i.key != "DEMO-1"]
    assert len(siblings) == 30
    assert all(s.description_text == "" and s.parent_key == "DEMO-1" for s in siblings)


@pytest.mark.parametrize("project", ["demo", "DE MO", 'DEMO" OR project = "OTRO'])
def test_gather_need_with_invalid_project_key_skips_jira(project: str) -> None:
    """RF-14, §11 (error): con una clave de proyecto no válida no se busca en Jira ni falla."""
    tracker = SpyTracker()

    context = make_service(tracker, project_key=project).gather(
        {"kind": "need", "text": "renovar préstamo"}, None
    )

    assert context.jira == []
    assert tracker.searches == []


def test_gather_need_asks_jira_for_at_most_twenty_candidates() -> None:
    """RF-14 (eficiencia): la búsqueda de la necesidad pide como mucho 20 candidatas."""
    tracker = SpyTracker(search_results=[])

    make_service(tracker, project_key="DEMO").gather({"kind": "need", "text": "renovar"}, None)

    assert MAX_NEED_CANDIDATES == 20
    assert tracker.searches[0][1] == MAX_NEED_CANDIDATES


def test_gather_need_related_issues_exclude_epics_and_subtasks() -> None:
    """RF-14, §6.1: las HU relacionadas con una necesidad son HU, no épicas ni subtareas."""
    tracker = SpyTracker(
        search_results=[
            summary("DEMO-80", "CP-01 Renovar préstamo vencido", "Subtarea"),
            summary("DEMO-81", "Renovar préstamo vencido", "Epic"),
            summary("DEMO-82", "Renovar un préstamo", "Historia"),
        ]
    )

    context = make_service(tracker, project_key="DEMO").gather(
        {"kind": "need", "text": "renovar préstamo vencido"}, None
    )

    assert [i.key for i in context.jira] == ["DEMO-82"]


# === similar_stories y NOT_STORIES (T-53, RF-14, PA-55) =======================================


@pytest.mark.parametrize(
    "issue_type", ["EPIC", " Épica ", "épica", "SUB-TASK", "Subtarea", "SubTask", "TAREA", "task"]
)
def test_similar_stories_drops_non_story_types_in_any_case(issue_type: str) -> None:
    """T-53: épicas, subtareas y tareas no son «HU parecida», en mayúsculas o con espacios."""
    tracker = SpyTracker(search_results=[summary("DEMO-90", "Renovar préstamo", issue_type)])

    assert make_service(tracker).similar_stories("renovar préstamo", "DEMO") == []


@pytest.mark.parametrize("issue_type", ["Story", "story", "Historia", "HISTORIA", "Bug", "Error"])
def test_similar_stories_keeps_story_and_bug_like_types(issue_type: str) -> None:
    """T-53 · comportamiento fijado (PA-55 pendiente): «Historia» en cualquier caja es HU; «Bug»
    y «Error» no están en NOT_STORIES y también se proponen."""
    tracker = SpyTracker(search_results=[summary("DEMO-91", "Renovar préstamo", issue_type)])

    result = make_service(tracker).similar_stories("renovar préstamo", "DEMO")

    assert [i.key for i in result] == ["DEMO-91"]


def test_similar_stories_filters_before_cutting_to_three() -> None:
    """T-53: con cinco épicas delante, aún salen las HU que vienen detrás (se filtra y se corta)."""
    epics = [summary(f"DEMO-{n}", "Renovar préstamo vencido", "Epic") for n in range(1, 6)]
    stories = [summary(f"DEMO-{n}", "Renovar préstamo", "Story") for n in range(20, 24)]
    tracker = SpyTracker(search_results=[*epics, *stories])

    result = make_service(tracker).similar_stories("renovar préstamo vencido", "DEMO")

    assert [i.key for i in result] == ["DEMO-20", "DEMO-21", "DEMO-22"]


@pytest.mark.parametrize("project", INVALID_PROJECTS)
def test_similar_stories_injected_project_returns_empty_without_search(project: str) -> None:
    """T-53, §11 (seguridad): una clave de proyecto inyectada no lanza búsqueda ni excepción."""
    tracker = SpyTracker()

    assert make_service(tracker).similar_stories("renovar préstamo", project) == []
    assert tracker.searches == []


def test_similar_stories_uses_only_lowercase_keywords_in_jql() -> None:
    """T-53, RF-14: la JQL de las HU parecidas lleva palabras clave, sin palabras vacías."""
    tracker = SpyTracker(search_results=[])

    make_service(tracker).similar_stories("Como socia QUIERO Renovar un PRÉSTAMO", "DEMO")

    assert jql_literal(tracker.searches[0][0]) == "renovar OR préstamo"


def test_not_stories_are_normalized_lowercase_without_spaces() -> None:
    """T-53: NOT_STORIES está en minúsculas y sin espacios (se compara con `strip().lower()`)."""
    assert all(t == t.strip().lower() for t in NOT_STORIES)
    assert {"epic", "épica", "subtarea", "sub-task", "task", "tarea"} <= NOT_STORIES
    assert not {"story", "historia"} & NOT_STORIES


def test_related_pairs_are_symmetric_norm_and_minutes_only() -> None:
    """PA-69: el par es exactamente politicas ↔ documentacion, en los dos sentidos."""
    assert RELATED_PAIRS == {"politicas": "documentacion", "documentacion": "politicas"}


def test_truncate_issue_with_thousands_of_relations_is_fast_and_within_budget() -> None:
    """PA-165 · revisión de seguridad: miles de etiquetas y subtareas se recortan en tiempo
    lineal y el resultado nunca supera el máximo (sin la marca de recorte si no cabe)."""
    import time

    from core.context.budget import truncate_issue

    subtasks = [summary(f"DEMO-{n}", "Caso ficticio", "Subtarea") for n in range(1000, 6000)]
    issue = story("DEMO-70", "HU ficticia", subtasks=subtasks).model_copy(
        update={"labels": ["x"] * 50_000, "description_text": "d" * 50_000}
    )
    for budget in (1000, 6000, 24_000):
        start = time.perf_counter()
        trimmed = truncate_issue(issue, budget)
        assert time.perf_counter() - start < 1.0
        assert issue_tokens(trimmed) <= budget
