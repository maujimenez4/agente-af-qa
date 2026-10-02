"""Registro real de la ejecución de un CP en Jira nativo (T-47: RF-28, R-01 opción A).

ESCRIBE EN JIRA: crea una HU sintética en `JIRA_PROJECT_KEY`, le publica una suite de 1 CP
(subtarea con la etiqueta `caso-prueba`) y registra sobre esa subtarea primero «paso» y después
«fallo», ambos con evidencia. Comprueba que la subtarea queda con la etiqueta `ejecucion-fallo`
(y sin `ejecucion-paso`) y con 2 comentarios «Resultado de la ejecución». Solo se ejecuta con
`-m integration` y la variable de entorno `JIRA_WRITE_TESTS=1`; se salta si faltan
JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN o JIRA_PROJECT_KEY. Nunca se imprimen valores del
`.env`.

LIMPIEZA MANUAL: el agente no borra nada en Jira. Las claves creadas se muestran con `print`
(`uv run pytest -m integration -s …`) y deben borrarse a mano (al borrar la HU se borran sus
subtareas). Los títulos empiezan por «[PRUEBA-AGENTE]» (`summary ~ "PRUEBA-AGENTE"`).
"""

import os

import pytest

from adapters.testmgmt.jira_native import ExecutionStatus, JiraNativeTests
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
RESULT_TEXT = "Resultado de la ejecución"


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


def single_case_suite(story_key: str) -> TestSuite:
    return TestSuite(
        story_jira_key=story_key,
        cases=[
            TestCase(
                internal_id="CP-01",
                title=f"{TEST_PREFIX} Caso ficticio de ejecución",
                criterion_ids=["CA-01"],
                type=TestCaseType.POSITIVE,
                preconditions=["Una persona socia ficticia con un préstamo activo"],
                steps=[
                    TestStep(action="Pulsar «Renovar»", data=None, expected="Se amplía el plazo")
                ],
                gherkin=None,
                priority=Priority.MUST,
            )
        ],
        strategy_md="# Estrategia ficticia\n\nPrueba de registro de ejecución (T-47).\n",
    )


def test_record_execution_updates_label_and_adds_comments(live_settings: Settings) -> None:
    """RF-28, R-01 opción A: «paso» y luego «fallo» → etiqueta ejecucion-fallo y 2 comentarios."""
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
            update={"internal_id": None, "title": f"{TEST_PREFIX} HU para ejecución (T-47)"}
        )
        story_key = tracker.create_story(story, None, project)
        created.append(story_key)

        published = tests.publish_suite(single_case_suite(story_key))
        created += published.created
        assert published.failed == []
        [case_key] = published.created

        tests.record_execution(
            case_key, ExecutionStatus.PASSED, "Ejecución ficticia correcta: **plazo ampliado**."
        )
        tests.record_execution(
            case_key,
            ExecutionStatus.FAILED,
            "Falla el paso 1 (dato ficticio): [captura](https://ejemplo.invalid/captura.png)",
        )

        issue = tracker.get_issue(case_key)
        assert "caso-prueba" in issue.labels
        assert "ejecucion-fallo" in issue.labels
        assert "ejecucion-paso" not in issue.labels
        results = [c for c in issue.comments if RESULT_TEXT in c]
        assert len(results) == 2
    finally:
        # Solo claves: nunca URLs, credenciales ni contenido del .env.
        print(f"\nIncidencias de prueba creadas (bórralas a mano): {', '.join(created) or '-'}")
