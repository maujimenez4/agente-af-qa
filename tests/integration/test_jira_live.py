"""Conexión real con Jira Cloud (T-11: RF-01, RNF-04).

Solo lectura: no escribe nada en Jira. Se salta si faltan JIRA_BASE_URL, JIRA_EMAIL o
JIRA_API_TOKEN en `.env` o en el entorno.
"""

import pytest

from core.config import Settings
from core.factories import build_issue_tracker

pytestmark = pytest.mark.integration


@pytest.fixture
def live_settings() -> Settings:
    settings = Settings()
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
    return settings


def test_test_connection_succeeds_against_real_jira(live_settings: Settings) -> None:
    """RF-01: las credenciales configuradas permiten conectar con Jira Cloud (solo lectura)."""
    build_issue_tracker(live_settings).test_connection()
