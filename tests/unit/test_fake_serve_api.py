"""`tests/fakes/serve_api.py`: la API real sobre los dobles, solo para desarrollo del frontend."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from adapters.base import Message, TaskType
from core.config import Settings
from tests.fakes import serve_api
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.serve_api import DelayedLLM


class _UvicornSpy:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, app: object, **kwargs: Any) -> None:
        self.calls.append({"app": app, **kwargs})


@pytest.fixture
def uvicorn_spy(monkeypatch: pytest.MonkeyPatch) -> _UvicornSpy:
    spy = _UvicornSpy()
    monkeypatch.setattr(serve_api.uvicorn, "run", spy)
    return spy


@pytest.mark.parametrize("value", [None, "", "production", "Development", "test"])
def test_refuses_to_start_unless_app_env_is_development(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    uvicorn_spy: _UvicornSpy,
    value: str | None,
) -> None:
    if value is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", value)

    assert serve_api.main([]) == 2
    assert uvicorn_spy.calls == []
    assert serve_api.NOT_DEVELOPMENT in capsys.readouterr().err


def test_listens_only_on_loopback(
    monkeypatch: pytest.MonkeyPatch, uvicorn_spy: _UvicornSpy
) -> None:
    monkeypatch.setenv("APP_ENV", "development")

    assert serve_api.main(["--port", "8123", "--delay", "0"]) == 0

    (call,) = uvicorn_spy.calls
    assert call["host"] == "127.0.0.1" == serve_api.HOST
    assert call["port"] == 8123
    assert call["workers"] == 1
    assert call["access_log"] is False
    assert isinstance(call["app"], FastAPI)


def test_has_no_option_to_change_the_host() -> None:
    with pytest.raises(SystemExit):
        serve_api.parse_args(["--host", "0.0.0.0"])  # noqa: S104 - se comprueba que se rechaza


def test_defaults_are_port_8100_and_delay_one_and_a_half_seconds() -> None:
    args = serve_api.parse_args([])

    assert args.port == serve_api.DEFAULT_PORT == 8100
    assert args.delay == serve_api.DEFAULT_DELAY_S == 1.5


def test_does_not_read_the_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aunque `Settings` apunte a un `.env` con valores no válidos, la app se compone igual."""
    env_file = tmp_path / ".env"
    env_file.write_text("API_SESSION_IDLE_MINUTES=-5\nJIRA_PUBLISH_MODE=live\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", env_file)
    with pytest.raises(ValueError):  # sanidad: leerlo sí fallaría
        Settings()
    captured: dict[str, Any] = {}
    real_create_app = serve_api.create_app

    def spy_create_app(**kwargs: Any) -> FastAPI:
        captured.update(kwargs)
        return real_create_app(**kwargs)

    monkeypatch.setattr(serve_api, "create_app", spy_create_app)

    app = serve_api.build_app(tmp_path, delay_s=0)

    assert isinstance(app, FastAPI)
    settings: Settings = captured["settings"]
    assert settings.jira_publish_mode == "simulation"
    assert settings.app_env == "development"
    assert settings.api_session_idle_minutes == 30


def test_runtime_runs_long_operations_in_background_and_in_simulation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    real_create_app = serve_api.create_app

    def spy_create_app(**kwargs: Any) -> FastAPI:
        captured.update(kwargs)
        return real_create_app(**kwargs)

    monkeypatch.setattr(serve_api, "create_app", spy_create_app)

    serve_api.build_app(tmp_path, delay_s=0)

    runtime = captured["runtime_instance"]
    assert runtime.run_inline is False
    container = runtime.workspace_factory().container
    assert container.publish_mode == "simulation"
    assert isinstance(container.llm, DelayedLLM)


def test_delayed_llm_waits_then_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(serve_api.time, "sleep", waits.append)
    inner = FakeLLMProvider()
    llm = DelayedLLM(inner, 1.5)
    messages = [Message(role="user", content="Texto ficticio")]

    result = llm.generate(messages, TaskType.CLASSIFY_SOURCE)

    assert waits == [1.5]
    assert result.provider == inner.provider
    assert len(inner.calls) == 1


def test_negative_delay_is_treated_as_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built: dict[str, Any] = {}
    real_container = serve_api.fake_container

    def spy_container(memory_dir: Path, **overrides: Any) -> Any:
        built.update(overrides)
        return real_container(memory_dir, **overrides)

    monkeypatch.setattr(serve_api, "fake_container", spy_container)

    serve_api.build_app(tmp_path, delay_s=-3)

    assert built["llm"]._delay_s == 0.0
    assert built["publish_mode"] == "simulation"


def test_usage_ring_counts_tokens_of_todays_llm_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /settings/usage tiene datos: cada llamada al LLM falso anota sus tokens."""
    monkeypatch.setattr(serve_api.time, "sleep", lambda _s: None)
    usage = serve_api.InMemoryUsage()
    llm = DelayedLLM(FakeLLMProvider(), 0, usage)
    messages = [Message(role="user", content="Texto ficticio")]

    first = llm.generate(messages, TaskType.CLASSIFY_SOURCE)
    second = llm.generate(messages, TaskType.NL_TO_JQL)

    calls = usage.calls()
    assert [c.task for c in calls] == ["nl_to_jql", "classify_source"]  # más reciente primero
    expected = sum(r.input_tokens + r.output_tokens for r in (first, second))
    assert sum(c.total_tokens for c in calls) == expected
    assert usage.calls(limit=1)[0].task == "nl_to_jql"
    assert usage.calls(since=calls[0].at.replace(year=calls[0].at.year + 1)) == []


def test_runtime_exposes_the_usage_for_the_ring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    real_create_app = serve_api.create_app

    def spy_create_app(**kwargs: Any) -> FastAPI:
        captured.update(kwargs)
        return real_create_app(**kwargs)

    monkeypatch.setattr(serve_api, "create_app", spy_create_app)

    serve_api.build_app(tmp_path, delay_s=0)

    runtime = captured["runtime_instance"]
    assert isinstance(runtime.usage, serve_api.InMemoryUsage)
    assert runtime.workspace_factory().container.llm._usage is runtime.usage
