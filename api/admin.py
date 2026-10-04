"""Administración mínima (T-29; RF-01, RF-40, RF-41): probar conexiones y ver los modelos.

Solo lectura y solo para `admin` (`MANAGE_CONNECTIONS`, `MANAGE_MODELS`; `core/permissions`).
Las comprobaciones están en `core/health.py`; aquí se componen con los adaptadores concretos a
partir de la configuración. Nada de esto escribe en Jira ni genera texto con un modelo.
"""

import math
import threading
import time
from typing import Any

from fastapi import APIRouter, Request

from adapters.llm.catalog import HttpModelCatalog
from api import examples as ex
from api.errors import ApiError
from api.models import (
    AdminModelOut,
    AdminModelsOut,
    AdminTaskModelsOut,
    ConnectionCheckOut,
    ConnectionsTestOut,
    ErrorResponse,
    ModelChoiceOut,
)
from api.runtime import Workspace
from api.security import session_for
from core.config import AppConfig
from core.factories import build_connection_tester
from core.health import ConnectionTester, host_of
from core.logging import get_logger
from core.permissions import Permission, require

log = get_logger("api.admin")

TEST_INTERVAL_S = 10.0  # una prueba de conexiones cada 10 s por persona
NOT_AVAILABLE = "La configuración no está disponible: no se pueden comprobar los servicios."

router = APIRouter(prefix="/admin", tags=["Administración"])


class ConnectionTestLimiter:
    """Una prueba cada `interval_s` por persona; seguro entre hilos."""

    def __init__(self, interval_s: float = TEST_INTERVAL_S) -> None:
        self._interval_s = interval_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, username: str) -> float | None:
        """`None` si puede probar ya (y lo anota); si no, los segundos que faltan."""
        now = time.monotonic()
        with self._lock:
            last = self._last.get(username)
            if last is not None and now - last < self._interval_s:
                return self._interval_s - (now - last)
            self._last[username] = now
            return None


def _limiter(request: Request) -> ConnectionTestLimiter:
    state = request.app.state
    limiter = getattr(state, "admin_test_limiter", None)
    if limiter is None:
        limiter = ConnectionTestLimiter()
        state.admin_test_limiter = limiter
    return limiter


def _config(ws: Workspace) -> AppConfig:
    config = ws.container.config
    if config is None:
        raise ApiError(503, "service_unavailable", NOT_AVAILABLE)
    return config


def build_tester(ws: Workspace) -> tuple[ConnectionTester, HttpModelCatalog]:
    """Compone las comprobaciones con los adaptadores concretos (las pruebas lo sustituyen)."""
    return build_connection_tester(_config(ws), ws.container.issue_tracker)


def _host(config: AppConfig, provider: str) -> str:
    if provider not in config.models.providers:
        return "?"
    return host_of(config.base_url_for(provider))


# --- Ejemplos del contrato -----------------------------------------------------------------------


def _json(example: Any) -> dict[str, Any]:
    return {"content": {"application/json": {"example": example}}}


def _error(status: int, code: str, message: str, description: str) -> dict[int, Any]:
    retry_after = TEST_INTERVAL_S if code == "rate_limited" else None
    example = ex.error(code, message, retry_after)
    return {status: {"model": ErrorResponse, "description": description, **_json(example)}}


