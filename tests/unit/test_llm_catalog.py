"""Catálogo de modelos por HTTP (T-29 mínima; RF-40, RF-41): `adapters/llm/catalog.py`.

Todo con `httpx.MockTransport`: no sale ninguna petición a la red. Claves y URL 100 % ficticias.
"""

from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from adapters.errors import AuthenticationError, ExternalServiceError
from adapters.llm.catalog import MAX_MODELS, HttpModelCatalog, host_of

BASE_URL = "http://ollama.example.invalid:11434/v1"
CLOUD_URL = "https://nube.example.invalid/openai/v1"
FAKE_KEY = "clave-ficticia-catalogo-0000"
HOST = "ollama.example.invalid:11434"

Handler = Callable[[httpx.Request], httpx.Response]


def _catalog(
    handler: Handler,
    *,
    keys: dict[str, SecretStr | None] | None = None,
    timeout_s: float = 5.0,
) -> tuple[HttpModelCatalog, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(record))
    catalog = HttpModelCatalog(
        {"local": BASE_URL, "nube": CLOUD_URL},
        keys,
        http_client=client,
        timeout_s=timeout_s,
    )
    return catalog, seen


def _ok(payload: object) -> Handler:
    return lambda _request: httpx.Response(200, json=payload)


# --- Lista de modelos ---------------------------------------------------------------------------


def test_list_models_returns_ids_when_response_is_valid() -> None:
    """CA T-29 (RF-41): GET {base_url}/models devuelve los ids de los modelos disponibles."""
    payload = {"object": "list", "data": [{"id": "qwen3:8b"}, {"id": "bge-m3:latest"}]}
    catalog, seen = _catalog(_ok(payload))
    assert catalog.list_models("local") == {"qwen3:8b", "bge-m3:latest"}
    assert len(seen) == 1
    assert seen[0].method == "GET"
    assert str(seen[0].url) == f"{BASE_URL}/models"


def test_list_models_strips_trailing_slash_when_base_url_has_it() -> None:
    """CA T-29: la ruta es {base_url}/models aunque la URL base termine en «/»."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    catalog = HttpModelCatalog({"local": BASE_URL + "/"}, http_client=client)
    assert catalog.list_models("local") == set()
    assert str(seen[0].url) == f"{BASE_URL}/models"


def test_list_models_ignores_entries_when_id_is_missing_or_not_text() -> None:
    """CA T-29: las entradas sin `id` (o con un `id` que no es texto) se ignoran."""
    payload = {
        "data": [
            {"id": "modelo-ficticio-a"},
            {"name": "sin-id"},
            {"id": 123},
            {"id": None},
            "no-es-un-objeto",
            {"id": "modelo-ficticio-b"},
        ]
    }
    catalog, _ = _catalog(_ok(payload))
    assert catalog.list_models("local") == {"modelo-ficticio-a", "modelo-ficticio-b"}


def test_list_models_reads_at_most_max_models_when_list_is_huge() -> None:
    """CA T-29 (límite): solo se leen los primeros MAX_MODELS nombres de la respuesta."""
    payload = {"data": [{"id": f"modelo-{i}"} for i in range(MAX_MODELS + 50)]}
    catalog, _ = _catalog(_ok(payload))
    models = catalog.list_models("local")
    assert len(models) == MAX_MODELS
    assert f"modelo-{MAX_MODELS - 1}" in models
    assert f"modelo-{MAX_MODELS}" not in models


# --- Cabecera Authorization ---------------------------------------------------------------------


def test_list_models_sends_bearer_when_provider_has_key() -> None:
    """CA T-29: con clave se envía `Authorization: Bearer <clave>`."""
    catalog, seen = _catalog(_ok({"data": []}), keys={"nube": SecretStr(FAKE_KEY)})
    catalog.list_models("nube")
    assert seen[0].headers["Authorization"] == f"Bearer {FAKE_KEY}"
    assert seen[0].headers["Accept"] == "application/json"


@pytest.mark.parametrize("key", [None, SecretStr("")])
def test_list_models_omits_authorization_when_key_is_missing_or_empty(
    key: SecretStr | None,
) -> None:
    """CA T-29: sin clave (o vacía) no se envía la cabecera Authorization."""
    catalog, seen = _catalog(_ok({"data": []}), keys={"local": key})
    catalog.list_models("local")
    assert "Authorization" not in seen[0].headers


def test_list_models_does_not_send_key_of_other_provider() -> None:
    """CA T-29: la clave de un proveedor no viaja a otro."""
    catalog, seen = _catalog(_ok({"data": []}), keys={"nube": SecretStr(FAKE_KEY)})
    catalog.list_models("local")
    assert "Authorization" not in seen[0].headers


# --- Errores ------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_list_models_raises_authentication_error_when_key_rejected(status: int) -> None:
    """CA T-29 (RNF seguridad): 401/403 → AuthenticationError sin la clave ni la ruta."""
    catalog, _ = _catalog(
        lambda _r: httpx.Response(status, json={"error": f"bad key {FAKE_KEY}"}),
        keys={"nube": SecretStr(FAKE_KEY)},
    )
    with pytest.raises(AuthenticationError) as info:
        catalog.list_models("nube")
    message = str(info.value)
    assert f"HTTP {status}" in message
    assert "nube.example.invalid" in message
    assert FAKE_KEY not in message
    assert "/openai/v1" not in message
    assert "/models" not in message
    assert info.value.service == "nube"


def test_list_models_raises_external_error_with_host_when_timeout() -> None:
    """CA T-29: tiempo agotado → ExternalServiceError con el host y sin el texto de la excepción."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("texto-interno-ficticio-timeout", request=request)

    catalog, _ = _catalog(handler, timeout_s=0.5)
    with pytest.raises(ExternalServiceError) as info:
        catalog.list_models("local")
    message = str(info.value)
    assert HOST in message
    assert "0.5 s" in message
    assert "texto-interno-ficticio-timeout" not in message
    assert not isinstance(info.value, AuthenticationError)
    assert info.value.__cause__ is None
    assert info.value.__suppress_context__


