"""Pruebas del set de preguntas y del script de evaluación de la recuperación (T-17)."""

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from adapters.base import Chunk, EmbeddingProvider, RetrievedChunk, VectorStore
from core.rag.documents import CATEGORIES
from eval.retrieval_eval import (
    DEFAULT_QUESTIONS_PATH,
    LATENCY_TARGET_MS,
    RetrievalQuestion,
    doc_id_of,
    evaluate,
    format_report,
    load_questions,
)
from schemas.common import SourceRef
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.vector_store import FakeVectorStore

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "seed" / "corpus"


def _corpus_docs() -> dict[str, tuple[dict, str]]:
    """Documentos del corpus por id: (cabecera YAML, cuerpo)."""
    docs: dict[str, tuple[dict, str]] = {}
    for path in sorted(CORPUS.rglob("DOC-*.md")):
        _, header, body = path.read_text(encoding="utf-8").split("---", 2)
        meta = yaml.safe_load(header)
        docs[meta["id"]] = (meta, body)
    return docs


def _hit(doc: str, *, in_metadata: bool = True) -> RetrievedChunk:
    chunk = Chunk(
        id=f"{doc}-0",
        document_id="uuid-ficticio" if in_metadata else doc,
        ordinal=0,
        content=f"Contenido sintético de {doc}",
        metadata={"doc_id": doc} if in_metadata else {},
    )
    return RetrievedChunk(chunk=chunk, score=1.0, source=SourceRef(kind="rag", ref=doc))


@dataclass
class ScriptedStore:
    """Store determinista: devuelve, para cada pregunta, los documentos indicados en orden."""

    answers: dict[str, list[str]]
    calls: list[tuple[str, int, float]] = field(default_factory=list)

    def upsert(self, chunks: list[Chunk]) -> None: ...

    def delete_by_document(self, document_id: str) -> None: ...

    def search(
        self,
        query_vector: list[float],
        query_text: str,
        k: int,
        filters: dict[str, str] | None = None,
        memory_boost: float = 1.0,
    ) -> list[RetrievedChunk]:
        self.calls.append((query_text, k, memory_boost))
        return [_hit(doc) for doc in self.answers.get(query_text, [])][:k]


def _question(qid: str, text: str, expected: list[str]) -> RetrievalQuestion:
    return RetrievalQuestion(id=qid, question=text, expected_docs=expected)


# --- Set de preguntas -------------------------------------------------------------------


def test_questions_file_loads_ten_valid_questions() -> None:
    raw = yaml.safe_load(DEFAULT_QUESTIONS_PATH.read_text(encoding="utf-8"))
    questions = load_questions()

    assert raw["version"] == 1
    assert len(questions) == 10
    assert len({q.id for q in questions}) == 10
    assert all(q.id == f"Q-{n:02d}" for n, q in enumerate(questions, start=1))
    assert all(q.expected_docs and q.question.strip() for q in questions)


def test_expected_docs_exist_in_corpus_headers() -> None:
    corpus_ids = set(_corpus_docs())
    for question in load_questions():
        missing = set(question.expected_docs) - corpus_ids
        assert not missing, f"{question.id} referencia documentos inexistentes: {missing}"


ACTA_IDS = frozenset({"DOC-19", "DOC-20", "DOC-21", "DOC-22"})
# Categorías con documentos esperados en el set actual (T-49 solo remapeó `category`).
CURRENT_QUESTION_CATEGORIES = frozenset({"politicas", "documentacion", "procesos", "glosarios"})


def _is_acta(meta: dict) -> bool:
    """Las actas están en `documentacion` (T-49): se reconocen por id o por título «Acta…»."""
    return meta["id"] in ACTA_IDS or str(meta.get("title", "")).startswith("Acta")


def test_questions_cover_categories_and_amending_minutes() -> None:
    """RNF-14 · T-49: las categorías del set son las de RF-12, cubren las 4 actuales y hay
    al menos 3 preguntas cuya respuesta combina una política con el acta que la cambió."""
    docs = _corpus_docs()
    questions = load_questions()
    categories = {docs[d][0]["category"] for q in questions for d in q.expected_docs}
    with_minutes = [
        q
        for q in questions
        if any(_is_acta(docs[d][0]) for d in q.expected_docs)
        and any(docs[d][0]["category"] == "politicas" for d in q.expected_docs)
    ]

    assert categories <= set(CATEGORIES), (
        f"Categorías fuera de RF-12: {categories - set(CATEGORIES)}"
    )
    assert categories >= CURRENT_QUESTION_CATEGORIES
    assert len(categories) >= 4
    assert len(with_minutes) >= 3
    for q in questions:
        if q.category is not None:
            assert q.category in CATEGORIES, f"{q.id}: categoría '{q.category}' no válida"
            assert q.category in {docs[d][0]["category"] for d in q.expected_docs}


def test_load_questions_rejects_invalid_sets(tmp_path: Path) -> None:
    base = [{"id": "Q-01", "question": "¿Pregunta?", "expected_docs": ["DOC-01"]}]
    too_few = tmp_path / "pocas.yaml"
    too_few.write_text(yaml.safe_dump({"version": 1, "questions": base * 1}), encoding="utf-8")
    duplicated = tmp_path / "duplicadas.yaml"
    duplicated.write_text(yaml.safe_dump({"version": 1, "questions": base * 10}), "utf-8")
    empty_docs = tmp_path / "vacias.yaml"
    items = [{"id": f"Q-{n:02d}", "question": "¿Pregunta?", "expected_docs": []} for n in range(10)]
    empty_docs.write_text(yaml.safe_dump({"version": 1, "questions": items}), "utf-8")

    with pytest.raises(ValueError, match="al menos 10"):
        load_questions(too_few)
    with pytest.raises(ValueError, match="duplicados"):
        load_questions(duplicated)
    with pytest.raises(ValueError):
        load_questions(empty_docs)


