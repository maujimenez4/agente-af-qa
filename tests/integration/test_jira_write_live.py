"""Escritura real en Jira Cloud (T-27: RF-04, RF-05, RF-06, PA-46).

ESCRIBE EN JIRA: crea dos HU sintéticas en `JIRA_PROJECT_KEY`, actualiza una con un comentario
de diff y las vincula con «relates to». Solo se ejecuta con `-m integration` y la variable de
entorno `JIRA_WRITE_TESTS=1`; se salta si faltan JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN o
JIRA_PROJECT_KEY. Nunca se imprimen valores del `.env`.

LIMPIEZA MANUAL: el adaptador no tiene borrado (nada borra en Jira desde el agente). Las claves
creadas se muestran con `print` (`uv run pytest -m integration -s …`) y deben borrarse a mano
en Jira. Todos los títulos empiezan por «[PRUEBA-AGENTE]» para localizarlas con
`summary ~ "PRUEBA-AGENTE"`.
"""

import os

import pytest

from adapters.jira.tracker import JIRA_KEY_RE
from core.config import Settings
from core.factories import build_issue_tracker
from schemas.user_story import UserStory
from tests.fakes.dataset import renewal_story

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("JIRA_WRITE_TESTS") != "1",
        reason="Escribe en Jira: requiere JIRA_WRITE_TESTS=1 en el entorno.",
    ),
]

TEST_PREFIX = "[PRUEBA-AGENTE]"


@pytest.fixture
def live_settings() -> Settings:
    settings = Settings()
    missing = [
        name
        for name, value in (
            ("JIRA_BASE_URL", settings.jira_base_url),
            ("JIRA_EMAIL", settings.jira_email),
            ("JIRA_API_TOKEN", settings.jira_api_token),
            ("JIRA_PROJECT_KEY", settings.jira_project_key),
        )
        if not value
    ]
    if missing:
        pytest.skip(f"Faltan variables de Jira: {', '.join(missing)}")
    return settings


def synthetic_story(title: str) -> UserStory:
    """HU ficticia, sin id interno: el título empieza por el prefijo de prueba."""
    return renewal_story(None).model_copy(
        update={"internal_id": None, "title": f"{TEST_PREFIX} {title}"}
    )


def test_create_update_and_link_synthetic_stories(live_settings: Settings) -> None:
    """RF-04, RF-05, RF-06, PA-46: crea dos HU, actualiza una con diff y las vincula."""
    project = live_settings.jira_project_key
    assert project
    tracker = build_issue_tracker(live_settings)
    created: list[str] = []
    try:
        first = tracker.create_story(synthetic_story("HU ficticia A"), None, project)
        created.append(first)
        second = tracker.create_story(synthetic_story("HU ficticia B"), None, project)
        created.append(second)

        for key in created:
            assert JIRA_KEY_RE.fullmatch(key)
            assert key.rsplit("-", 1)[0] == project  # PA-46

        updated = synthetic_story("HU ficticia A (actualizada)")
        diff = (
            "**Cambios propuestos por FAQ y aprobados**\n\n"
            "| Campo | Antes | Después |\n|---|---|---|\n"
            f"| title | {TEST_PREFIX} HU ficticia A | {updated.title} |"
        )
        tracker.update_story(first, updated, diff)
        tracker.link(first, second, "relates to", "Vínculo de prueba ficticio (T-27).")

        detail = tracker.get_issue(first)
        assert detail.summary == updated.title
        assert any("Cambios propuestos" in comment for comment in detail.comments)
        assert any(link.key == second for link in detail.links)
    finally:
        # Solo claves: nunca URLs, credenciales ni contenido del .env.
        print(f"\nHU de prueba creadas (bórralas a mano en Jira): {', '.join(created) or '-'}")
