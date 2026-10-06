"""Prueba de conexiones de la Administración (T-29 mínima; RF-01, RF-40, RF-41).

Una comprobación por servicio, en paralelo y con tiempo límite; un fallo no impide las demás:

- **Jira:** `IssueTracker.test_connection()`, una lectura barata; nunca una escritura.
- **PostgreSQL:** `SELECT 1` y la revisión de Alembic aplicada frente a `head`.
- **Modelos** (un resultado por proveedor de las cadenas de `config/models.yaml`) y
  **embeddings:** el listado de modelos del proveedor (`ModelCatalog`) y que los configurados
  están descargados. Sin generar texto: no se gastan tokens ni se carga ningún modelo.

`detail` va en español y nunca lleva secretos: solo mensajes fijos, el host (sin usuario) y, si
acaso, el mensaje ya saneado de un `AgentError` (`adapters/errors.py`); el texto de cualquier
otra excepción se descarta.
"""

import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

from adapters.base import IssueTracker
from adapters.errors import AgentError
from core.config import AppConfig
from core.logging import get_logger

if TYPE_CHECKING:
    from sqlalchemy.engine import URL

log = get_logger(__name__)

DEFAULT_TIMEOUT_S = 5.0
NOT_CONFIGURED = "Sin configurar"
MAX_DETAIL_CHARS = 300
MAX_MISSING_SHOWN = 5


class ModelCatalog(Protocol):
    """Modelos disponibles en un proveedor; la implementación está en `adapters/llm/catalog.py`."""

    def list_models(self, provider: str) -> set[str]: ...


@dataclass(frozen=True)
class ServiceCheck:
    service: str
    ok: bool
    detail: str
    duration_ms: int


class NotConfiguredError(Exception):
    """El servicio no está configurado: no se le llama (p. ej. un proveedor sin clave)."""


Check = Callable[[], str]  # devuelve el detalle si va bien; lanza si no


@dataclass(frozen=True)
class _Plan:
    service: str
    run: Check


def normalize_model(name: str) -> str:
    """En Ollama, un modelo sin etiqueta es `:latest` (`qwen3` ≡ `qwen3:latest`)."""
    name = name.strip()
    return name if ":" in name else f"{name}:latest"


