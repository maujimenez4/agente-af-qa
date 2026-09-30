"""Cada fake de tests/fakes cumple su protocolo de adapters/base.py (CA-00-03)."""

import inspect
from typing import Any

import pytest

from adapters import base
from tests.fakes import (
    FakeAuthProvider,
    FakeEmbeddingProvider,
    FakeIssueTracker,
    FakeLLMProvider,
    FakeMemoryGenerator,
    FakeTestManagement,
    FakeVectorStore,
)

PAIRS: list[tuple[type[Any], type[Any]]] = [
    (base.IssueTracker, FakeIssueTracker),
    (base.TestManagement, FakeTestManagement),
    (base.LLMProvider, FakeLLMProvider),
    (base.EmbeddingProvider, FakeEmbeddingProvider),
    (base.VectorStore, FakeVectorStore),
    (base.AuthProvider, FakeAuthProvider),
    (base.MemoryGenerator, FakeMemoryGenerator),
]
IDS = [protocol.__name__ for protocol, _ in PAIRS]


def _protocol_methods(protocol: type[Any]) -> list[str]:
    return [
        name
        for name, value in vars(protocol).items()
        if callable(value) and not name.startswith("_")
    ]


def _param_shape(func: Any) -> list[tuple[str, Any, Any]]:
    return [(p.name, p.kind, p.default) for p in inspect.signature(func).parameters.values()]


def test_all_seven_protocols_are_covered_by_a_fake() -> None:
    """CA-00-03: los 7 protocolos de adapters/base.py tienen un fake."""
    declared = {
        obj
        for obj in vars(base).values()
        if isinstance(obj, type)
        and getattr(obj, "_is_protocol", False)
        and obj is not base.Protocol
    }
    assert declared == {protocol for protocol, _ in PAIRS}


@pytest.mark.parametrize(("protocol", "fake_cls"), PAIRS, ids=IDS)
def test_fake_is_instance_of_protocol_when_runtime_checked(
    protocol: type[Any], fake_cls: type[Any]
) -> None:
    """CA-00-03: isinstance del fake contra el Protocol @runtime_checkable."""
    assert isinstance(fake_cls(), protocol)


@pytest.mark.parametrize(("protocol", "fake_cls"), PAIRS, ids=IDS)
def test_fake_method_signatures_match_protocol(protocol: type[Any], fake_cls: type[Any]) -> None:
    """CA-00-03: nombres, tipo de parámetro y valores por defecto iguales a los del Protocol."""
    methods = _protocol_methods(protocol)
    assert methods, f"{protocol.__name__} no declara métodos"
    for name in methods:
        assert hasattr(fake_cls, name), f"{fake_cls.__name__} no implementa {name}"
        assert _param_shape(getattr(fake_cls, name)) == _param_shape(getattr(protocol, name)), (
            f"{fake_cls.__name__}.{name} difiere de {protocol.__name__}.{name}"
        )


def test_embedding_fake_declares_protocol_attributes() -> None:
    """CA-00-03: EmbeddingProvider exige los atributos model_name y dimensions."""
    fake = FakeEmbeddingProvider()
    for attribute in base.EmbeddingProvider.__annotations__:
        assert hasattr(fake, attribute)
    assert isinstance(fake.model_name, str)
    assert isinstance(fake.dimensions, int)


@pytest.mark.parametrize(("protocol", "fake_cls"), PAIRS, ids=IDS)
def test_unrelated_object_is_not_instance_of_protocol(
    protocol: type[Any], fake_cls: type[Any]
) -> None:
    """CA-00-03 (negativa): un objeto sin los métodos no satisface el protocolo."""
    assert not isinstance(object(), protocol)
