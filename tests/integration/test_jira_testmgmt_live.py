"""Publicación real de una suite de QA en Jira nativo (T-30: RF-30, RNF-13, PA-05).

ESCRIBE EN JIRA: crea una HU sintética en `JIRA_PROJECT_KEY`, le publica una suite de 2 CP
(subtareas con la etiqueta `caso-prueba`) con la estrategia y la matriz como adjuntos, y la
vuelve a publicar para comprobar que no duplica nada (PA-05). Solo se ejecuta con
`-m integration` y la variable de entorno `JIRA_WRITE_TESTS=1`; se salta si faltan
JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN o JIRA_PROJECT_KEY. Nunca se imprimen valores del
`.env`.

LIMPIEZA MANUAL: el agente no borra nada en Jira. Las claves creadas se muestran con `print`
(`uv run pytest -m integration -s …`) y deben borrarse a mano (al borrar la HU se borran sus
subtareas). Los títulos empiezan por «[PRUEBA-AGENTE]» (`summary ~ "PRUEBA-AGENTE"`).
"""

import os

import pytest

from adapters.testmgmt.jira_native import JiraNativeTests
from core.config import Settings
from core.factories import build_issue_tracker
from schemas.common import Priority
from schemas.test_case import TestCase, TestCaseType, TestStep, TestSuite
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


def synthetic_suite(story_key: str) -> TestSuite:
    def case(number: int, criterion: str, kind: TestCaseType) -> TestCase:
        return TestCase(
            internal_id=f"CP-0{number}",
            title=f"{TEST_PREFIX} Caso ficticio {number}",
            criterion_ids=[criterion],
            type=kind,
            preconditions=["Una persona socia ficticia con un préstamo activo"],
            steps=[TestStep(action="Pulsar «Renovar»", data=None, expected="Se amplía el plazo")],
            gherkin="Escenario: caso ficticio\n  Dado un préstamo\n  Cuando renuevo\n  Entonces ok",
            priority=Priority.MUST,
        )

    return TestSuite(
        story_jira_key=story_key,
        cases=[
            case(1, "CA-01", TestCaseType.POSITIVE),
            case(2, "CA-02", TestCaseType.NEGATIVE),
        ],
        strategy_md="# Estrategia ficticia\n\nPruebas funcionales de la HU de prueba.\n",
    )


def test_publish_suite_creates_subtasks_and_attachments_without_duplicates(
    live_settings: Settings,
) -> None:
    """RF-30, RNF-13, PA-05: publica 2 CP y los adjuntos; republicar no duplica nada."""
    project = live_settings.jira_project_key
    assert project and live_settings.jira_email and live_settings.jira_api_token
    tracker = build_issue_tracker(live_settings)
    tests = JiraNativeTests(
        live_settings.jira_base_url or "",
        live_settings.jira_email,
        live_settings.jira_api_token,
        cloud_id=live_settings.jira_cloud_id,
        subtask_type=live_settings.jira_test_subtask_type,
    )
    created: list[str] = []
    try:
        story = renewal_story(None).model_copy(
            update={"internal_id": None, "title": f"{TEST_PREFIX} HU para casos (T-30)"}
        )
        story_key = tracker.create_story(story, None, project)
        created.append(story_key)

        first = tests.publish_suite(synthetic_suite(story_key))
        created += first.created
        assert first.failed == []
        assert len(first.created) == 2

        cases = tests.list_cases(story_key)
        assert sorted(c.key for c in cases) == sorted(first.created)
        assert all(c.summary.startswith(("[CP-01]", "[CP-02]")) for c in cases)

        second = tests.publish_suite(synthetic_suite(story_key))  # PA-05
        assert second.failed == []
        assert sorted(second.created) == sorted(first.created)
        assert len(tests.list_cases(story_key)) == 2
    finally:
        # Solo claves: nunca URLs, credenciales ni contenido del .env.
        print(f"\nIncidencias de prueba creadas (bórralas a mano): {', '.join(created) or '-'}")