class ConnectionTester:
    """Ejecuta las comprobaciones en paralelo y devuelve un `ServiceCheck` por servicio."""

    def __init__(
        self,
        config: AppConfig,
        catalog: ModelCatalog,
        *,
        issue_tracker: IssueTracker | None = None,
        database_check: Check | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._config = config
        self._catalog = catalog
        self._tracker = issue_tracker
        self._database_check = database_check
        self._timeout_s = timeout_s

    def run(self) -> list[ServiceCheck]:
        plans = self._plans()
        started = time.perf_counter()
        results: dict[int, ServiceCheck] = {}
        executor = ThreadPoolExecutor(max_workers=max(1, len(plans)))
        try:
            futures = {executor.submit(_timed, plan): i for i, plan in enumerate(plans)}
            done, _pending = wait_futures(futures, timeout=self._timeout_s)
            for future, index in futures.items():
                if future in done:
                    results[index] = future.result()
                else:  # agotó el tiempo: los demás resultados siguen valiendo
                    results[index] = ServiceCheck(
                        plans[index].service,
                        False,
                        f"No respondió en {self._timeout_s:g} s.",
                        round(self._timeout_s * 1000),
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        checks = [results[i] for i in range(len(plans))]
        log.info(
            "conexiones probadas",
            action="test_connections",
            services=len(checks),
            failed=sum(not c.ok for c in checks),
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return checks

    # --- Plan de comprobaciones ------------------------------------------------------------

    def _plans(self) -> list[_Plan]:
        plans = [_Plan("Jira", self._check_jira), _Plan("PostgreSQL", self._check_database)]
        for provider, models in self._models_by_provider().items():
            plans.append(_Plan(f"Modelos · {provider}", self._model_check(provider, models)))
        embeddings = self._config.models.embeddings
        plans.append(
            _Plan("Embeddings", self._model_check(embeddings.provider, [embeddings.model]))
        )
        return plans

    def _models_by_provider(self) -> dict[str, list[str]]:
        by_provider: dict[str, list[str]] = {}
        for chain in self._config.models.tasks.values():
            for ref in chain:
                models = by_provider.setdefault(ref.provider, [])
                if ref.model not in models:
                    models.append(ref.model)
        return by_provider

    def _check_jira(self) -> str:
        if self._tracker is None:
            raise NotConfiguredError
        self._tracker.test_connection()
        return f"Conexión correcta con {jira_host(self._config)}."

    def _check_database(self) -> str:
        if self._database_check is None:
            raise NotConfiguredError
        return self._database_check()

    def _model_check(self, provider: str, models: Iterable[str]) -> Check:
        wanted = list(models)

        def check() -> str:
            if not self._config.provider_status(provider).available:
                raise NotConfiguredError  # sin clave: no se le llama
            available = {normalize_model(m) for m in self._catalog.list_models(provider)}
            missing = [m for m in wanted if normalize_model(m) not in available]
            if missing:
                shown = ", ".join(missing[:MAX_MISSING_SHOWN])
                more = (
                    f" y {len(missing) - MAX_MISSING_SHOWN} más"
                    if len(missing) > MAX_MISSING_SHOWN
                    else ""
                )
                raise MissingModelsError(f"Faltan modelos: {shown}{more}.")
            plural = "modelo disponible" if len(wanted) == 1 else "modelos disponibles"
            return f"{len(wanted)} {plural}."

        return check


class MissingModelsError(Exception):
    """Algún modelo configurado no está descargado en el proveedor (mensaje ya seguro)."""


def _timed(plan: _Plan) -> ServiceCheck:
    started = time.perf_counter()
    try:
        ok, detail = True, plan.run()
    except NotConfiguredError:
        ok, detail = False, f"{NOT_CONFIGURED}."
    except (AgentError, MissingModelsError, MissingMigrationsError) as exc:
        ok, detail = False, str(exc)  # mensajes saneados (adapters/errors.py) o propios
    except Exception as exc:  # nunca el texto: podría llevar una cadena de conexión
        # PA-244: el administrador ve un mensaje fijo; en el log queda el tipo, sin el mensaje.
        log.warning(
            "comprobación fallida",
            action="test_connections",
            service=plan.service,
            error_type=type(exc).__name__,
        )
        ok, detail = False, "Error inesperado al comprobar el servicio."
    elapsed = round((time.perf_counter() - started) * 1000)
    return ServiceCheck(plan.service, ok, detail[:MAX_DETAIL_CHARS], elapsed)


def host_of(url: str) -> str:
    """Solo el host (y el puerto) de una URL: nunca usuario, contraseña, ruta ni consulta."""
    parts = urlsplit(url)
    host = parts.hostname or "?"
    return f"{host}:{parts.port}" if parts.port else host


def jira_host(config: AppConfig) -> str:
    settings = config.settings
    if settings.jira_cloud_id is not None and settings.jira_cloud_id.get_secret_value():
        return "api.atlassian.com"
    return host_of(settings.jira_base_url or "")


# --- PostgreSQL ---------------------------------------------------------------------------------


def database_check(url: "URL", *, timeout_s: float = DEFAULT_TIMEOUT_S) -> Check:
    """`SELECT 1` y la revisión de Alembic aplicada frente a `head`. El detalle solo lleva el
    host y el puerto: nunca el usuario ni la contraseña de la URL."""
    import sqlalchemy as sa

    from adapters.errors import ExternalServiceError

    where = f"{url.host or '?'}:{url.port or 5432}"

    def check() -> str:
        # Tiempo límite al conectar y en cada consulta: un servidor que acepta y no responde
        # no deja el hilo colgado.
        connect_args = {
            "connect_timeout": max(1, int(timeout_s)),
            "options": f"-c statement_timeout={round(timeout_s * 1000)}",
        }
        engine = sa.create_engine(url, connect_args=connect_args)
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
                try:
                    current = conn.execute(
                        sa.text("SELECT version_num FROM alembic_version")
                    ).scalar()
                except sa.exc.SQLAlchemyError:
                    current = None  # sin tabla de Alembic: no se han aplicado migraciones
        except sa.exc.SQLAlchemyError:
            raise ExternalServiceError(
                f"No se pudo conectar con PostgreSQL en {where}.", service="postgresql"
            ) from None
        finally:
            engine.dispose()
        head = alembic_head()
        if current is None:
            raise MissingMigrationsError(
                f"Conecta con {where}, pero no hay migraciones aplicadas (alembic upgrade head)."
            )
        if current != head:
            raise MissingMigrationsError(
                f"Conecta con {where}, pero la revisión es {current} y la última es {head} "
                "(alembic upgrade head)."
            )
        return f"Conexión correcta con {where}; migraciones al día ({head})."

    return check


class MissingMigrationsError(Exception):
    """La base de datos responde pero no está en la última migración (mensaje ya seguro)."""


def alembic_head() -> str:
    """Revisión `head` de `migrations/` (sin conectar a la base de datos)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from core.config import ROOT_DIR

    return str(
        ScriptDirectory.from_config(Config(str(ROOT_DIR / "alembic.ini"))).get_current_head()
    )
