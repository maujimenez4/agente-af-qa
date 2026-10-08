"""Prueba cruzada T-34 (RNF-19): el área A prueba la indexación del área B (RF-10, RF-38).

Cubre huecos de `core/rag/indexing.py` que no prueban `test_rag_indexing.py`: fallos del
`VectorStore` o de los embeddings a mitad del reindexado, número de vectores incorrecto,
documentos retirados del corpus, ids duplicados, la CLI ante carpetas inexistentes o errores
externos y el paso de `related` a la metadata. Solo fakes (sin red, PostgreSQL ni `.env`).
Los defectos confirmados van como `xfail(strict=True)`. Datos 100 % ficticios.
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from adapters.base import Chunk
from adapters.errors import AgentError, ExternalServiceError
from core.config import AppConfig, Settings, load_models_config
from core.rag.chunking import chunk_document
from core.rag.indexing import CorpusIndexer
from core.rag.ingest import Ingestor, split_front_matter
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.vector_store import FakeVectorStore
from tests.fixtures import MODELS_FIXTURE

DIMENSIONS = 8


class HeaderlessExtractor:
    """Extractor falso sin Docling: el cuerpo del archivo sin la cabecera YAML."""

    def extract(self, path: Path) -> str:
        _, body = split_front_matter(path.read_text(encoding="utf-8"))
        return body


@dataclass
class FailingUpsertStore(FakeVectorStore):
    """`FakeVectorStore` cuyo `upsert` falla cuando `fail` está activo (BD caída)."""

    fail: bool = False

    def upsert(self, chunks: list[Chunk]) -> None:
        if self.fail:
            raise ExternalServiceError("No se pudo guardar en la base ficticia.", service="db")
        super().upsert(chunks)


@dataclass
class FailingEmbeddings(FakeEmbeddingProvider):
    """Embeddings que fallan como un servicio externo caído."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ExternalServiceError("Servicio de embeddings ficticio caído.", service="embeddings")


