"""Configuración de la aplicación: secretos desde `.env` y modelos desde `config/models.yaml`.

Es el único punto de lectura de configuración (CLAUDE.md, principio 2). Los secretos se
guardan como `SecretStr` y los valores de ejemplo (`TU_*`) se tratan como ausentes, de modo
que la aplicación arranca aunque no haya ninguna clave configurada.
"""

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

from adapters.base import TaskType

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODELS_PATH = ROOT_DIR / "config" / "models.yaml"
# Origen explícito para la API (T-55): esquema, host sin comodines y puerto opcional.
_ORIGIN = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")

_PLACEHOLDER = re.compile(r"^TU_[A-ZÑÁÉÍÓÚ0-9_]+$")


def is_placeholder(value: str | None) -> bool:
    """Indica si un valor está vacío o es un placeholder de `.env.example` (`TU_*`)."""
    return value is None or not value.strip() or bool(_PLACEHOLDER.match(value.strip()))


class ConfigError(Exception):
    """Configuración inválida; el mensaje está en español para mostrarlo en la UI."""


# --- config/models.yaml ------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderConfig(_StrictModel):
    type: Literal["openai_compatible"]
    base_url: str = Field(min_length=1)
    # Nombre de la variable de entorno, nunca la clave (evita mostrar una clave pegada por error).
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")


