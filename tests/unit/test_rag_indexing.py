"""Pruebas de la indexación del corpus (T-16) y de la CLI de evaluación (T-17).

RF-09/RF-10 (metadata de cada fragmento), RF-38 (reindexar sustituye los fragmentos) y
RNF-14 (evaluación real de la recuperación). Datos 100 % sintéticos (Biblioteca Municipal de
Villaficticia); sin red, sin Docling real, sin PostgreSQL ni `.env`.
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from adapters.base import Chunk
from core.config import AppConfig, Settings, load_models_config
from core.rag.chunking import chunk_document
from core.rag.documents import CATEGORIES, IngestedDocument
from core.rag.indexing import (
    CorpusIndexer,
    IndexReport,
    embedding_text,
    prepare_chunks,
    relative_source,
)
from core.rag.ingest import Ingestor, split_front_matter
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "data" / "seed" / "corpus"
TODAY = date(2026, 1, 15)
DIMENSIONS = 16


# --- Dobles y utilidades --------------------------------------------------------------------


class ReadFileExtractor:
    """Extractor falso sin Docling: el texto tal cual, sin la cabecera YAML (como Docling)."""

    def extract(self, path: Path) -> str:
        _, body = split_front_matter(path.read_text(encoding="utf-8"))
        return body


@dataclass
class RecordingEmbeddings(FakeEmbeddingProvider):
    """`FakeEmbeddingProvider` que guarda los textos que se le piden vectorizar."""

    texts: list[str] = field(default_factory=list)

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return super().embed(texts)


@dataclass
class SpyVectorStore(FakeVectorStore):
    """`FakeVectorStore` que registra el orden de las llamadas de escritura."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def upsert(self, chunks: list[Chunk]) -> None:
        for document_id in dict.fromkeys(c.document_id for c in chunks):
            self.calls.append(("upsert", document_id))
        super().upsert(chunks)

    def delete_by_document(self, document_id: str) -> None:
        self.calls.append(("delete", document_id))
        super().delete_by_document(document_id)


