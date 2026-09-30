"""Dobles de prueba (fakes) de cada protocolo de adapters/base.py con datos sintéticos."""

from tests.fakes.auth import FakeAuthProvider
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator
from tests.fakes.test_management import FakeTestManagement
from tests.fakes.vector_store import FakeVectorStore

__all__ = [
    "FakeAuthProvider",
    "FakeEmbeddingProvider",
    "FakeIssueTracker",
    "FakeLLMProvider",
    "FakeMemoryGenerator",
    "FakeTestManagement",
    "FakeVectorStore",
]