@dataclass
class ShortEmbeddings(FakeEmbeddingProvider):
    """Embeddings que devuelven un vector menos de los pedidos."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return super().embed(texts)[:-1]


@dataclass
class CallLog(FakeVectorStore):
    calls: list[str] = field(default_factory=list)

    def delete_by_document(self, document_id: str) -> None:
        self.calls.append(f"delete:{document_id}")
        super().delete_by_document(document_id)


def _write_md(path: Path, body: str, **header: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", *(f"{k}: {v}" for k, v in header.items()), "---", "", body]
    path.write_bytes("\n".join(lines).encode("utf-8"))
    return path


def _corpus(root: Path) -> Path:
    _write_md(
        root / "politicas" / "DOC-81-normas.md",
        "# Normas ficticias\n\n## Plazos\n\nEl préstamo ficticio dura quince días.",
        id="DOC-81",
        title="Normas ficticias",
        category="politicas",
    )
    _write_md(
        root / "glosarios" / "DOC-82-glosario.md",
        "# Glosario ficticio\n\nSocio: persona ficticia inscrita en Villaficticia.",
        id="DOC-82",
        title="Glosario ficticio",
        category="glosarios",
    )
    return root


def _indexer(
    store: FakeVectorStore, embeddings: FakeEmbeddingProvider | None = None
) -> CorpusIndexer:
    return CorpusIndexer(
        Ingestor(FakeLLMProvider(), extractor=HeaderlessExtractor()),
        lambda doc: chunk_document(doc, 60, 5),
        embeddings or FakeEmbeddingProvider(dimensions=DIMENSIONS),
        store,
    )


def _doc_ids(store: FakeVectorStore) -> set[str]:
    return {c.document_id for c in store.chunks.values()}


# --------------------------------------------------------------------------- fallos a mitad


def test_index_dir_keeps_previous_chunks_when_upsert_fails_after_delete(tmp_path: Path) -> None:
    """RF-38: un reindexado fallido no pierde los fragmentos que ya había."""
    root = _corpus(tmp_path / "corpus")
    store = FailingUpsertStore()
    _indexer(store).index_dir(root)
    before = dict(store.chunks)

    store.fail = True
    with pytest.raises(ExternalServiceError):
        _indexer(store).index_dir(root)

    assert store.chunks == before


def test_index_dir_propagates_external_error_when_upsert_fails(tmp_path: Path) -> None:
    """RF-38: el fallo del VectorStore sale como ExternalServiceError (mensaje en español)."""
    store = FailingUpsertStore(fail=True)

    with pytest.raises(ExternalServiceError, match="No se pudo guardar"):
        _indexer(store).index_dir(_corpus(tmp_path / "corpus"))


def test_index_dir_deletes_nothing_when_embeddings_fail(tmp_path: Path) -> None:
    """RF-38: si fallan los embeddings no se borra nada y el error externo se propaga."""
    root = _corpus(tmp_path / "corpus")
    store = CallLog()
    _indexer(store).index_dir(root)
    before = dict(store.chunks)
    store.calls.clear()

    with pytest.raises(ExternalServiceError, match="embeddings"):
        _indexer(store, FailingEmbeddings()).index_dir(root)

    assert store.calls == []
    assert store.chunks == before


def test_index_dir_raises_agent_error_when_embeddings_return_fewer_vectors(
    tmp_path: Path,
) -> None:
    """RF-10: un proveedor de embeddings incoherente se notifica como error del agente."""
    with pytest.raises(AgentError):
        _indexer(FakeVectorStore(), ShortEmbeddings()).index_dir(_corpus(tmp_path / "corpus"))


def test_index_dir_deletes_nothing_when_embeddings_return_fewer_vectors(tmp_path: Path) -> None:
    """RF-38 (comportamiento fijado): el fallo de recuento ocurre antes de borrar."""
    root = _corpus(tmp_path / "corpus")
    store = CallLog()
    _indexer(store).index_dir(root)
    before = dict(store.chunks)
    store.calls.clear()

    with pytest.raises(ExternalServiceError, match="vectores"):  # PA-216
        _indexer(store, ShortEmbeddings()).index_dir(root)

    assert store.calls == []
    assert store.chunks == before


# --------------------------------------------------------------------------- corpus cambiante


def test_index_dir_keeps_orphan_chunks_when_document_removed_from_corpus(tmp_path: Path) -> None:
    """RF-38 (comportamiento fijado): un documento retirado del corpus no se poda del índice."""
    root = _corpus(tmp_path / "corpus")
    store = FakeVectorStore()
    _indexer(store).index_dir(root)
    (root / "glosarios" / "DOC-82-glosario.md").unlink()

    report = _indexer(store).index_dir(root)

    assert report.documents == 1
    assert _doc_ids(store) == {"DOC-81", "DOC-82"}


def test_index_dir_keeps_both_documents_when_same_name_in_different_folders(
    tmp_path: Path,
) -> None:
    """RF-10: cada archivo del corpus queda indexado (o la indexación avisa del conflicto)."""
    root = tmp_path / "corpus"
    _write_md(
        root / "politicas" / "nota.md", "# Uno\n\nContenido alfa ficticio.", category="politicas"
    )
    _write_md(
        root / "procesos" / "nota.md", "# Dos\n\nContenido beta ficticio.", category="procesos"
    )
    store = FakeVectorStore()

    try:
        _indexer(store).index_dir(root)
    except AgentError:
        return
    contents = " ".join(c.content for c in store.chunks.values())
    assert "alfa" in contents and "beta" in contents


def test_index_dir_keeps_related_as_related_and_sets_no_related_key(tmp_path: Path) -> None:
    """RF-10 (comportamiento fijado): `related` de la cabecera va a metadata["related"].

    No se rellena `related_key` (la columna `documents.related_key` queda vacía en el corpus).
    """
    root = tmp_path / "corpus"
    _write_md(
        root / "historias" / "DOC-83-hu.md",
        "# HU ficticia\n\nComo socio ficticio quiero renovar.",
        id="DOC-83",
        category="historias",
        related="[DEMO-3, DEMO-4]",
    )
    store = FakeVectorStore()

    _indexer(store).index_dir(root)

    metadata = next(iter(store.chunks.values())).metadata
    assert metadata["related"] == "DEMO-3, DEMO-4"
    assert "related_key" not in metadata


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Sustituye las fábricas de la CLI por fakes; devuelve el estado para ajustarlo."""
    import core.config
    import core.factories
    import core.rag.indexing as indexing

    state: dict[str, object] = {"store": FakeVectorStore()}
    config = AppConfig(Settings(_env_file=None), load_models_config(MODELS_FIXTURE))
    monkeypatch.setattr(core.config, "build_config", lambda: config)
    monkeypatch.setattr(core.factories, "build_llm_provider", lambda _c: FakeLLMProvider())
    monkeypatch.setattr(
        core.factories, "build_embeddings", lambda _c: FakeEmbeddingProvider(dimensions=DIMENSIONS)
    )
    monkeypatch.setattr(core.factories, "build_vector_store", lambda _c: state["store"])
    monkeypatch.setattr(
        indexing, "Ingestor", lambda llm: Ingestor(llm, extractor=HeaderlessExtractor())
    )
    return state


def test_indexing_main_returns_nonzero_when_folder_does_not_exist(
    tmp_path: Path, cli: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    """RF-10: una ruta mal escrita no puede pasar por una indexación correcta."""
    import core.rag.indexing as indexing

    code = indexing.main([str(tmp_path / "no-existe")])

    assert code != 0
    assert "no-existe" in capsys.readouterr().err


def test_indexing_main_prints_spanish_error_when_external_service_fails(
    tmp_path: Path, cli: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    """CLAUDE.md: los errores externos llegan al usuario con un mensaje en español."""
    import core.rag.indexing as indexing

    cli["store"] = FailingUpsertStore(fail=True)
    root = _corpus(tmp_path / "corpus")

    code = indexing.main([str(root)])

    assert code != 0
    assert "No se pudo guardar" in capsys.readouterr().err


def test_indexing_main_prints_spanish_error_when_config_is_invalid(
    tmp_path: Path,
    cli: dict[str, object],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PA-217: un `ConfigError` (no es `AgentError`) también sale como mensaje, sin traceback."""
    import core.config
    import core.rag.indexing as indexing

    def broken() -> None:
        raise core.config.ConfigError("Falta configurar el modelo de embeddings ficticio.")

    monkeypatch.setattr(core.config, "build_config", broken)
    code = indexing.main([str(_corpus(tmp_path / "corpus"))])

    assert code == 1
    err = capsys.readouterr().err
    assert "Falta configurar" in err and "Traceback" not in err
