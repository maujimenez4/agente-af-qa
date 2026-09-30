"""Evaluación de la recuperación del RAG (T-17, RNF-14, RNF-09).

La API (`evaluate`, métricas e informe) trabaja contra los protocolos `VectorStore` y
`EmbeddingProvider` de `adapters/base.py`, sin implementaciones concretas ni red. Solo `main`
compone los adaptadores reales (PostgreSQL + Ollama) para evaluar el corpus indexado:
`uv run python -m eval.retrieval_eval [k]`.

Métricas por pregunta:
- recall@k: fracción de `expected_docs` presentes entre los documentos recuperados.
- reciprocal rank: 1 / posición del primer documento esperado (0 si no aparece ninguno).
Las posiciones se cuentan sobre los ids de documento recuperados, deduplicados en orden,
porque un mismo documento puede aportar varios fragmentos.
"""

import time
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from adapters.base import EmbeddingProvider, RetrievedChunk, VectorStore

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "retrieval_questions.yaml"
MIN_QUESTIONS = 10
LATENCY_TARGET_MS = 3000.0  # RNF-09
DOC_ID_KEY = "doc_id"


class RetrievalQuestion(BaseModel):
    id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    expected_docs: list[str] = Field(min_length=1)
    category: str | None = None


class QuestionResult(BaseModel):
    id: str
    question: str
    expected_docs: list[str]
    retrieved_docs: list[str]
    recall: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)


class RetrievalReport(BaseModel):
    k: int = Field(ge=1)
    recall_at_k: float = Field(ge=0.0, le=1.0)
    mrr: float = Field(ge=0.0, le=1.0)
    mean_latency_ms: float = Field(ge=0.0)
    max_latency_ms: float = Field(ge=0.0)
    latency_target_ms: float = LATENCY_TARGET_MS
    meets_latency_target: bool
    results: list[QuestionResult]


