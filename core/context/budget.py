"""Presupuesto de tokens del contexto (T-18, PA-07): prioriza y recorta lo que se envía al LLM.

La guarda de la ventana (PA-114) comprueba el mensaje completo antes de llamar al LLM: recorta
las fuentes de menos prioridad y, si ni así cabe, falla con un error claro en lugar de dejar
que Ollama descarte en silencio el principio del prompt.
"""

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from adapters.base import IssueDetail, Message, RetrievedChunk, TaskType
from adapters.errors import AgentError
from core.logging import get_logger

if TYPE_CHECKING:
    from core.config import AppConfig, LimitsConfig, ModelsConfig

ProvidersFor = Callable[[TaskType], Sequence[str]]

# PA-114: en español, qwen3 mide ~3,2 caracteres por token (3,02 en el JSON de una HU); con 4
# el contexto «de 4108 tokens» ocupaba ~5500 reales y Ollama truncaba en silencio.
CHARS_PER_TOKEN = 3
TRUNCATION_MARK = " […]"
# Margen por la serialización JSON (nombres de campos, estado, tipo, fuente…).
ISSUE_OVERHEAD_TOKENS = 30
CHUNK_OVERHEAD_TOKENS = 20


def estimate_tokens(text: str) -> int:
    """Estimación barata y algo conservadora (3 caracteres por token, PA-114)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def issue_tokens(issue: IssueDetail) -> int:
    """Tokens que ocupa la incidencia tal como se envía al LLM (texto + relaciones + margen)."""
    parts = [issue.key, issue.summary, issue.description_text, *issue.comments]
    related = [f"{s.key} {s.summary}" for s in issue.subtasks]
    related += [f"{link.link_type} {link.key}" for link in issue.links]
    related += issue.labels
    return (
        estimate_tokens(" ".join(parts))
        + estimate_tokens(" ".join(related))
        + (ISSUE_OVERHEAD_TOKENS)
    )


def chunk_tokens(chunk: RetrievedChunk) -> int:
    return estimate_tokens(chunk.chunk.content) + CHUNK_OVERHEAD_TOKENS


def truncate_issue(issue: IssueDetail, max_tokens: int) -> IssueDetail:
    """Recorta la incidencia para que quepa en `max_tokens`.

    Se quitan los comentarios; vínculos, subtareas y etiquetas se conservan mientras quepan
    (PA-165: una HU con cientos de subtareas de casos de prueba, D-09, no rompe el presupuesto)
    y la descripción ocupa el resto. Clave y resumen siempre se conservan. Se cuenta de forma
    incremental, con la misma medida que `issue_tokens`, en tiempo lineal (revisión de
    seguridad: sin coste cuadrático con miles de elementos).
    """
    # «clave resumen descripción» con la descripción vacía: dos separadores.
    parts_chars = len(issue.key) + 1 + len(issue.summary) + 1
    related_chars = 0
    count = 0
    kept: dict[str, list[object]] = {"links": [], "subtasks": [], "labels": []}
    # Si hay descripción, se reserva sitio para la marca de recorte: sigue viéndose que se
    # recortó y no se supera el máximo por ella.
    reserve = (
        math.ceil((len(TRUNCATION_MARK) + 1) / CHARS_PER_TOKEN) if issue.description_text else 0
    )
    texts = {
        "links": lambda link: f"{link.link_type} {link.key}",
        "subtasks": lambda sub: f"{sub.key} {sub.summary}",
        "labels": lambda label: label,
    }
    for name in ("links", "subtasks", "labels"):
        for item in getattr(issue, name):
            extra = len(texts[name](item)) + (1 if count else 0)
            cost = (
                math.ceil(parts_chars / CHARS_PER_TOKEN)
                + math.ceil((related_chars + extra) / CHARS_PER_TOKEN)
                + ISSUE_OVERHEAD_TOKENS
            )
            if cost > max_tokens - reserve:
                break
            kept[name].append(item)
            related_chars += extra
            count += 1
    current = issue.model_copy(
        update={"description_text": "", "comments": [], **kept}  # type: ignore[arg-type]
    )
    fixed = issue_tokens(current)
    room_chars = max(0, (max_tokens - fixed) * CHARS_PER_TOKEN - 1)
    description = issue.description_text
    if len(description) > room_chars:
        description = description[: max(0, room_chars - len(TRUNCATION_MARK))] + TRUNCATION_MARK
    return current.model_copy(update={"description_text": description})


class BudgetReport(BaseModel):
    budget: int
    used: int
    dropped_issues: int = 0
    dropped_chunks: int = 0
    truncated_issues: int = 0


def apply_budget(
    issues: Sequence[IssueDetail],
    chunks: Sequence[RetrievedChunk],
    budget: int,
    jira_share: float = 0.5,
    *,
    has_origin: bool = True,
) -> tuple[list[IssueDetail], list[RetrievedChunk], BudgetReport]:
    """Selecciona el contexto por prioridad sin superar `budget` tokens.

    - `issues` llega ordenado por prioridad; la primera (el origen) entra siempre y **entera**
      (PA-442): nunca se recorta en silencio; si no cabe en la ventana del modelo, la guarda de
      PA-114 da el error «no cabe». El resto se recorta o se descarta según quede sitio.
    - `chunks` llega ordenado por prioridad (memorias primero); se descartan los que no caben.
    - Jira puede usar hasta `jira_share` del presupuesto; lo que no use pasa al RAG.
    - `has_origin=False` (una necesidad, PA-167): no hay origen; todas son secundarias.
    """
    report = BudgetReport(budget=budget, used=0)
    jira_cap = int(budget * jira_share)
    selected_issues: list[IssueDetail] = []
    used = 0
    for position, issue in enumerate(issues):
        cost = issue_tokens(issue)
        if has_origin and position == 0:  # PA-442: el origen, siempre y entero
            selected_issues.append(issue)
            used += cost
            continue
        room = jira_cap - used
        if cost <= room:
            selected_issues.append(issue)
            used += cost
            continue
        if room >= 60:  # una fuente opcional, recortada si cabe algo útil
            trimmed = truncate_issue(issue, room)
            if issue_tokens(trimmed) <= room:
                selected_issues.append(trimmed)
                used += issue_tokens(trimmed)
                report.truncated_issues += 1
                continue
        report.dropped_issues += 1

    selected_chunks: list[RetrievedChunk] = []
    for chunk in chunks:
        cost = chunk_tokens(chunk)
        if used + cost <= budget:
            selected_chunks.append(chunk)
            used += cost
        else:
            report.dropped_chunks += 1
    report.used = used
    return selected_issues, selected_chunks, report


# --- Guarda de la ventana de contexto (PA-114) -----------------------------------------------

# Margen sobre la estimación: plantilla de chat, separadores y la deriva de `/3` en textos densos.
SAFETY_TOKENS = 256
MESSAGE_OVERHEAD_TOKENS = 4  # rol y separadores de cada mensaje
DEFAULT_CONTEXT_WINDOW = 8192
FALLBACK_OUTPUT_TOKENS = 2500  # el mayor tope de salida de `config/models.yaml`

log = get_logger(__name__)


class ContextOverflowError(AgentError):
    """El prompt no cabe en la ventana del modelo ni recortando el contexto (PA-114)."""


@dataclass(frozen=True)
class PromptLimits:
    """Ventana del modelo y tope de salida por tarea (`limits` de `config/models.yaml`).

    PA-443: con `models`, cada proveedor puede tener sus límites, y lo que cabe en una tarea es lo
    más restrictivo de su cadena **efectiva** (`providers_for`, la del router: incluye el modelo
    elegido en la UI, RF-42), para que el prompt quepa también si se pasa al respaldo.
    """

    context_window: int = DEFAULT_CONTEXT_WINDOW
    max_output_tokens: Mapping[TaskType, int] = field(default_factory=dict)
    default_output_tokens: int = 0  # reserva para las tareas sin tope configurado
    models: "ModelsConfig | None" = None
    providers_for: ProvidersFor | None = None

    def available(self, task: TaskType) -> int:
        """Tokens de entrada que caben: ventana − tope de salida de la tarea − margen."""
        if self.models is not None and (names := self._providers(self.models, task)):
            room = min(_room(self.models.limits_for(name), task) for name in names)
            return room - SAFETY_TOKENS
        output = self.max_output_tokens.get(task, self.default_output_tokens)
        return self.context_window - output - SAFETY_TOKENS

    def window(self, task: TaskType) -> int:
        """Ventana del modelo que limita la tarea (el de menos sitio de su cadena), para el
        mensaje de «no cabe»."""
        if self.models is not None and (names := self._providers(self.models, task)):
            models = self.models
            tightest = min(names, key=lambda name: _room(models.limits_for(name), task))
            return models.limits_for(tightest).context_window
        return self.context_window

    def _providers(self, models: "ModelsConfig", task: TaskType) -> list[str]:
        names: list[str] = []
        if self.providers_for is not None:
            try:
                names = list(self.providers_for(task))
            except Exception as exc:  # sin la cadena efectiva, la configurada
                log.warning("cadena sin leer", action="context_limits", error=type(exc).__name__)
        return names or models.task_providers(task)

    @classmethod
    def from_config(
        cls, config: "AppConfig", providers_for: ProvidersFor | None = None
    ) -> "PromptLimits":
        limits = config.models.limits
        return cls(
            limits.context_window,
            dict(limits.max_output_tokens),
            models=config.models,
            providers_for=providers_for,
        )


def _room(limits: "LimitsConfig", task: TaskType) -> int:
    return limits.context_window - limits.max_output_tokens.get(task, 0)


def providers_of(llm: object) -> ProvidersFor | None:
    """PA-443: la cadena efectiva de proveedores del LLM del contenedor (`FallbackLLMProvider`
    la expone; las capas que lo envuelven la reenvían). `None` si no la tiene (dobles de prueba)."""
    resolver = getattr(llm, "chain_providers", None)
    return resolver if callable(resolver) else None


def default_prompt_limits() -> PromptLimits:
    """Límites de la configuración de la aplicación; sin configuración, los valores por defecto.

    Los escritores que no reciben `limits` (los crea el grafo solo con el LLM) usan estos
    (PA-228 propone que el grafo los pase desde el contenedor).
    """
    from core.config import ConfigError, get_config

    try:
        return PromptLimits.from_config(get_config())
    except (ConfigError, ValueError, OSError) as exc:
        # Sin el mensaje de la excepción (podría citar valores de `.env`); con una reserva de
        # salida conservadora para que la guarda no sea más permisiva que con la configuración.
        log.warning(
            "sin configuración para la ventana de contexto; valores por defecto",
            action="context_limits",
            error=type(exc).__name__,
        )
        return PromptLimits(default_output_tokens=FALLBACK_OUTPUT_TOKENS)


def estimate_messages(messages: Sequence[Message]) -> int:
    """Tokens del mensaje completo: todo lo que se envía (instrucciones, contexto, HU previa,
    feedback y, en un reintento, la respuesta anterior y la corrección)."""
    return sum(estimate_tokens(m.content) + MESSAGE_OVERHEAD_TOKENS for m in messages)


@dataclass(frozen=True)
class FitReport:
    """Qué hizo la guarda; solo recuentos, nunca contenido."""

    estimated: int
    available: int
    dropped_rag: int = 0
    dropped_jira: int = 0


def fit_messages(
    build: Callable[[int, int], list[Message]],
    n_rag: int,
    n_related: int,
    limits: PromptLimits,
    task: TaskType,
    *,
    action: str,
) -> tuple[list[Message], FitReport]:
    """Mensajes que caben en la ventana, recortando solo fuentes de baja prioridad.

    `build(rag, related)` construye los mensajes con los `rag` primeros fragmentos del RAG y las
    `related` primeras HU relacionadas; lo demás (instrucciones, origen, HU previa, feedback)
    lo pone siempre. Se quitan primero los últimos fragmentos y después las últimas HU
    relacionadas. Si ni sin ellos cabe, `ContextOverflowError`: nunca un truncado silencioso.
    """
    available = limits.available(task)
    rag, related = n_rag, n_related
    messages = build(rag, related)
    estimated = estimate_messages(messages)
    while estimated > available and (rag or related):
        if rag:
            rag -= 1
        else:
            related -= 1
        messages = build(rag, related)
        estimated = estimate_messages(messages)
    report = FitReport(estimated, available, n_rag - rag, n_related - related)
    if report.dropped_rag or report.dropped_jira:
        log.info(
            "contexto recortado para caber en la ventana",
            action=action,
            task=task.value,
            dropped_rag=report.dropped_rag,
            dropped_jira=report.dropped_jira,
            estimated_tokens=estimated,
            available_tokens=available,
        )
    if estimated > available:
        log.warning(
            "el prompt no cabe en la ventana",
            action=action,
            task=task.value,
            estimated_tokens=estimated,
            available_tokens=available,
        )
        raise ContextOverflowError(
            f"La petición no cabe en la ventana del modelo ({limits.window(task)} tokens): "
            f"ocupa unos {estimated} y caben {available} con el tope de salida de la tarea, "
            "incluso sin fuentes opcionales. Acorta la HU o el feedback, o usa un modelo con "
            "más contexto."
        )
    return messages, report


def check_messages(
    messages: list[Message], limits: PromptLimits, task: TaskType, *, action: str
) -> list[Message]:
    """Guarda sin recorte (memoria, impacto): error claro si no cabe (PA-114)."""
    fitted, _ = fit_messages(lambda _r, _j: messages, 0, 0, limits, task, action=action)
    return fitted
