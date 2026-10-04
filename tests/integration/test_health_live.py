"""Prueba de conexiones real (T-29 mínima; RF-01, RF-40, RF-41).

Compone `ConnectionTester` con los adaptadores reales (como `api.admin.build_tester`): Jira si
están sus variables, PostgreSQL y el catálogo `GET {base_url}/models` de cada proveedor. Solo
lectura: no escribe en Jira ni genera texto con ningún modelo. Se salta si faltan las variables
de Jira; los demás servicios pueden fallar sin romper la prueba (se comprueba la forma y que
el detalle no lleva secretos). Nunca se imprimen valores del `.env`.
"""

import pytest

from adapters.llm.catalog import HttpModelCatalog
from core.config import AppConfig, build_config
from core.factories import build_issue_tracker
from core.health import DEFAULT_TIMEOUT_S, MAX_DETAIL_CHARS, ConnectionTester, database_check

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_config() -> AppConfig:
    config = build_config()
    settings = config.settings
    missing = [
        name
        for name, value in (
            ("JIRA_BASE_URL", settings.jira_base_url),
            ("JIRA_EMAIL", settings.jira_email),
            ("JIRA_API_TOKEN", settings.jira_api_token),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Faltan variables de Jira: {', '.join(missing)}")
    return config


def test_connection_tester_reports_every_service_when_live(live_config: AppConfig) -> None:
    """CA T-29 (RF-01, RF-40, RF-41): un resultado por servicio, a tiempo y sin secretos."""
    providers = {ref.provider for chain in live_config.models.tasks.values() for ref in chain}
    providers.add(live_config.models.embeddings.provider)
    catalog = HttpModelCatalog(
        base_urls={p: live_config.base_url_for(p) for p in providers},
        api_keys={p: live_config.api_key_for(p) for p in providers},
    )
    tester = ConnectionTester(
        live_config,
        catalog,
        issue_tracker=build_issue_tracker(live_config.settings),
        database_check=database_check(live_config.settings.sqlalchemy_url()),
    )
    try:
        checks = tester.run()
    finally:
        catalog.close()

    services = [c.service for c in checks]
    assert services[:2] == ["Jira", "PostgreSQL"]
    assert services[-1] == "Embeddings"
    assert {
        f"Modelos · {p}" for p in providers if p != live_config.models.embeddings.provider
    } <= set(services)
    sensitive_values = live_config.settings.secret_values()
    for check in checks:
        assert check.detail
        assert len(check.detail) <= MAX_DETAIL_CHARS
        assert check.duration_ms <= DEFAULT_TIMEOUT_S * 1000 + 1000
        for value in sensitive_values:
            assert value not in check.detail, f"El detalle de {check.service} lleva un secreto"
