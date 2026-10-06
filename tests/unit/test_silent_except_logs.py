"""PA-244 · Los `except Exception` que ignoraban el error dejan rastro del tipo en el log.

Cuatro casos de la capa 1 de `/auditoria` (`silent-except`): el resultado para la persona no
cambia y el log lleva `error_type`, nunca el mensaje de la excepción (podría llevar datos).
Datos ficticios.
"""

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from structlog.testing import capture_logs

from api import service
from app import conversation as conv_module
from app.conversation import RESTART, Conversation
from app.origin import StartRequest
from core.health import ServiceCheck, _Plan, _timed

LEAK = "cadena-ficticia-que-no-debe-salir-0000"


class BoomError(RuntimeError):
    """Fallo ficticio cuyo mensaje no debe aparecer en el log."""


def _raise(*_args: Any, **_kwargs: Any) -> Any:
    raise BoomError(LEAK)


def _warning(logs: list[dict[str, Any]], action: str) -> dict[str, Any]:
    (entry,) = [e for e in logs if e.get("action") == action]
    assert entry["log_level"] == "warning"
    assert entry["error_type"] == "BoomError"
    assert LEAK not in repr(entry)
    return entry


def test_failed_ids_logs_error_type_and_still_returns_empty() -> None:
    ws = SimpleNamespace(container=SimpleNamespace(audit=SimpleNamespace(entries=_raise)))
    artifact = SimpleNamespace(id=uuid4())

    with capture_logs() as logs:
        result = service._failed_ids(ws, artifact)  # type: ignore[arg-type]

    assert result == []
    assert _warning(logs, "read_failed_ids")["artifact_id"] == str(artifact.id)


def _conversation() -> Conversation:
    return Conversation(StartRequest(flow="evolve", kind="story", project="DEMO"), user="af-demo")


def _broken_ws() -> Any:
    return SimpleNamespace(graph=SimpleNamespace(get_state=_raise))


def test_after_failure_logs_error_type_and_still_offers_restart() -> None:
    conv = _conversation()

    with capture_logs() as logs:
        conv_module._after_failure(_broken_ws(), conv)

    assert conv.finished == RESTART and conv.can_restart is True
    assert _warning(logs, "after_failure")["user"] == "af-demo"


def test_settle_approval_logs_error_type_and_still_returns_false() -> None:
    conv = _conversation()

    with capture_logs() as logs:
        settled = conv_module._settle_approval(_broken_ws(), conv, None, None)  # type: ignore[arg-type]

    assert settled is False
    assert _warning(logs, "settle_approval")["user"] == "af-demo"


def test_health_check_logs_error_type_and_keeps_fixed_detail() -> None:
    with capture_logs() as logs:
        check = _timed(_Plan("Jira", _raise))

    assert isinstance(check, ServiceCheck)
    assert check.ok is False
    assert check.detail == "Error inesperado al comprobar el servicio."
    assert LEAK not in check.detail
    assert _warning(logs, "test_connections")["service"] == "Jira"