# --- Métricas ---------------------------------------------------------------------------


def test_doc_id_of_prefers_metadata_and_falls_back_to_document_id() -> None:
    assert doc_id_of(_hit("DOC-05")) == "DOC-05"
    assert doc_id_of(_hit("DOC-07", in_metadata=False)) == "DOC-07"


def test_hit_at_first_position() -> None:
    store = ScriptedStore({"p1": ["DOC-01", "DOC-02"]})
    report = evaluate(store, FakeEmbeddingProvider(), [_question("Q-01", "p1", ["DOC-01"])])

    assert report.results[0].recall == 1.0
    assert report.results[0].reciprocal_rank == 1.0
    assert report.recall_at_k == 1.0
    assert report.mrr == 1.0


def test_hit_at_third_position_with_duplicated_chunks() -> None:
    # DOC-03 aparece dos veces: se deduplica y DOC-01 queda en la posición 3.
    store = ScriptedStore({"p": ["DOC-03", "DOC-03", "DOC-04", "DOC-01"]})
    report = evaluate(store, FakeEmbeddingProvider(), [_question("Q-01", "p", ["DOC-01"])])

    assert report.results[0].retrieved_docs == ["DOC-03", "DOC-04", "DOC-01"]
    assert report.results[0].reciprocal_rank == pytest.approx(1 / 3)
    assert report.results[0].recall == 1.0


def test_total_miss() -> None:
    store = ScriptedStore({"p": ["DOC-10", "DOC-11"]})
    report = evaluate(store, FakeEmbeddingProvider(), [_question("Q-01", "p", ["DOC-01"])])

    assert report.results[0].recall == 0.0
    assert report.results[0].reciprocal_rank == 0.0


def test_partial_recall_with_two_expected_docs() -> None:
    store = ScriptedStore({"p": ["DOC-09", "DOC-20", "DOC-11"]})
    report = evaluate(
        store, FakeEmbeddingProvider(), [_question("Q-01", "p", ["DOC-03", "DOC-20"])]
    )

    assert report.results[0].recall == 0.5
    assert report.results[0].reciprocal_rank == 0.5


def test_aggregates_over_questions_and_passes_parameters() -> None:
    store = ScriptedStore(
        {
            "a": ["DOC-01"],
            "b": ["DOC-05", "DOC-06", "DOC-02"],
            "c": ["DOC-09"],
            "d": ["DOC-20", "DOC-03"],
        }
    )
    questions = [
        _question("Q-01", "a", ["DOC-01"]),
        _question("Q-02", "b", ["DOC-02"]),
        _question("Q-03", "c", ["DOC-01"]),
        _question("Q-04", "d", ["DOC-03", "DOC-19"]),
    ]
    report = evaluate(store, FakeEmbeddingProvider(), questions, k=4, memory_boost=1.5)

    assert report.k == 4
    assert report.recall_at_k == pytest.approx((1 + 1 + 0 + 0.5) / 4)
    assert report.mrr == pytest.approx((1 + 1 / 3 + 0 + 1 / 2) / 4)
    assert all(call[1:] == (4, 1.5) for call in store.calls)
    assert report.meets_latency_target
    assert report.max_latency_ms >= report.mean_latency_ms >= 0


def test_evaluate_rejects_empty_questions_and_invalid_k() -> None:
    store = ScriptedStore({})
    with pytest.raises(ValueError):
        evaluate(store, FakeEmbeddingProvider(), [])
    with pytest.raises(ValueError):
        evaluate(store, FakeEmbeddingProvider(), [_question("Q-01", "p", ["DOC-01"])], k=0)


def test_format_report_in_spanish_markdown() -> None:
    store = ScriptedStore({"p": ["DOC-01"]})
    report = evaluate(store, FakeEmbeddingProvider(), [_question("Q-01", "p", ["DOC-01"])])
    text = format_report(report)

    assert text.startswith("# Evaluación de la recuperación")
    assert "Recall@6: 1.00" in text
    assert "MRR: 1.00" in text
    assert f"≤ {LATENCY_TARGET_MS:.0f} ms" in text
    assert "| Q-01 | DOC-01 | DOC-01 |" in text


# --- Recorrido con los fakes sobre el corpus --------------------------------------------


def test_end_to_end_with_fakes_over_corpus() -> None:
    embeddings = FakeEmbeddingProvider()
    store = FakeVectorStore()
    assert isinstance(embeddings, EmbeddingProvider)
    assert isinstance(store, VectorStore)

    docs = _corpus_docs()
    ids = sorted(docs)
    vectors = embeddings.embed([docs[i][1] for i in ids])
    store.upsert(
        [
            Chunk(
                id=f"{doc}-0",
                document_id=doc,
                ordinal=0,
                content=docs[doc][1],
                embedding=vector,
                metadata={"doc_id": doc, "category": docs[doc][0]["category"]},
            )
            for doc, vector in zip(ids, vectors, strict=True)
        ]
    )

    questions = load_questions()
    report = evaluate(store, embeddings, questions, k=6)

    assert len(report.results) == len(questions)
    assert 0.0 <= report.recall_at_k <= 1.0
    assert 0.0 <= report.mrr <= 1.0
    assert report.mean_latency_ms >= 0.0
    assert report.max_latency_ms >= report.mean_latency_ms
    for result in report.results:
        assert 0.0 <= result.recall <= 1.0
        assert 0.0 <= result.reciprocal_rank <= 1.0
        assert result.latency_ms >= 0.0
        assert len(result.retrieved_docs) <= 6
        assert set(result.retrieved_docs) <= set(ids)
    assert "## Detalle por pregunta" in format_report(report)
