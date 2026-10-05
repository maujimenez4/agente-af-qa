"""Administración mínima (T-29; RF-01, RF-40, RF-41): probar conexiones y ver los modelos.

Solo para `admin` (`MANAGE_CONNECTIONS`, `MANAGE_MODELS`) y solo lectura: nada se escribe en Jira
ni se genera texto con un modelo. Las comprobaciones están en `core/health.py`; de cada proveedor
solo se muestra el host, nunca la URL entera ni la clave.
"""

import time

import streamlit as st

from adapters.base import IssueTracker
from app.session import SessionState, go
from core.config import AppConfig
from core.factories import build_connection_tester
from core.health import ServiceCheck, host_of
from core.logging import get_logger
from core.permissions import Permission, can

log = get_logger(__name__)

TEST_INTERVAL_S = 10.0  # como la API: una prueba cada 10 s
_LAST_TEST = "admin_last_test"
_RESULTS = "admin_results"


def allowed(session: SessionState) -> bool:
    user = session.user
    return can(user, Permission.MANAGE_CONNECTIONS) and can(user, Permission.MANAGE_MODELS)


def render(session: SessionState) -> None:
    ws, config = session.workspace, session.config
    if not allowed(session) or ws is None or config is None:
        go(session, "inicio")
        return
    st.subheader("Administración · solo lectura")
    st.caption("Comprueba los servicios y consulta los modelos configurados. No cambia nada.")
    _connections(session, config, ws.container.issue_tracker)
    st.divider()
    _models(config)


def _connections(session: SessionState, config: AppConfig, tracker: IssueTracker) -> None:
    st.markdown("**Conexiones**")
    if st.button("Probar conexiones", type="primary", key="admin_test"):
        wait = wait_seconds(st.session_state.get(_LAST_TEST), time.monotonic())
        if wait is not None:
            st.warning(f"Espera {wait} s antes de volver a probar las conexiones.")
        else:
            st.session_state[_LAST_TEST] = time.monotonic()
            with st.spinner("Comprobando los servicios…"):
                st.session_state[_RESULTS] = run_checks(config, tracker)
            log.info(
                "conexiones probadas por admin",
                user=session.user.username if session.user else None,
                action="test_connections",
            )
    results: list[ServiceCheck] | None = st.session_state.get(_RESULTS)
    if results:
        st.dataframe(check_rows(results), hide_index=True)


def _models(config: AppConfig) -> None:
    st.markdown("**Modelos por tarea**")
    st.dataframe(model_rows(config), hide_index=True)


# --- Funciones puras (probadas sin Streamlit) ----------------------------------------------------


def wait_seconds(last: float | None, now: float, interval_s: float = TEST_INTERVAL_S) -> int | None:
    """`None` si se puede probar ya; si no, los segundos (redondeados hacia arriba) que faltan."""
    if last is None or now - last >= interval_s:
        return None
    return max(1, int(interval_s - (now - last) + 0.999))


def run_checks(config: AppConfig, tracker: IssueTracker | None) -> list[ServiceCheck]:
    tester, catalog = build_connection_tester(config, tracker)
    try:
        return tester.run()
    finally:
        catalog.close()


def check_rows(checks: list[ServiceCheck]) -> list[dict[str, str]]:
    return [
        {
            "Servicio": c.service,
            "Estado": "✅" if c.ok else "❌",
            "Detalle": c.detail,
            "Tiempo": f"{c.duration_ms} ms",
        }
        for c in checks
    ]


def _host(config: AppConfig, provider: str) -> str:
    if provider not in config.models.providers:
        return "?"
    return host_of(config.base_url_for(provider))


def model_rows(config: AppConfig) -> list[dict[str, str]]:
    rows = [
        {
            "Tarea": task.value,
            "Orden": str(position),
            "Proveedor": ref.provider,
            "Modelo": ref.model,
            "Host": _host(config, ref.provider),
        }
        for task, chain in config.models.tasks.items()
        for position, ref in enumerate(chain, start=1)
    ]
    embeddings = config.models.embeddings
    rows.append(
        {
            "Tarea": "embeddings",
            "Orden": "1",
            "Proveedor": embeddings.provider,
            "Modelo": embeddings.model,
            "Host": _host(config, embeddings.provider),
        }
    )
    return rows
