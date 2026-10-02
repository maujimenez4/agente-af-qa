"""FakeTestManagement.record_execution (T-47, RF-28): mismas reglas que `JiraNativeTests`.

Pruebas del método añadido al fake por la sesión Jira; el resto del fake se prueba en
`tests/unit/test_fake_test_management.py` (de la sesión principal).
"""

import pytest

from adapters.errors import PublishError
from adapters.testmgmt.jira_native import ExecutionStatus
from tests.fakes import FakeTestManagement
from tests.fakes.llm import renewal_test_suite


@pytest.mark.parametrize("status", list(ExecutionStatus))
def test_record_execution_registers_key_value_and_evidence(status: ExecutionStatus) -> None:
    """RF-28: el fake registra (clave, valor del resultado, evidencia) aceptando el enum."""
    fake = FakeTestManagement()
    fake.record_execution("DEMO-501", status, "Evidencia ficticia")
    assert fake.executions == [("DEMO-501", status.value, "Evidencia ficticia")]


def test_record_execution_accepts_str_value_and_keeps_order() -> None:
    """RF-28: también acepta el valor str; las ejecuciones se acumulan en orden."""
    fake = FakeTestManagement()
    fake.record_execution("DEMO-501", "paso", "")
    fake.record_execution("DEMO-501", ExecutionStatus.FAILED, "Falla el paso 2")
    assert fake.executions == [
        ("DEMO-501", "paso", ""),
        ("DEMO-501", "fallo", "Falla el paso 2"),
    ]


@pytest.mark.parametrize("status", [ExecutionStatus.FAILED, "fallo"], ids=["enum", "str"])
@pytest.mark.parametrize("evidence", ["", "   ", "\n\t"], ids=["vacia", "espacios", "blancos"])
def test_record_execution_raises_publish_error_when_failed_has_no_evidence(
    status: ExecutionStatus | str, evidence: str
) -> None:
    """RF-28, UI.md §6.6: «fallo» sin evidencia → PublishError y nada registrado."""
    fake = FakeTestManagement()
    with pytest.raises(PublishError, match="necesita evidencia"):
        fake.record_execution("DEMO-501", status, evidence)
    assert fake.executions == []


def test_record_execution_raises_publish_error_for_fail_execution_keys() -> None:
    """RF-28: `fail_execution_keys` simula el fallo; las demás claves se registran."""
    fake = FakeTestManagement(fail_execution_keys={"DEMO-502"})
    with pytest.raises(PublishError, match="DEMO-502"):
        fake.record_execution("DEMO-502", ExecutionStatus.PASSED, "")
    fake.record_execution("DEMO-501", ExecutionStatus.PASSED, "")
    assert fake.executions == [("DEMO-501", "paso", "")]


def test_publish_suite_and_list_cases_unchanged_by_executions() -> None:
    """CA-00-03, RF-28: registrar ejecuciones no altera publish_suite ni list_cases."""
    fake = FakeTestManagement()
    result = fake.publish_suite(renewal_test_suite())
    before = fake.list_cases("DEMO-3")
    fake.record_execution(result.created[0], ExecutionStatus.FAILED, "Evidencia ficticia")
    assert fake.list_cases("DEMO-3") == before
    assert fake.publish_calls == 1
    assert fake.attachments["DEMO-3"]
    assert len(fake.executions) == 1


def test_record_execution_raises_publish_error_when_status_is_unknown() -> None:
    """RF-28: un resultado desconocido → PublishError, como en JiraNativeTests."""
    fake = FakeTestManagement()
    with pytest.raises(PublishError):
        fake.record_execution("DEMO-501", "desconocido", "Evidencia ficticia")