def test_list_models_raises_external_error_when_connection_fails() -> None:
    """CA T-29: error de conexión → ExternalServiceError «No se pudo conectar con <host>»."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("texto-interno-ficticio-conexion", request=request)

    catalog, _ = _catalog(handler)
    with pytest.raises(ExternalServiceError, match="No se pudo conectar") as info:
        catalog.list_models("local")
    assert HOST in str(info.value)
    assert "texto-interno-ficticio-conexion" not in str(info.value)


def test_list_models_raises_external_error_when_server_fails() -> None:
    """CA T-29: HTTP 500 → ExternalServiceError con el código, sin el cuerpo."""
    catalog, _ = _catalog(lambda _r: httpx.Response(500, text="traza-interna-ficticia"))
    with pytest.raises(ExternalServiceError) as info:
        catalog.list_models("local")
    assert "HTTP 500" in str(info.value)
    assert "traza-interna-ficticia" not in str(info.value)
    assert not isinstance(info.value, AuthenticationError)


def test_list_models_raises_external_error_when_json_is_invalid() -> None:
    """CA T-29: un cuerpo que no es JSON → ExternalServiceError «respuesta no válida»."""
    catalog, _ = _catalog(lambda _r: httpx.Response(200, text="<html>no json</html>"))
    with pytest.raises(ExternalServiceError, match="respuesta no válida"):
        catalog.list_models("local")


@pytest.mark.parametrize(
    "payload",
    [{"data": "no-lista"}, {"data": {"id": "x"}}, {"otro": []}, ["lista-suelta"], "texto"],
)
def test_list_models_raises_external_error_when_data_is_not_a_list(payload: object) -> None:
    """CA T-29: "data" ausente o que no es una lista → ExternalServiceError."""
    catalog, _ = _catalog(_ok(payload))
    with pytest.raises(ExternalServiceError, match="lista de modelos no válida"):
        catalog.list_models("local")


def test_list_models_raises_external_error_when_provider_not_configured() -> None:
    """CA T-29: un proveedor sin base_url → ExternalServiceError sin llamar a la red."""
    catalog, seen = _catalog(_ok({"data": []}))
    with pytest.raises(ExternalServiceError, match="no está configurado") as info:
        catalog.list_models("desconocido")
    assert seen == []
    assert info.value.service == "desconocido"


def test_list_models_truncates_provider_name_when_not_configured() -> None:
    """CA T-29 (límite): el nombre del proveedor del mensaje se recorta a 40 caracteres."""
    catalog, _ = _catalog(_ok({"data": []}))
    with pytest.raises(ExternalServiceError) as info:
        catalog.list_models("p" * 200)
    assert "p" * 40 in str(info.value)
    assert "p" * 41 not in str(info.value)


def test_list_models_does_not_follow_redirects_when_server_answers_302() -> None:
    """CA T-29 (seguridad): un 302 es un error; no se sigue (la clave no viaja a otro host)."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "otro.example.invalid":
            return httpx.Response(200, json={"data": [{"id": "x"}]})
        return httpx.Response(302, headers={"Location": "https://otro.example.invalid/models"})

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    catalog = HttpModelCatalog(
        {"nube": CLOUD_URL}, {"nube": SecretStr(FAKE_KEY)}, http_client=client
    )
    with pytest.raises(ExternalServiceError, match="HTTP 302"):
        catalog.list_models("nube")
    assert [r.url.host for r in seen] == ["nube.example.invalid"]


# --- host_of y close ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("http://usuario_demo:clave_demo@ollama.example.invalid:11434/v1?x=1", HOST),
        ("https://usuario_demo@nube.example.invalid/openai/v1", "nube.example.invalid"),
        ("https://api.example.invalid", "api.example.invalid"),
        ("", "?"),
        ("no-es-una-url", "?"),
    ],
)
def test_host_of_returns_only_host_and_port_when_url_has_credentials(
    url: str, expected: str
) -> None:
    """CA T-29 (seguridad): host_of nunca devuelve usuario, contraseña, ruta ni consulta."""
    host = host_of(url)
    assert host == expected
    for leaked in ("usuario_demo", "clave_demo", "/v1", "x=1", "@"):
        assert leaked not in host


def test_close_closes_client_when_catalog_created_it() -> None:
    """CA T-29: close() cierra el cliente propio y no toca uno inyectado."""
    own = HttpModelCatalog({"local": BASE_URL})
    own.close()
    assert own._client.is_closed

    injected = httpx.Client(transport=httpx.MockTransport(_ok({"data": []})))
    shared = HttpModelCatalog({"local": BASE_URL}, http_client=injected)
    shared.close()
    assert not injected.is_closed
    injected.close()