def load_questions(path: Path = DEFAULT_QUESTIONS_PATH) -> list[RetrievalQuestion]:
    """Carga y valida el set de preguntas (mínimo 10, ids únicos, `expected_docs` no vacío)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list):
        raise ValueError(f"El fichero {path.name} no contiene una lista «questions».")
    questions = [RetrievalQuestion.model_validate(item) for item in data["questions"]]
    if len(questions) < MIN_QUESTIONS:
        raise ValueError(
            f"El set de evaluación necesita al menos {MIN_QUESTIONS} preguntas; "
            f"hay {len(questions)}."
        )
    ids = [q.id for q in questions]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"Ids de pregunta duplicados: {', '.join(duplicated)}.")
    return questions


def doc_id_of(result: RetrievedChunk) -> str:
    """Id de documento del corpus (`DOC-NN`) de un fragmento recuperado.

    Usa `metadata["doc_id"]` (lo añade `core/rag/indexing.py`) y, si falta, `chunk.document_id`,
    que en la ingesta de T-12 es también el `id` de la cabecera del documento.
    """
    return result.chunk.metadata.get(DOC_ID_KEY) or result.chunk.document_id


def dedupe_in_order(items: Sequence[str]) -> list[str]:
    """Elimina duplicados conservando el orden de la primera aparición."""
    return list(dict.fromkeys(items))


def recall(expected: Sequence[str], retrieved: Sequence[str]) -> float:
    """Fracción de documentos esperados presentes entre los recuperados."""
    expected_set = set(expected)
    if not expected_set:
        return 0.0
    return len(expected_set & set(retrieved)) / len(expected_set)


def reciprocal_rank(expected: Sequence[str], retrieved: Sequence[str]) -> float:
    """1 / posición (desde 1) del primer documento esperado; 0 si no aparece ninguno."""
    expected_set = set(expected)
    for position, doc in enumerate(retrieved, start=1):
        if doc in expected_set:
            return 1.0 / position
    return 0.0


def evaluate_question(
    store: VectorStore,
    embeddings: EmbeddingProvider,
    question: RetrievalQuestion,
    k: int = 6,
    memory_boost: float = 1.0,
    doc_id: Callable[[RetrievedChunk], str] = doc_id_of,
) -> QuestionResult:
    """Recupera los k fragmentos de una pregunta y calcula sus métricas.

    La latencia mide la recuperación completa (embeber la pregunta + búsqueda).
    """
    start = time.perf_counter()
    vector = embeddings.embed([question.question])[0]
    hits = store.search(vector, question.question, k, memory_boost=memory_boost)
    latency_ms = (time.perf_counter() - start) * 1000
    retrieved = dedupe_in_order([doc_id(hit) for hit in hits])
    return QuestionResult(
        id=question.id,
        question=question.question,
        expected_docs=question.expected_docs,
        retrieved_docs=retrieved,
        recall=recall(question.expected_docs, retrieved),
        reciprocal_rank=reciprocal_rank(question.expected_docs, retrieved),
        latency_ms=max(latency_ms, 0.0),
    )


def evaluate(
    store: VectorStore,
    embeddings: EmbeddingProvider,
    questions: Sequence[RetrievalQuestion],
    k: int = 6,
    memory_boost: float = 1.0,
    doc_id: Callable[[RetrievedChunk], str] = doc_id_of,
) -> RetrievalReport:
    """Evalúa la recuperación sobre el set de preguntas y agrega las métricas."""
    if k < 1:
        raise ValueError("k debe ser mayor o igual que 1.")
    if not questions:
        raise ValueError("No hay preguntas que evaluar.")
    results = [
        evaluate_question(store, embeddings, q, k=k, memory_boost=memory_boost, doc_id=doc_id)
        for q in questions
    ]
    count = len(results)
    latencies = [r.latency_ms for r in results]
    max_latency = max(latencies)
    return RetrievalReport(
        k=k,
        recall_at_k=sum(r.recall for r in results) / count,
        mrr=sum(r.reciprocal_rank for r in results) / count,
        mean_latency_ms=sum(latencies) / count,
        max_latency_ms=max_latency,
        meets_latency_target=max_latency <= LATENCY_TARGET_MS,
        results=results,
    )


def format_report(report: RetrievalReport) -> str:
    """Informe de la evaluación en Markdown (español)."""
    verdict = "sí" if report.meets_latency_target else "no"
    lines = [
        "# Evaluación de la recuperación",
        "",
        f"- Preguntas: {len(report.results)}",
        f"- k: {report.k}",
        f"- Recall@{report.k}: {report.recall_at_k:.2f}",
        f"- MRR: {report.mrr:.2f}",
        f"- Latencia media: {report.mean_latency_ms:.1f} ms",
        f"- Latencia máxima: {report.max_latency_ms:.1f} ms",
        f"- Cumple el objetivo de latencia (≤ {report.latency_target_ms:.0f} ms, RNF-09): "
        f"{verdict}",
        "",
        "## Detalle por pregunta",
        "",
        "| Id | Esperados | Recuperados | Recall | RR | Latencia (ms) |",
        "|---|---|---|---|---|---|",
    ]
    for r in report.results:
        retrieved = ", ".join(r.retrieved_docs) or "—"
        lines.append(
            f"| {r.id} | {', '.join(r.expected_docs)} | {retrieved} | "
            f"{r.recall:.2f} | {r.reciprocal_rank:.2f} | {r.latency_ms:.1f} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Evalúa la recuperación real: `uv run python -m eval.retrieval_eval [k]`.

    Requiere el corpus indexado (`uv run python -m core.rag.indexing`), PostgreSQL y Ollama.
    """
    import sys

    from core.config import build_config
    from core.factories import build_embeddings, build_vector_store

    args = sys.argv[1:] if argv is None else argv
    if args and not (args[0].isdigit() and int(args[0]) >= 1):
        sys.stderr.write("Uso: python -m eval.retrieval_eval [k], con k entero positivo.\n")
        return 2
    config = build_config()
    k = int(args[0]) if args else config.models.rag.top_k
    report = evaluate(
        build_vector_store(config),
        build_embeddings(config),
        load_questions(),
        k=k,
        memory_boost=config.models.rag.memory_boost,
    )
    sys.stdout.reconfigure(encoding="utf-8")  # consolas de Windows en cp1252
    sys.stdout.write(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
