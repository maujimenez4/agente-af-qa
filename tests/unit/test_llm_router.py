"""Pruebas de adapters/llm/router.py (T-10 · RF-41, RF-42, RF-44).

El router no depende de `core/` (SPEC-00 §2): se prueba con cadenas construidas a mano y
`FakeLLMProvider` como fábrica. Proveedores y modelos ficticios; sin red.
"""

import dataclasses

import pytest

from adapters.base import LLMProvider, Message, TaskType
from adapters.llm.fallback import FallbackLLMProvider
from adapters.llm.router import ModelChoice, ModelRouter
from tests.fakes.llm import FakeLLMProvider

MESSAGES = [Message(role="user", content="Clasifica este documento ficticio.")]

PRIMARY = ModelChoice(provider="alfa", model="alfa-grande")
BACKUP = ModelChoice(provider="beta", model="beta-libre")
LOCAL = ModelChoice(provider="local", model="local-ligero")

CHAINS: dict[TaskType, list[ModelChoice]] = {
    TaskType.GENERATE_STORY: [PRIMARY, BACKUP],
    TaskType.CLASSIFY_SOURCE: [LOCAL, PRIMARY],
    TaskType.SYNTHESIZE_MEMORY: [BACKUP, LOCAL],
    TaskType.NL_TO_JQL: [BACKUP, LOCAL],
}
# "beta" está declarado pero sin clave (no disponible).
PROVIDERS = {"alfa": True, "beta": False, "local": True}


class CountingFactory:
    """provider_factory falsa: crea FakeLLMProvider y registra cada creación."""

    def __init__(self) -> None:
        self.created: list[ModelChoice] = []

    def __call__(self, choice: ModelChoice) -> LLMProvider:
        self.created.append(choice)
        return FakeLLMProvider(provider=choice.provider, model=choice.model)


@pytest.fixture
def factory() -> CountingFactory:
    return CountingFactory()


@pytest.fixture
def router(factory: CountingFactory) -> ModelRouter:
    return ModelRouter(CHAINS, factory, providers=PROVIDERS)


def _ids(chain: list[LLMProvider]) -> list[tuple[str, str]]:
    return [(p.provider, p.model) for p in chain]  # type: ignore[attr-defined]


# --- ModelChoice ---------------------------------------------------------------------------


