"""Selector de modelo de la sesión (RF-42; `docs/specs/UI.md` §2).

«Modelo automático» deja la cadena de `config/models.yaml`. Elegir un modelo lo pone primero
en las tareas de la propuesta (generar, evolucionar y revisar la HU, y generar casos); los
respaldos de la cadena siguen detrás (`ModelRouter.models_for`).
"""

from dataclasses import dataclass

from adapters.base import TaskType
from adapters.llm.router import ModelChoice, ModelRouter
from core.config import AppConfig

AUTOMATIC = "Modelo automático"
SELECTABLE_TASKS: tuple[TaskType, ...] = (
    TaskType.GENERATE_STORY,
    TaskType.EVOLVE_STORY,
    TaskType.REVIEW_STORY,
    TaskType.GENERATE_TESTS,
)


@dataclass(frozen=True)
class ModelOption:
    label: str
    choice: ModelChoice | None  # None = automático


def model_options(config: AppConfig) -> list[ModelOption]:
    """Automático y los modelos de las cadenas de esas tareas con proveedor disponible."""
    options = [ModelOption(AUTOMATIC, None)]
    seen: set[ModelChoice] = set()
    for task in SELECTABLE_TASKS:
        for ref in config.task_chain(task, only_available=True):
            choice = ModelChoice(ref.provider, ref.model)
            if choice not in seen:
                seen.add(choice)
                options.append(ModelOption(f"{ref.provider} · {ref.model}", choice))
    return options


def apply_model(router: ModelRouter, choice: ModelChoice | None) -> None:
    """Aplica la elección a las tareas de la propuesta; `ValueError` si el proveedor falla."""
    for task in SELECTABLE_TASKS:
        if choice is None:
            router.clear_override(task)
        else:
            router.set_override(task, choice)