def _write_md(path: Path, body: str, **header: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", *(f"{k}: {v}" for k, v in header.items()), "---", "", body]
    path.write_bytes("\n".join(lines).encode("utf-8"))
    return path


def _synthetic_corpus(root: Path) -> Path:
    """Tres documentos ficticios con cabecera YAML y un README de índice."""
    _write_md(
        root / "politicas" / "DOC-91-reglamento-ficticio.md",
        "# Reglamento ficticio\n\n## Plazos\n\n"
        + "El préstamo ficticio dura veintiún días naturales. " * 6
        + "\n\n## Renovaciones\n\nSe permiten dos renovaciones ficticias por ejemplar.",
        id="DOC-91",
        title="Reglamento ficticio de préstamo",
        category="politicas",
        date="2026-03-01",
    )
    _write_md(
        root / "glosarios" / "DOC-92-glosario-ficticio.md",
        "# Glosario ficticio\n\n## Términos\n\nEjemplar: copia física ficticia de una obra.",
        id="DOC-92",
        title="Glosario ficticio",
        category="glosarios",
    )
    _write_md(
        root / "politicas" / "DOC-93-politica-ficticia.md",
        "# Política ficticia\n\nLas sanciones ficticias se aplican por retraso en la devolución.",
        id="DOC-93",
        title="Política ficticia de sanciones",
        category="politicas",
    )
    (root / "README.md").write_text(
        "# Índice ficticio del corpus\n\nNo debe indexarse.", encoding="utf-8"
    )
    return root


def _indexer(
    embeddings: FakeEmbeddingProvider | None = None,
    store: FakeVectorStore | None = None,
    chunk_tokens: int = 40,
    overlap_tokens: int = 5,
) -> CorpusIndexer:
    return CorpusIndexer(
        Ingestor(FakeLLMProvider(), extractor=ReadFileExtractor()),
        lambda doc: chunk_document(doc, chunk_tokens, overlap_tokens),
        embeddings or FakeEmbeddingProvider(dimensions=DIMENSIONS),
        store if store is not None else FakeVectorStore(),
    )


def _doc(root: Path, source: Path | None = None, **overrides: object) -> IngestedDocument:
    values: dict[str, object] = {
        "id": "DOC-90",
        "title": "Documento ficticio",
        "category": "procesos",
        "classified_by": "metadata",
        "source_path": (source or root / "procesos" / "DOC-90-ficticio.md").as_posix(),
        "content_hash": "hash-ficticio-0001",
        "text": "# Documento ficticio\n\nTexto ficticio.",
        "metadata": {"date": "2026-02-10"},
    }
    values.update(overrides)
    return IngestedDocument.model_validate(values)


def _chunk(ordinal: int = 0, **metadata: str) -> Chunk:
    base = {
        "category": "procesos",
        "title": "Documento ficticio",
        "section": "Alta ficticia",
        "date": "2026-02-10",
        "source": "C:/ruta/absoluta/ficticia/DOC-90.md",
    }
    base.update(metadata)
    return Chunk(
        id=f"DOC-90#{ordinal}",
        document_id="DOC-90",
        ordinal=ordinal,
        section="Alta ficticia",
        content=f"Contenido ficticio {ordinal}.",
        metadata=base,
    )


# --- relative_source / prepare_chunks (RF-10) -----------------------------------------------


def test_relative_source_returns_posix_path_when_inside_root(tmp_path: Path) -> None:
    """RF-10: la ruta se guarda relativa a la raíz del corpus, con `/`."""
    source = tmp_path / "procesos" / "sub" / "DOC-90.md"
    assert relative_source(str(source), tmp_path) == "procesos/sub/DOC-90.md"


def test_relative_source_returns_only_name_when_outside_root(tmp_path: Path) -> None:
    """RF-10: fuera de la raíz solo se guarda el nombre (nunca la ruta del equipo)."""
    outside = tmp_path.parent / "otra-carpeta-ficticia" / "DOC-99.md"
    assert relative_source(str(outside), tmp_path / "corpus") == "DOC-99.md"


def test_prepare_chunks_adds_vector_store_metadata_when_called(tmp_path: Path) -> None:
    """RF-10 / SPEC-00 §11: añade source_path, source, content_hash, doc_id, classified_by e
    ingested_at (ISO con `today` inyectado)."""
    doc = _doc(tmp_path, classified_by="llm")
    [prepared] = prepare_chunks(doc, [_chunk()], tmp_path, today=TODAY)
    meta = prepared.metadata
    assert meta["source_path"] == "procesos/DOC-90-ficticio.md"
    assert meta["source"] == "procesos/DOC-90-ficticio.md"
    assert meta["content_hash"] == "hash-ficticio-0001"
    assert meta["doc_id"] == doc.id == "DOC-90"
    assert meta["classified_by"] == "llm"
    assert meta["ingested_at"] == "2026-01-15"


def test_prepare_chunks_uses_today_when_no_date_injected(tmp_path: Path) -> None:
    """RF-10: sin `today`, `ingested_at` es la fecha actual en ISO."""
    [prepared] = prepare_chunks(_doc(tmp_path), [_chunk()], tmp_path)
    assert prepared.metadata["ingested_at"] == date.today().isoformat()


def test_prepare_chunks_keeps_previous_metadata_when_adding_fields(tmp_path: Path) -> None:
    """RF-10: conserva category, title, section, date y otros campos previos."""
    [prepared] = prepare_chunks(_doc(tmp_path), [_chunk(related="DOC-01")], tmp_path, today=TODAY)
    meta = prepared.metadata
    assert meta["category"] == "procesos"
    assert meta["title"] == "Documento ficticio"
    assert meta["section"] == "Alta ficticia"
    assert meta["date"] == "2026-02-10"
    assert meta["related"] == "DOC-01"
    assert prepared.content == "Contenido ficticio 0."
    assert prepared.section == "Alta ficticia"


def test_prepare_chunks_never_stores_absolute_path_when_source_outside_root(
    tmp_path: Path,
) -> None:
    """RF-10: si la fuente está fuera de la raíz, source y source_path son solo el nombre."""
    outside = tmp_path / "fuera" / "DOC-90-ficticio.md"
    doc = _doc(tmp_path, source=outside)
    [prepared] = prepare_chunks(doc, [_chunk()], tmp_path / "corpus", today=TODAY)
    assert prepared.metadata["source_path"] == "DOC-90-ficticio.md"
    assert prepared.metadata["source"] == "DOC-90-ficticio.md"


def test_prepare_chunks_does_not_mutate_original_chunks(tmp_path: Path) -> None:
    """RF-10: los fragmentos de entrada no se modifican."""
    originals = [_chunk(0), _chunk(1)]
    snapshot = [c.model_dump() for c in originals]
    prepared = prepare_chunks(_doc(tmp_path), originals, tmp_path, today=TODAY)
    assert [c.model_dump() for c in originals] == snapshot
    assert all(p is not o for p, o in zip(prepared, originals, strict=True))
    assert all(p.metadata is not o.metadata for p, o in zip(prepared, originals, strict=True))


def test_prepare_chunks_returns_empty_list_when_no_chunks(tmp_path: Path) -> None:
    """Límite: sin fragmentos no hay nada que preparar."""
    assert prepare_chunks(_doc(tmp_path), [], tmp_path, today=TODAY) == []


# --- embedding_text ------------------------------------------------------------------------


def test_embedding_text_prepends_title_and_section_when_both_exist() -> None:
    """RF-09: el título y la sección dan contexto al fragmento que se vectoriza."""
    chunk = _chunk()
    assert embedding_text(chunk) == "Documento ficticio · Alta ficticia\n\nContenido ficticio 0."


def test_embedding_text_prepends_only_title_when_no_section() -> None:
    """RF-09: sin sección, solo se antepone el título."""
    chunk = _chunk().model_copy(update={"section": None})
    assert embedding_text(chunk) == "Documento ficticio\n\nContenido ficticio 0."


def test_embedding_text_prepends_only_section_when_no_title() -> None:
    """RF-09: sin título, solo se antepone la sección."""
    chunk = _chunk()
    chunk = chunk.model_copy(
        update={"metadata": {k: v for k, v in chunk.metadata.items() if k != "title"}}
    )
    assert embedding_text(chunk) == "Alta ficticia\n\nContenido ficticio 0."


def test_embedding_text_returns_content_when_no_title_nor_section() -> None:
    """RF-09: sin título ni sección se vectoriza solo el contenido."""
    chunk = Chunk(id="X#0", document_id="X", ordinal=0, content="Solo contenido ficticio.")
    assert embedding_text(chunk) == "Solo contenido ficticio."


# --- CorpusIndexer.index_dir (T-16) ----------------------------------------------------------


def test_index_dir_reports_documents_chunks_and_categories_when_corpus_indexed(
    tmp_path: Path,
) -> None:
    """T-16: el informe cuenta documentos, fragmentos y documentos por categoría."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    report = _indexer(store=store).index_dir(root)
    assert isinstance(report, IndexReport)
    assert report.documents == 3
    assert report.by_category == {"politicas": 2, "glosarios": 1}
    assert report.chunks == len(store.chunks)
    assert report.chunks > report.documents  # el reglamento se fragmenta en varias partes


def test_index_dir_stores_chunks_with_embedding_and_metadata_when_indexed(
    tmp_path: Path,
) -> None:
    """T-16 / RF-10: cada fragmento tiene embedding de la dimensión correcta y la metadata
    que espera el VectorStore."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    _indexer(store=store).index_dir(root)
    assert store.chunks
    for chunk in store.chunks.values():
        assert chunk.embedding is not None and len(chunk.embedding) == DIMENSIONS
        meta = chunk.metadata
        assert meta["doc_id"] == chunk.document_id
        assert meta["category"] in CATEGORIES
        assert meta["classified_by"] == "metadata"
        assert len(meta["content_hash"]) == 64
        assert date.fromisoformat(meta["ingested_at"])
        assert not Path(meta["source_path"]).is_absolute()
        assert meta["source"] == meta["source_path"]
        assert meta["title"]
    reglamento = [c for c in store.chunks.values() if c.document_id == "DOC-91"]
    assert {c.metadata["source_path"] for c in reglamento} == {
        "politicas/DOC-91-reglamento-ficticio.md"
    }
    assert {c.metadata["date"] for c in reglamento} == {"2026-03-01"}
    assert any(c.metadata.get("section", "").endswith("Plazos") for c in reglamento)


def test_index_dir_does_not_duplicate_chunks_when_reindexed(tmp_path: Path) -> None:
    """RF-38: reindexar dos veces deja los mismos fragmentos."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    indexer = _indexer(store=store)
    first = indexer.index_dir(root)
    ids_first = sorted(store.chunks)
    second = indexer.index_dir(root)
    assert sorted(store.chunks) == ids_first
    assert second == first


def test_index_dir_deletes_document_before_upsert_when_indexing(tmp_path: Path) -> None:
    """RF-38: por cada documento se llama a `delete_by_document` justo antes del `upsert`."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = SpyVectorStore()
    _indexer(store=store).index_dir(root)
    # `ingest_dir` recorre las rutas ordenadas: glosarios/DOC-92, politicas/DOC-91, …/DOC-93.
    assert store.calls == [
        ("delete", "DOC-92"),
        ("upsert", "DOC-92"),
        ("delete", "DOC-91"),
        ("upsert", "DOC-91"),
        ("delete", "DOC-93"),
        ("upsert", "DOC-93"),
    ]


def test_index_dir_removes_stale_chunks_when_document_shrinks(tmp_path: Path) -> None:
    """RF-38: si un documento queda con menos fragmentos, los antiguos desaparecen."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    indexer = _indexer(store=store)
    indexer.index_dir(root)
    before = [c for c in store.chunks.values() if c.document_id == "DOC-91"]
    _write_md(
        root / "politicas" / "DOC-91-reglamento-ficticio.md",
        "# Reglamento ficticio\n\nVersión reducida y ficticia.",
        id="DOC-91",
        title="Reglamento ficticio de préstamo",
        category="politicas",
    )
    indexer.index_dir(root)
    after = [c for c in store.chunks.values() if c.document_id == "DOC-91"]
    assert len(before) > 1
    assert len(after) == 1
    assert after[0].content == "# Reglamento ficticio\n\nVersión reducida y ficticia."


def test_index_dir_skips_readme_when_present_in_corpus(tmp_path: Path) -> None:
    """RF-07 / INDEX_FILENAMES: el README.md del corpus no se indexa."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    _indexer(store=store).index_dir(root)
    assert all("README" not in c.metadata["source_path"] for c in store.chunks.values())
    assert all("Índice ficticio" not in c.content for c in store.chunks.values())
    assert {c.document_id for c in store.chunks.values()} == {"DOC-91", "DOC-92", "DOC-93"}


def test_index_dir_embeds_one_text_per_chunk_when_indexed(tmp_path: Path) -> None:
    """T-16: se vectoriza exactamente un texto (con título/sección) por fragmento."""
    root = _synthetic_corpus(tmp_path / "corpus")
    embeddings = RecordingEmbeddings(dimensions=DIMENSIONS)
    store = FakeVectorStore()
    report = _indexer(embeddings=embeddings, store=store).index_dir(root)
    assert len(embeddings.texts) == report.chunks == len(store.chunks)
    assert sorted(embeddings.texts) == sorted(embedding_text(c) for c in store.chunks.values())


def test_index_dir_returns_empty_report_when_directory_empty(tmp_path: Path) -> None:
    """Límite: un directorio sin documentos admitidos da un informe vacío y no escribe."""
    (tmp_path / "vacio").mkdir()
    (tmp_path / "vacio" / "README.md").write_text("# Solo índice", encoding="utf-8")
    store = SpyVectorStore()
    report = _indexer(store=store).index_dir(tmp_path / "vacio")
    assert report == IndexReport(documents=0, chunks=0, by_category={})
    assert store.calls == []


def test_index_dir_skips_document_when_chunker_returns_nothing(tmp_path: Path) -> None:
    """Límite: un documento sin fragmentos no se cuenta, pero se borran los que tuviera (RF-38)."""
    root = _synthetic_corpus(tmp_path / "corpus")
    store = SpyVectorStore()
    indexer = CorpusIndexer(
        Ingestor(FakeLLMProvider(), extractor=ReadFileExtractor()),
        lambda doc: [] if doc.id == "DOC-92" else chunk_document(doc, 40, 5),
        FakeEmbeddingProvider(dimensions=DIMENSIONS),
        store,
    )
    report = indexer.index_dir(root)
    assert report.documents == 2
    assert report.by_category == {"politicas": 2}
    assert [call for call in store.calls if call[1] == "DOC-92"] == [("delete", "DOC-92")]


# --- Corpus real con fakes (T-16) ------------------------------------------------------------


def test_index_dir_indexes_whole_seed_corpus_when_using_fakes() -> None:
    """T-16 / T-49: el corpus piloto se indexa entero (28 documentos, 7 categorías) sin rutas
    absolutas en la metadata."""
    store = FakeVectorStore()
    report = _indexer(store=store, chunk_tokens=650, overlap_tokens=80).index_dir(CORPUS)
    assert report.documents == 28
    assert set(report.by_category) == set(CATEGORIES)
    assert report.by_category == {
        "documentacion": 13,
        "glosarios": 2,
        "historias": 2,
        "politicas": 4,
        "procesos": 3,
        "productos": 2,
        "pruebas": 2,
    }
    assert sum(report.by_category.values()) == 28
    assert report.chunks == len(store.chunks)
    assert {c.document_id for c in store.chunks.values()} == {f"DOC-{n:02d}" for n in range(1, 29)}
    for chunk in store.chunks.values():
        source = chunk.metadata["source_path"]
        assert not Path(source).is_absolute()
        assert str(ROOT.as_posix()) not in source
        assert source.startswith(f"{chunk.metadata['category']}/DOC-")
        assert chunk.metadata["source"] == source


# --- CLI (main) con fábricas sustituidas -----------------------------------------------------


@pytest.fixture
def fake_config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    """AppConfig real (models.yaml) sin `.env` ni claves."""
    return AppConfig(Settings(_env_file=None), load_models_config())


def test_indexing_main_prints_spanish_summary_and_returns_zero_when_fakes(
    tmp_path: Path,
    fake_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T-16: la CLI indexa la carpeta indicada e imprime un resumen en español."""
    import core.config
    import core.factories
    import core.rag.indexing as indexing

    root = _synthetic_corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    monkeypatch.setattr(core.config, "build_config", lambda: fake_config)
    monkeypatch.setattr(core.factories, "build_llm_provider", lambda _c: FakeLLMProvider())
    monkeypatch.setattr(
        core.factories, "build_embeddings", lambda _c: FakeEmbeddingProvider(dimensions=8)
    )
    monkeypatch.setattr(core.factories, "build_vector_store", lambda _c: store)
    monkeypatch.setattr(
        indexing, "Ingestor", lambda llm: Ingestor(llm, extractor=ReadFileExtractor())
    )

    assert indexing.main([str(root)]) == 0

    out = capsys.readouterr().out
    assert out.startswith("Indexados 3 documentos y ")
    assert f"{len(store.chunks)} fragmentos" in out
    assert "(glosarios: 1, politicas: 2)" in out
    assert all(len(c.embedding or []) == 8 for c in store.chunks.values())


def test_eval_main_prints_spanish_report_and_returns_zero_when_fakes(
    fake_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T-17 / RNF-14: la CLI de evaluación usa las fábricas y escribe el informe en español."""
    import core.config
    import core.factories
    from eval import retrieval_eval

    embeddings = FakeEmbeddingProvider(dimensions=DIMENSIONS)
    store = FakeVectorStore()
    _indexer(embeddings=embeddings, store=store, chunk_tokens=650, overlap_tokens=80).index_dir(
        CORPUS
    )
    monkeypatch.setattr(core.config, "build_config", lambda: fake_config)
    monkeypatch.setattr(core.factories, "build_embeddings", lambda _c: embeddings)
    monkeypatch.setattr(core.factories, "build_vector_store", lambda _c: store)

    assert retrieval_eval.main(["3"]) == 0

    out = capsys.readouterr().out
    questions = retrieval_eval.load_questions()
    assert out.startswith("# Evaluación de la recuperación")
    assert "- k: 3" in out
    assert "Recall@3:" in out
    assert "MRR:" in out
    assert f"- Preguntas: {len(questions)}" in out
    assert "## Detalle por pregunta" in out


def test_eval_main_uses_default_k_when_no_arguments(
    fake_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T-17: sin argumentos se evalúa con k = 6."""
    import core.config
    import core.factories
    from eval import retrieval_eval

    monkeypatch.setattr(core.config, "build_config", lambda: fake_config)
    monkeypatch.setattr(
        core.factories, "build_embeddings", lambda _c: FakeEmbeddingProvider(dimensions=8)
    )
    monkeypatch.setattr(core.factories, "build_vector_store", lambda _c: FakeVectorStore())

    assert retrieval_eval.main([]) == 0
    out = capsys.readouterr().out
    assert "- k: 6" in out
    assert "Recall@6: 0.00" in out  # store vacío: no se recupera nada


@pytest.mark.parametrize("arg", ["abc", "0", "-3"])
def test_eval_main_rejects_invalid_k(arg: str, capsys: pytest.CaptureFixture[str]) -> None:
    from eval import retrieval_eval

    assert retrieval_eval.main([arg]) == 2
    assert "entero positivo" in capsys.readouterr().err