class ModelOptions(_StrictModel):
    """Opciones de petición por modelo, enviadas tal cual en el cuerpo (T-58).

    Sirven para desactivar el razonamiento de los modelos que lo traen activado. Solo se admiten
    estas claves:
    - `reasoning_effort: "none"`: **la que funciona con el endpoint OpenAI de Ollama** (el que usa
      la app); medido con `qwen3:1.7b` el 2026-10-02.
    - `think: false`: la opción de la API nativa de Ollama; por el endpoint OpenAI **no tiene
      efecto** (el modelo sigue razonando). Se conserva por si cambia el proveedor.
    """

    think: bool | None = None
    reasoning_effort: Literal["none", "low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if self.think is None and self.reasoning_effort is None:
            raise ValueError("options necesita al menos 'think' o 'reasoning_effort'")
        return self

    def request_body(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class ModelRef(_StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    options: ModelOptions | None = None


class EmbeddingsConfig(_StrictModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    dimensions: PositiveInt


class LimitsConfig(_StrictModel):
    max_retries_on_429: NonNegativeInt
    context_token_budget: PositiveInt
    # PA-114: ventana de contexto del modelo, en tokens: prompt + contexto + tope de salida de la
    # tarea no pueden superarla (Ollama trunca en silencio el principio si se desborda).
    context_window: PositiveInt = 8192
    daily_token_warning: PositiveInt
    # Segundos por llamada al LLM: un modelo local en CPU tarda más que uno en la nube.
    request_timeout_s: PositiveFloat = 60.0
    # Tope de tokens de salida por tarea; sin entrada, sin tope. Acorta la generación y deja sitio
    # al reintento dentro de la ventana de contexto.
    max_output_tokens: dict[TaskType, PositiveInt] = {}


class RagConfig(_StrictModel):
    chunk_tokens: PositiveInt
    overlap_tokens: NonNegativeInt
    top_k: PositiveInt
    memory_boost: PositiveFloat

    @model_validator(mode="after")
    def _overlap_smaller_than_chunk(self) -> Self:
        if self.overlap_tokens >= self.chunk_tokens:
            raise ValueError("rag.overlap_tokens debe ser menor que rag.chunk_tokens")
        return self


class ModelsConfig(_StrictModel):
    """Estructura de `config/models.yaml`: cada tarea es una cadena ordenada de modelos."""

    providers: dict[str, ProviderConfig] = Field(min_length=1)
    tasks: dict[TaskType, list[ModelRef]]
    embeddings: EmbeddingsConfig
    limits: LimitsConfig
    rag: RagConfig

    @field_validator("tasks")
    @classmethod
    def _chains_not_empty(
        cls, tasks: dict[TaskType, list[ModelRef]]
    ) -> dict[TaskType, list[ModelRef]]:
        empty = [task.value for task, chain in tasks.items() if not chain]
        if empty:
            raise ValueError(f"cadena de modelos vacía en las tareas: {', '.join(empty)}")
        return tasks

    @model_validator(mode="after")
    def _references_are_consistent(self) -> Self:
        missing_tasks = [task.value for task in TaskType if task not in self.tasks]
        if missing_tasks:
            raise ValueError(f"faltan tareas en 'tasks': {', '.join(missing_tasks)}")
        refs = [ref.provider for chain in self.tasks.values() for ref in chain]
        refs.append(self.embeddings.provider)
        unknown = sorted({name for name in refs if name not in self.providers})
        if unknown:
            raise ValueError(f"proveedores no declarados en 'providers': {', '.join(unknown)}")
        return self


def load_models_config(path: Path = DEFAULT_MODELS_PATH) -> ModelsConfig:
    """Lee y valida `config/models.yaml`; lanza `ConfigError` con un mensaje legible."""
    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        # Sin encadenar: el texto de YAMLError incluye fragmentos del archivo.
        raise ConfigError(f"No se pudo leer la configuración de modelos '{path.name}'.") from None
    try:
        return ModelsConfig.model_validate(raw)
    except ValidationError as exc:
        # Sin los valores de entrada ni la excepción encadenada: podrían contener una clave.
        raise ConfigError(
            f"La configuración de modelos '{path.name}' no es válida:\n{_describe_errors(exc)}"
        ) from None


def _describe_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors(include_input=False, include_url=False, include_context=False):
        location = ".".join(str(part) for part in error["loc"]) or "(raíz)"
        lines.append(f"- {location}: {error['msg']}")
    return "\n".join(lines)


# --- .env --------------------------------------------------------------------------------


class Settings(BaseSettings):
    """Variables de entorno y `.env` (ver `.env.example`)."""

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Jira Cloud
    jira_base_url: str | None = None
    jira_cloud_id: SecretStr | None = None
    jira_email: SecretStr | None = None
    jira_api_token: SecretStr | None = None
    jira_project_key: str | None = None
    jira_test_subtask_type: str = "Subtarea"
    # T-25: por defecto no se escribe en Jira; `live` solo cuando se decida publicar de verdad.
    jira_publish_mode: Literal["simulation", "live"] = "simulation"

    # Proveedores LLM (D-14)
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    ollama_base_url: str | None = None

    # Base de datos
    postgres_user: str = "agente"
    postgres_password: SecretStr | None = None
    postgres_db: str = "agente"
    database_url: SecretStr | None = None

    # Aplicación
    app_env: str = "development"
    log_level: str = "INFO"
    models_config_path: Path = DEFAULT_MODELS_PATH

    # API HTTP para el frontend (T-55, `docs/api/requisitos-parte-2.md`)
    # Orígenes permitidos (`Origin`/`Referer` y CORS), separados por comas. Vacío: solo el
    # mismo origen (el frontend llega por el proxy de Vite o del servidor web).
    api_allowed_origins: str = ""
    # Cookie sin `Secure`: solo con este indicador y `APP_ENV=development` (localhost ya la acepta).
    api_insecure_dev_cookie: bool = False
    api_session_idle_minutes: PositiveInt = 30
    api_session_max_hours: PositiveInt = 12
    api_login_max_attempts: PositiveInt = 5
    api_login_lock_seconds: PositiveInt = 300
    api_max_body_bytes: PositiveInt = 262_144
    api_max_streams_per_user: PositiveInt = 3
    # Hilos de las operaciones largas (no son workers de uvicorn: la API va en un solo proceso).
    api_workers: PositiveInt = 4
    # PA-279 (RGPD): días que se conservan las revisiones de calidad guardadas.
    quality_retention_days: PositiveInt = 90

    @field_validator("api_allowed_origins")
    @classmethod
    def _explicit_origins(cls, value: str) -> str:
        """Solo orígenes explícitos `http(s)://host[:puerto]`: nunca `*` con credenciales."""
        for origin in (o.strip() for o in value.split(",")):
            if origin and not _ORIGIN.fullmatch(origin.rstrip("/")):
                raise ValueError(
                    "API_ALLOWED_ORIGINS solo admite orígenes http(s)://host[:puerto]."
                )
        return value

    @property
    def is_development(self) -> bool:
        return self.app_env.strip().lower() == "development"

    @property
    def api_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.api_allowed_origins.split(",") if o.strip()]

    @property
    def api_cookie_secure(self) -> bool:
        return not (self.api_insecure_dev_cookie and self.is_development)

    @field_validator(
        "jira_base_url",
        "jira_cloud_id",
        "jira_email",
        "jira_api_token",
        "jira_project_key",
        "groq_api_key",
        "openrouter_api_key",
        mode="before",
    )
    @classmethod
    def _placeholder_as_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and (is_placeholder(value) or "TU_SITIO" in value):
            return None
        return value

    def sqlalchemy_url(self) -> URL:
        """URL de la base de datos: `DATABASE_URL` o, si falta, las variables `POSTGRES_*`."""
        if self.database_url and self.database_url.get_secret_value():
            return make_url(self.database_url.get_secret_value())
        password = self.postgres_password.get_secret_value() if self.postgres_password else None
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=password,
            # 127.0.0.1 y no localhost: con el puerto publicado solo en IPv4, Windows prueba
            # antes ::1 y tarda ~20 s en pasar a IPv4 (e2e del 2026-10-04).
            host="127.0.0.1",
            port=5432,
            database=self.postgres_db,
        )

    def secret_values(self) -> list[str]:
        """Valores de todos los secretos presentes, para el enmascarado de logs."""
        values = []
        for name in type(self).model_fields:
            field = getattr(self, name)
            if isinstance(field, SecretStr) and field.get_secret_value():
                values.append(field.get_secret_value())
        return values


# --- Configuración combinada ---------------------------------------------------------------


class ProviderStatus(BaseModel):
    name: str
    available: bool
    reason: str | None = None


class AppConfig:
    """Secretos + modelos, con la disponibilidad de cada proveedor resuelta sin fallar."""

    def __init__(self, settings: Settings, models: ModelsConfig) -> None:
        self.settings = settings
        self.models = models

    def api_key_for(self, provider: str) -> SecretStr | None:
        env_name = self.models.providers[provider].api_key_env
        if env_name is None:
            return None
        field = env_name.lower()
        if field in type(self.settings).model_fields:
            value = getattr(self.settings, field)
            return value if isinstance(value, SecretStr) else None
        raw = os.environ.get(env_name)
        return None if is_placeholder(raw) else SecretStr(raw or "")

    def base_url_for(self, provider: str) -> str:
        config = self.models.providers[provider]
        # El proveedor local (sin clave) es Ollama: OLLAMA_BASE_URL tiene prioridad.
        if config.api_key_env is None and self.settings.ollama_base_url:
            return self.settings.ollama_base_url
        return config.base_url

    def provider_status(self, provider: str) -> ProviderStatus:
        config = self.models.providers[provider]
        if config.api_key_env is None or self.api_key_for(provider) is not None:
            return ProviderStatus(name=provider, available=True)
        return ProviderStatus(
            name=provider,
            available=False,
            reason=f"Falta la variable {config.api_key_env}; proveedor no disponible.",
        )

    def providers_status(self) -> dict[str, ProviderStatus]:
        return {name: self.provider_status(name) for name in self.models.providers}

    def task_chain(self, task: TaskType, only_available: bool = True) -> list[ModelRef]:
        """Cadena ordenada de modelos de la tarea (principal primero, luego respaldos)."""
        chain = self.models.tasks[task]
        if not only_available:
            return list(chain)
        return [ref for ref in chain if self.provider_status(ref.provider).available]


def build_config(settings: Settings | None = None) -> AppConfig:
    settings = settings or Settings()
    return AppConfig(settings, load_models_config(settings.models_config_path))


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Configuración de la aplicación, cargada una sola vez por proceso."""
    return build_config()
