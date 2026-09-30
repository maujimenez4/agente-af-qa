"""Pruebas de core/logging.py: ningún secreto aparece en los logs (T-03 · RNF-02, RNF-23)."""

import io
import json
from collections.abc import Iterator

import pytest
import structlog
from pydantic import SecretStr

from core.config import Settings
from core.logging import MASK, SecretMasker, configure_logging, get_logger

# Valores sintéticos con forma de secreto; no son credenciales reales.
FAKE_SECRET = "fake-secret-value-0000000000"
FAKE_BEARER = "Bearer faketoken0000000000000000"
FAKE_JWT = "eyJfakeheader000.eyJfakepayload00.fakesignature0000"
FAKE_GROQ_LIKE = "gsk_" + "0" * 40


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    configure_logging("DEBUG", secrets=[FAKE_SECRET], stream=stream)
    yield stream
    structlog.reset_defaults()


def _lines(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_output_is_json_with_conventional_fields(log_stream: io.StringIO) -> None:
    get_logger("test").info(
        "artefacto generado", user="u-demo", action="create", artifact_id="a1", duration_ms=12
    )
    (event,) = _lines(log_stream)
    assert event["event"] == "artefacto generado"
    assert event["level"] == "info"
    assert event["user"] == "u-demo"
    assert event["duration_ms"] == 12
    assert "timestamp" in event


def test_known_secret_value_never_appears(log_stream: io.StringIO) -> None:
    log = get_logger()
    log.info(f"llamada con {FAKE_SECRET}", detail={"nested": [f"x {FAKE_SECRET} y"]})
    log.error("fallo", error=f"401 para clave {FAKE_SECRET}")
    output = log_stream.getvalue()
    assert FAKE_SECRET not in output
    assert MASK in output


@pytest.mark.parametrize("value", [FAKE_BEARER, FAKE_JWT, FAKE_GROQ_LIKE])
def test_token_patterns_are_masked(log_stream: io.StringIO, value: str) -> None:
    get_logger().info("respuesta", body=f"texto {value} fin")
    output = log_stream.getvalue()
    assert value not in output
    assert MASK in output


@pytest.mark.parametrize("key", ["authorization", "api_key", "password", "jira_api_token"])
def test_sensitive_keys_are_masked(log_stream: io.StringIO, key: str) -> None:
    get_logger().info("peticion", headers={key: "valor-cualquiera"}, **{key: "valor-cualquiera"})
    (event,) = _lines(log_stream)
    assert event[key] == MASK
    assert event["headers"][key] == MASK


def test_password_in_connection_url_is_masked(log_stream: io.StringIO) -> None:
    get_logger().info("conectando", target="postgresql+psycopg://agente:clave-ficticia@db:5432/x")
    output = log_stream.getvalue()
    assert "clave-ficticia" not in output
    assert "agente:***@db" in output


def test_secretstr_values_are_masked(log_stream: io.StringIO) -> None:
    get_logger().info("config", value=SecretStr("otro-valor-ficticio"))
    assert "otro-valor-ficticio" not in log_stream.getvalue()


def test_exception_text_is_masked(log_stream: io.StringIO) -> None:
    try:
        raise RuntimeError(f"fallo de autenticación con {FAKE_SECRET}")
    except RuntimeError:
        get_logger().exception("error externo")
    assert FAKE_SECRET not in log_stream.getvalue()


def test_settings_secrets_are_masked_end_to_end(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("OPENROUTER_API_KEY", "fake-openrouter-key-000")
    settings = Settings(_env_file=None)
    stream = io.StringIO()
    configure_logging(secrets=settings.secret_values(), stream=stream)
    try:
        get_logger().warning("reintento", info="clave fake-openrouter-key-000 rechazada")
    finally:
        structlog.reset_defaults()
    assert "fake-openrouter-key-000" not in stream.getvalue()


def test_level_filtering() -> None:
    stream = io.StringIO()
    configure_logging("WARNING", stream=stream)
    try:
        get_logger().info("no debe salir")
        get_logger().warning("sí debe salir")
    finally:
        structlog.reset_defaults()
    assert [e["event"] for e in _lines(stream)] == ["sí debe salir"]


def test_masker_prefers_longest_secret() -> None:
    masker = SecretMasker(["abcd", "abcd-efgh-ijkl"])
    assert masker.mask_text("x abcd-efgh-ijkl y") == f"x {MASK} y"


def test_bytes_values_are_masked(log_stream: io.StringIO) -> None:
    get_logger().info("respuesta", body=f"Authorization: {FAKE_BEARER} {FAKE_SECRET}".encode())
    output = log_stream.getvalue()
    assert "faketoken" not in output
    assert FAKE_SECRET not in output


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("GET https://api.example.invalid/v1?api_key=abc123fake&x=1", "abc123fake"),
        ("GET https://api.example.invalid/v1?token=tok999fake", "tok999fake"),
        ('{"password": "pw-ficticia-1", "user": "u-demo"}', "pw-ficticia-1"),
        ('{"access_token":"at-ficticio-2"}', "at-ficticio-2"),
        ("postgresql://agente:con@rroba-ficticia@db:5432/x", "rroba-ficticia"),
    ],
)
def test_secrets_inside_text_are_masked(log_stream: io.StringIO, text: str, leaked: str) -> None:
    get_logger().warning("error externo", detail=text)
    assert leaked not in log_stream.getvalue()


@pytest.mark.parametrize("key", ["auth", "jira_email", "jira_cloud_id", "X-Api-Key", "Set-Cookie"])
def test_more_sensitive_keys_are_masked(log_stream: io.StringIO, key: str) -> None:
    get_logger().info("peticion", headers={key: "valor-cualquiera"})
    (event,) = _lines(log_stream)
    assert event["headers"][key] == MASK


def test_token_metrics_are_not_masked(log_stream: io.StringIO) -> None:
    get_logger().info(
        "uso",
        input_tokens=120,
        max_tokens=900,
        context_token_budget=6000,
        detail="Basic authentication",
    )
    (event,) = _lines(log_stream)
    assert event["input_tokens"] == 120
    assert event["max_tokens"] == 900
    assert event["context_token_budget"] == 6000
    assert event["detail"] == "Basic authentication"


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("POSTGRES_PASSWORD=fakepw000", "fakepw000"),
        ("JIRA_API_TOKEN=fakejiratok000", "fakejiratok000"),
        ("GROQ_API_KEY=fakegroqval000", "fakegroqval000"),
        ("GET /x?api_token=fakeqs000", "fakeqs000"),
        ("Authorization: Token faketokval000", "faketokval000"),
        ('password="fake pass words"', "pass words"),
        ('{"password": "fa,ke-000"}', "ke-000"),
    ],
)
def test_prefixed_and_quoted_secrets_are_masked(
    log_stream: io.StringIO, text: str, leaked: str
) -> None:
    get_logger().warning("error externo", detail=text)
    assert leaked not in log_stream.getvalue()


@pytest.mark.parametrize("key", ["private_key", "session_id"])
def test_private_key_and_session_are_masked(log_stream: io.StringIO, key: str) -> None:
    get_logger().info("dato", **{key: "valor-ficticio"})
    (event,) = _lines(log_stream)
    assert event[key] == MASK
