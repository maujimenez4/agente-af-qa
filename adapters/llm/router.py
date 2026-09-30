"""Router de modelos por tarea (RF-41, RF-42).

Resuelve la cadena ordenada de modelos de cada tarea (principal y respaldos) a partir de datos
simples; la traducción desde `config/models.yaml` se hace en `core/factories.py`. Permite
sobrescribir el modelo de una tarea durante la sesión (selector de la UI, RF-42).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from adapters.base import LLMProvider, TaskType


@dataclass(frozen=True)
class ModelChoice:
    provider: str
    model: str


class ModelRouter:
    def __init__(
        self,
        chains: Mapping[TaskType, Sequence[ModelChoice]],
        provider_factory: Callable[[ModelChoice], LLMProvider],
        *,
        providers: Mapping[str, bool],
    ) -> None:
        self._chains = {task: list(chain) for task, chain in chains.items()}
        self._factory = provider_factory
        self._providers = dict(providers)  # nombre → disponible
        self._overrides: dict[TaskType, ModelChoice] = {}
        self._cache: dict[ModelChoice, LLMProvider] = {}

    def models_for(self, task: TaskType) -> list[ModelChoice]:
        """Cadena efectiva: el modelo elegido en la sesión (si hay) y luego la configurada."""
        candidates = [self._overrides[task]] if task in self._overrides else []
        candidates += self._chains.get(task, [])
        effective: list[ModelChoice] = []
        for choice in candidates:
            if self._providers.get(choice.provider) and choice not in effective:
                effective.append(choice)
        return effective

    def chain(self, task: TaskType) -> list[LLMProvider]:
        return [self._provider(choice) for choice in self.models_for(task)]

    def set_override(self, task: TaskType, choice: ModelChoice) -> None:
        if choice.provider not in self._providers:
            raise ValueError(f"El proveedor «{choice.provider}» no está configurado.")
        if not self._providers[choice.provider]:
            raise ValueError(
                f"El proveedor «{choice.provider}» no está disponible: falta su clave."
            )
        self._overrides[task] = choice

    def clear_override(self, task: TaskType) -> None:
        self._overrides.pop(task, None)

    def _provider(self, choice: ModelChoice) -> LLMProvider:
        if choice not in self._cache:
            self._cache[choice] = self._factory(choice)
        return self._cache[choice]