def test_model_choice_is_immutable_and_hashable() -> None:
    """RF-41: ModelChoice es un valor inmutable, usable como clave de caché."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        PRIMARY.model = "otro"  # type: ignore[misc]
    assert {PRIMARY: 1}[ModelChoice(provider="alfa", model="alfa-grande")] == 1


# --- models_for (RF-41) --------------------------------------------------------------------


def test_models_for_filters_unavailable_providers(router: ModelRouter) -> None:
    """RF-41 · RF-44: la cadena efectiva excluye los proveedores no disponibles."""
    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY]


def test_models_for_keeps_configured_order(router: ModelRouter) -> None:
    """RF-41: el orden de la cadena (principal y respaldos) se conserva."""
    assert router.models_for(TaskType.CLASSIFY_SOURCE) == [LOCAL, PRIMARY]


def test_models_for_is_empty_when_task_has_no_chain(router: ModelRouter) -> None:
    """RF-41 (límite): una tarea sin cadena devuelve una lista vacía."""
    assert router.models_for(TaskType.REVIEW_STORY) == []


def test_models_for_is_empty_when_no_provider_available(factory: CountingFactory) -> None:
    """RF-44 (límite): si ningún proveedor está disponible, la cadena queda vacía."""
    router = ModelRouter(CHAINS, factory, providers={"alfa": False, "beta": False})
    assert router.models_for(TaskType.GENERATE_STORY) == []


def test_models_for_excludes_provider_missing_from_providers(factory: CountingFactory) -> None:
    """RF-44 (límite): un proveedor que no figura en `providers` se trata como no disponible."""
    router = ModelRouter(CHAINS, factory, providers={"alfa": True})
    assert router.models_for(TaskType.CLASSIFY_SOURCE) == [PRIMARY]


def test_models_for_removes_duplicates_in_chain(factory: CountingFactory) -> None:
    """RF-41 (límite): una cadena con modelos repetidos no los duplica."""
    router = ModelRouter(
        {TaskType.GENERATE_STORY: [PRIMARY, LOCAL, PRIMARY]}, factory, providers=PROVIDERS
    )
    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY, LOCAL]


# --- Override (RF-42) ----------------------------------------------------------------------


def test_set_override_puts_chosen_model_first(router: ModelRouter) -> None:
    """RF-42: el modelo elegido en la UI es el principal y el resto queda de respaldo."""
    chosen = ModelChoice(provider="alfa", model="alfa-elegido")

    router.set_override(TaskType.GENERATE_STORY, chosen)

    assert router.models_for(TaskType.GENERATE_STORY) == [chosen, PRIMARY]


def test_set_override_does_not_duplicate_when_choice_in_chain(router: ModelRouter) -> None:
    """RF-42 (límite): si el elegido ya está en la cadena, pasa al principio sin duplicarse."""
    router.set_override(TaskType.CLASSIFY_SOURCE, PRIMARY)

    assert router.models_for(TaskType.CLASSIFY_SOURCE) == [PRIMARY, LOCAL]


def test_set_override_works_when_task_has_no_chain(router: ModelRouter) -> None:
    """RF-42: se puede elegir modelo para una tarea sin cadena configurada."""
    router.set_override(TaskType.REVIEW_STORY, LOCAL)

    assert router.models_for(TaskType.REVIEW_STORY) == [LOCAL]


def test_set_override_only_affects_its_task(router: ModelRouter) -> None:
    """RF-42: el override de una tarea no cambia las demás."""
    router.set_override(TaskType.GENERATE_STORY, LOCAL)

    assert router.models_for(TaskType.CLASSIFY_SOURCE) == [LOCAL, PRIMARY]


def test_set_override_replaces_previous_override(router: ModelRouter) -> None:
    """RF-42: un segundo override sustituye al primero."""
    router.set_override(TaskType.GENERATE_STORY, LOCAL)
    other = ModelChoice(provider="alfa", model="alfa-otro")

    router.set_override(TaskType.GENERATE_STORY, other)

    assert router.models_for(TaskType.GENERATE_STORY) == [other, PRIMARY]


def test_clear_override_restores_configured_chain(router: ModelRouter) -> None:
    """RF-42: al quitar el override vuelve la cadena configurada."""
    router.set_override(TaskType.GENERATE_STORY, LOCAL)

    router.clear_override(TaskType.GENERATE_STORY)

    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY]


def test_clear_override_does_nothing_when_no_override(router: ModelRouter) -> None:
    """RF-42 (límite): quitar un override inexistente no falla."""
    router.clear_override(TaskType.GENERATE_STORY)

    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY]


def test_set_override_raises_value_error_when_provider_unknown(router: ModelRouter) -> None:
    """RF-42 (error): un proveedor no declarado se rechaza con ValueError y mensaje útil."""
    with pytest.raises(ValueError, match="inexistente"):
        router.set_override(TaskType.GENERATE_STORY, ModelChoice(provider="inexistente", model="x"))

    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY]


def test_set_override_raises_value_error_when_provider_unavailable(router: ModelRouter) -> None:
    """RF-42 (error): un proveedor declarado pero no disponible se rechaza con ValueError."""
    with pytest.raises(ValueError, match="beta"):
        router.set_override(TaskType.GENERATE_STORY, BACKUP)

    assert router.models_for(TaskType.GENERATE_STORY) == [PRIMARY]


# --- chain (RF-44) -------------------------------------------------------------------------


def test_chain_builds_one_provider_per_choice_in_order(router: ModelRouter) -> None:
    """RF-44: la cadena de proveedores sigue el orden de models_for."""
    chain = router.chain(TaskType.CLASSIFY_SOURCE)

    assert _ids(chain) == [(LOCAL.provider, LOCAL.model), (PRIMARY.provider, PRIMARY.model)]


def test_chain_returns_cached_providers_when_called_twice(
    router: ModelRouter, factory: CountingFactory
) -> None:
    """RF-44: los proveedores se cachean por ModelChoice: mismos objetos en cada llamada."""
    first = router.chain(TaskType.CLASSIFY_SOURCE)
    second = router.chain(TaskType.CLASSIFY_SOURCE)

    assert all(a is b for a, b in zip(first, second, strict=True))
    assert factory.created == [LOCAL, PRIMARY]


def test_chain_shares_provider_between_tasks_with_same_choice(
    router: ModelRouter, factory: CountingFactory
) -> None:
    """RF-44: la caché es por ModelChoice, también entre tareas distintas."""
    memory = router.chain(TaskType.SYNTHESIZE_MEMORY)
    jql = router.chain(TaskType.NL_TO_JQL)

    assert len(memory) == len(jql) == 1
    assert memory[0] is jql[0]
    assert factory.created == [LOCAL]


def test_chain_is_empty_without_creating_providers_when_no_models(
    router: ModelRouter, factory: CountingFactory
) -> None:
    """RF-44 (límite): sin modelos disponibles no se crea ningún proveedor."""
    assert router.chain(TaskType.REVIEW_STORY) == []
    assert factory.created == []


def test_chain_follows_override(router: ModelRouter) -> None:
    """RF-42 · RF-44: el override se refleja en la cadena de proveedores."""
    router.set_override(TaskType.GENERATE_STORY, LOCAL)

    assert _ids(router.chain(TaskType.GENERATE_STORY))[0] == (LOCAL.provider, LOCAL.model)


def test_fallback_over_router_uses_override_provider(router: ModelRouter) -> None:
    """RF-42 · RF-44: con el router como fuente de cadenas responde el modelo elegido."""
    router.set_override(TaskType.CLASSIFY_SOURCE, PRIMARY)

    result = FallbackLLMProvider(router.chain).generate(MESSAGES, TaskType.CLASSIFY_SOURCE)

    assert (result.provider, result.model) == (PRIMARY.provider, PRIMARY.model)
