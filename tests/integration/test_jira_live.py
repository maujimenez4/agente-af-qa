"""Conexión y consultas reales con Jira Cloud (T-11: RF-01, RNF-04; T-14: RF-02, RF-14).

Solo lectura: no escribe nada en Jira (ni se llama a ningún método de escritura). Se salta si
faltan JIRA_BASE_URL, JIRA_EMAIL o JIRA_API_TOKEN en `.env` o en el entorno. Las pruebas de
T-14 necesitan además JIRA_PROJECT_KEY y el seed de `data/seed/jira/` importado (etiqueta
`seed-villaficticia`); si no está, se saltan con un mensaje claro. Nunca se imprimen valores
del `.env`.
"""

import httpx
import pytest

from adapters.jira import tracker as tracker_module
from adapters.jira.jql import quote
from adapters.jira.tracker import JiraCloudTracker
from core.config import Settings
from core.context.jql import text_search_jql
from core.factories import build_issue_tracker

SEED_LABEL = "seed-villaficticia"
SEED_ISSUES = 17
SEED_EPICS = 4

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


# --- T-14: consultas JQL contra el seed importado (solo lectura) -----------------------------


@pytest.fixture
def seed_project(live_settings: Settings) -> str:
    """Clave del proyecto con el seed; se salta si falta la variable o el seed."""
    project = live_settings.jira_project_key
    if not project:
        pytest.skip("Falta la variable de Jira: JIRA_PROJECT_KEY")
    tracker = build_issue_tracker(live_settings)
    if not tracker.search(seed_jql(project), limit=1):
        pytest.skip(
            f"El seed de Jira no está importado (0 incidencias con la etiqueta {SEED_LABEL}). "
            "Sigue data/seed/jira/README.md."
        )
    return project


def seed_jql(project: str) -> str:
    return f"project = {quote(project)} AND labels = {quote(SEED_LABEL)} ORDER BY key"


def test_list_epics_returns_four_seed_epics(live_settings: Settings, seed_project: str) -> None:
    """RF-02: el proyecto sembrado tiene 4 épicas (hierarchyLevel = 1)."""
    epics = build_issue_tracker(live_settings).list_epics(seed_project)
    assert len(epics) == SEED_EPICS
    assert len({epic.key for epic in epics}) == SEED_EPICS


def test_list_children_returns_four_stories_of_loan_epic(
    live_settings: Settings, seed_project: str
) -> None:
    """RF-02: la épica «Préstamo digital» tiene 4 HU hijas con prefijo [HU-0."""
    tracker = build_issue_tracker(live_settings)
    epics = [e for e in tracker.list_epics(seed_project) if "Préstamo digital" in e.summary]
    assert len(epics) == 1
    children = tracker.list_children(epics[0].key)
    assert len(children) == 4
    assert all(child.summary.startswith("[HU-0") for child in children)


def test_search_returns_seed_issues_up_to_limit(live_settings: Settings, seed_project: str) -> None:
    """RF-02: la búsqueda por etiqueta con limit=17 devuelve 17 claves distintas."""
    results = build_issue_tracker(live_settings).search(seed_jql(seed_project), limit=SEED_ISSUES)
    assert len(results) == SEED_ISSUES
    assert len({issue.key for issue in results}) == SEED_ISSUES


def test_search_paginates_with_next_page_token_when_page_size_small(
    live_settings: Settings, seed_project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RF-02: con PAGE_SIZE=5 se recorren varias páginas y no se repiten claves."""
    monkeypatch.setattr(tracker_module, "PAGE_SIZE", 5)
    # Solo se guarda si cada petición lleva token: la URL real (con el cloudId) nunca se imprime.
    has_token: list[bool] = []

    def record(request: httpx.Request) -> None:
        has_token.append("nextPageToken" in request.url.params)

    with httpx.Client(timeout=30.0, event_hooks={"request": [record]}) as client:
        tracker: JiraCloudTracker = build_issue_tracker(live_settings, http_client=client)
        results = tracker.search(seed_jql(seed_project), limit=SEED_ISSUES)
    assert len(results) == SEED_ISSUES
    assert len({issue.key for issue in results}) == SEED_ISSUES
    assert len(has_token) >= 4
    assert has_token[0] is False
    assert all(has_token[1:])


def test_text_search_finds_renewal_story(live_settings: Settings, seed_project: str) -> None:
    """RF-14: la búsqueda por texto libre «renovar» encuentra al menos una HU del seed."""
    results = build_issue_tracker(live_settings).search(
        text_search_jql(seed_project, "renovar"), limit=20
    )
    assert any(issue.summary.startswith("[HU-") for issue in results)


def test_list_projects_includes_configured_project(live_settings: Settings) -> None:
    """RF-02: el proyecto de `JIRA_PROJECT_KEY` aparece entre los proyectos visibles."""
    if not live_settings.jira_project_key:
        pytest.skip("Falta JIRA_PROJECT_KEY.")
    keys = [p.key for p in build_issue_tracker(live_settings).list_projects()]
    assert live_settings.jira_project_key in keys