# Las mismas respuestas comunes que el resto de rutas (`api/app.py`, requisitos 7 y 8).
ERRORS = {
    **_error(401, "unauthenticated", "Inicia sesión para continuar.", "Sin sesión o caducada."),
    **_error(
        429,
        "rate_limited",
        "Espera unos segundos antes de volver a probar las conexiones.",
        "Una prueba de conexiones cada 10 s por persona.",
    ),
    **_error(
        403,
        "forbidden",
        "No tienes permiso para realizar esta acción.",
        "Solo para `admin`, o sin cabecera `X-CSRF-Token` válida.",
    ),
    **_error(
        413, "payload_too_large", "La petición es demasiado grande.", "Cuerpo de más de 256 KB."
    ),
    **_error(
        500,
        "unexpected",
        "Ha ocurrido un error inesperado. Vuelve a intentarlo o empieza de nuevo.",
        "Error no previsto (sin detalles internos).",
    ),
    **_error(
        503,
        "service_unavailable",
        NOT_AVAILABLE,
        "La API no ha podido arrancar o falta la configuración.",
    ),
}
CHECKS_EXAMPLE = ConnectionsTestOut(
    checks=[
        ConnectionCheckOut(
            service="Jira",
            ok=True,
            detail="Conexión correcta con api.atlassian.com.",
            duration_ms=412,
        ),
        ConnectionCheckOut(
            service="PostgreSQL",
            ok=True,
            detail="Conexión correcta con db:5432; migraciones al día (0006_quality_reviews).",
            duration_ms=38,
        ),
        ConnectionCheckOut(
            service="Modelos · ollama",
            ok=False,
            detail="Faltan modelos: qwen3:8b.",
            duration_ms=21,
        ),
        ConnectionCheckOut(
            service="Embeddings", ok=True, detail="1 modelo disponible.", duration_ms=19
        ),
    ]
)
MODELS_EXAMPLE = AdminModelsOut(
    tasks=[
        AdminTaskModelsOut(
            task="functional",
            chain=[AdminModelOut(provider="ollama", model="qwen3:8b", host="ollama:11434")],
        )
    ],
    embeddings=AdminModelOut(provider="ollama", model="bge-m3", host="ollama:11434"),
)


# --- Rutas ---------------------------------------------------------------------------------------


@router.post(
    "/connections/test",
    response_model=ConnectionsTestOut,
    summary="Probar las conexiones (Jira, PostgreSQL, modelos y embeddings)",
    description=(
        "Una comprobación por servicio, en paralelo y con 5 s como máximo cada una; un fallo no "
        "impide las demás. Sin generar texto con ningún modelo. Una prueba cada 10 s por persona."
    ),
    responses={
        200: _json(CHECKS_EXAMPLE.model_dump(mode="json")),
        **ERRORS,
    },
)
def run_connection_test(request: Request) -> ConnectionsTestOut:
    session = session_for(request)
    user, ws = session.user, session.workspace
    require(user, Permission.MANAGE_CONNECTIONS)
    _config(ws)  # 503 sin configuración, sin gastar el turno del límite
    wait = _limiter(request).acquire(user.username)
    if wait is not None:
        raise ApiError(
            429,
            "rate_limited",
            "Espera unos segundos antes de volver a probar las conexiones.",
            float(math.ceil(wait)),
        )
    tester, catalog = build_tester(ws)
    try:
        checks = tester.run()
    finally:
        catalog.close()
    log.info(
        "conexiones probadas por admin",
        user=user.username,
        action="test_connections",
        failed=sum(not c.ok for c in checks),
    )
    return ConnectionsTestOut(
        checks=[
            ConnectionCheckOut(
                service=c.service, ok=c.ok, detail=c.detail, duration_ms=c.duration_ms
            )
            for c in checks
        ]
    )


@router.get(
    "/models",
    response_model=AdminModelsOut,
    summary="Modelos por tarea y de embeddings (solo lectura)",
    description="De cada proveedor, solo el host: nunca la URL entera ni la clave.",
    responses={200: _json(MODELS_EXAMPLE.model_dump(mode="json")), **ERRORS},
)
def list_models(request: Request) -> AdminModelsOut:
    session = session_for(request)
    user, ws = session.user, session.workspace
    require(user, Permission.MANAGE_MODELS)
    config = _config(ws)
    tasks = []
    for task, chain in config.models.tasks.items():
        override = ws.overrides.get(task)
        tasks.append(
            AdminTaskModelsOut(
                task=task.value,
                chain=[
                    AdminModelOut(
                        provider=ref.provider, model=ref.model, host=_host(config, ref.provider)
                    )
                    for ref in chain
                ],
                override=(
                    ModelChoiceOut(provider=override.provider, model=override.model)
                    if override
                    else None
                ),
            )
        )
    embeddings = config.models.embeddings
    return AdminModelsOut(
        tasks=tasks,
        embeddings=AdminModelOut(
            provider=embeddings.provider,
            model=embeddings.model,
            host=_host(config, embeddings.provider),
        ),
    )
