"""Contenedor con todos los fakes, compuesto mediante core/container.py."""

from pathlib import Path

from adapters.base import Chunk
from core.container import Container, build_container
from tests.fakes import dataset
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore


def fake_container(memory_dir: Path, **overrides: object) -> Container:
    """Fakes coherentes entre sí, con los documentos del dataset ya indexados."""
    embeddings = FakeEmbeddingProvider()
    vector_store = FakeVectorStore()
    for document_id, doc in dataset.DOCUMENTS.items():
        (vector,) = embeddings.embed([doc["content"]])
        vector_store.upsert(
            [
                Chunk(
                    id=f"{document_id}-0",
                    document_id=document_id,
                    ordinal=0,
                    section=doc["title"],
                    content=doc["content"],
                    embedding=vector,
                    metadata={"category": doc["category"]},
                )
            ]
        )
    dependencies: dict[str, object] = {
        "issue_tracker": FakeIssueTracker(),
        "test_management": FakeTestManagement(),
        "llm": FakeLLMProvider(),
        "embeddings": embeddings,
        "vector_store": vector_store,
        "memory_generator": FakeMemoryGenerator(),
        "auth": FakeAuthProvider(),
        **overrides,
    }
    # El «Jira» de los fakes es de mentira: las pruebas publican en modo real para comprobarlo.
    dependencies.setdefault("publish_mode", "live")
    return build_container(memory_dir=memory_dir, **dependencies)  # type: ignore[arg-type]
