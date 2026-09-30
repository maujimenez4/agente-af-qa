"""Pruebas de `OllamaEmbeddings` (T-16 · RF-10, CA-00-03).

Las unitarias inyectan un cliente falso con la forma de `OpenAI().embeddings`; no hay red.
La de integración usa el Ollama real de `Settings().ollama_base_url` y se salta si no responde.
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from adapters.base import EmbeddingProvider
from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError
from core.config import Settings

BASE_URL = "http://ollama-ficticio.invalid:11434/v1"
RESPONSE_DETAIL = "detalle-interno-ficticio-de-la-respuesta"
DIMS = 4


def _vector(seed: int, dims: int = DIMS) -> list[float]:
    return [float(seed)] + [0.0] * (dims - 1)


@dataclass
class FakeEmbeddingsEndpoint:
    """Imita `client.embeddings`: registra llamadas y devuelve `.data` con `.index`/`.embedding`."""

    dims: int = DIMS
    reverse: bool = False
    drop_one: bool = False
    error: Exception | None = None
    calls: list[list[str]] = field(default_factory=list)

    def create(self, model: str, input: list[str]) -> Any:
        self.calls.append(list(input))
        if self.error is not None:
            raise self.error
        items = [
            SimpleNamespace(index=i, embedding=_vector(int(text.split("-")[-1]), self.dims))
            for i, text in enumerate(input)
        ]
        if self.drop_one:
            items = items[:-1]
        if self.reverse:
            items = list(reversed(items))
        return SimpleNamespace(data=items)


def _provider(endpoint: FakeEmbeddingsEndpoint, **kwargs: Any) -> OllamaEmbeddings:
    client = SimpleNamespace(embeddings=endpoint)
    return OllamaEmbeddings("bge-m3", DIMS, BASE_URL, client=client, **kwargs)


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    return httpx.Response(
        status, headers=headers or {}, request=request, json={"error": RESPONSE_DETAIL}
    )


def _assert_safe_message(exc: BaseException) -> None:
    message = str(exc)
    assert "ollama-ficticio" not in message
    assert BASE_URL not in message
    assert RESPONSE_DETAIL not in message
    assert exc.__cause__ is None  # `from None`: no arrastra la excepción original


# --- Protocolo y parámetros ----------------------------------------------------------


def test_implements_embedding_provider_protocol_when_built() -> None:
    """CA-00-03: cumple el protocolo EmbeddingProvider."""
    provider = _provider(FakeEmbeddingsEndpoint())
    assert isinstance(provider, EmbeddingProvider)


def test_exposes_model_name_and_dimensions_when_built() -> None:
    """CA-00-03 / RF-10: expone model_name y dimensions configurados."""
    provider = _provider(FakeEmbeddingsEndpoint())
    assert provider.model_name == "bge-m3"
    assert provider.dimensions == DIMS


def test_builds_real_openai_client_when_no_client_injected() -> None:
    """CA-00-03: sin cliente inyectado crea un cliente OpenAI (sin llamar a la red)."""
    provider = OllamaEmbeddings("bge-m3", DIMS, BASE_URL)
    assert isinstance(provider._client, openai.OpenAI)


@pytest.mark.parametrize(("dimensions", "batch_size"), [(0, 32), (-1, 32), (DIMS, 0), (DIMS, -5)])
def test_rejects_invalid_parameters_when_not_positive(dimensions: int, batch_size: int) -> None:
    """CA-00-03: dimensiones o tamaño de lote no positivos → ValueError."""
    with pytest.raises(ValueError):
        OllamaEmbeddings(
            "bge-m3",
            dimensions,
            BASE_URL,
            batch_size=batch_size,
            client=SimpleNamespace(embeddings=FakeEmbeddingsEndpoint()),
        )


# --- Lotes y orden -------------------------------------------------------------------


def test_splits_into_batches_when_more_texts_than_batch_size() -> None:
    """RF-10: 5 textos con batch_size=2 → 3 llamadas (2, 2, 1)."""
    endpoint = FakeEmbeddingsEndpoint()
    texts = [f"texto-{i}" for i in range(5)]
    vectors = _provider(endpoint, batch_size=2).embed(texts)
    assert [len(call) for call in endpoint.calls] == [2, 2, 1]
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_preserves_order_when_response_data_is_unordered() -> None:
    """RF-10: el orden de los vectores sigue a los textos aunque `.data` venga desordenado."""
    endpoint = FakeEmbeddingsEndpoint(reverse=True)
    texts = [f"texto-{i}" for i in range(5)]
    vectors = _provider(endpoint, batch_size=2).embed(texts)
    assert [v[0] for v in vectors] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_returns_empty_list_without_calls_when_no_texts() -> None:
    """RF-10 (límite): lista vacía → [] sin llamar al servicio."""
    endpoint = FakeEmbeddingsEndpoint()
    assert _provider(endpoint).embed([]) == []
    assert endpoint.calls == []


def test_single_call_when_texts_fit_in_one_batch() -> None:
    """RF-10 (límite): exactamente batch_size textos → una sola llamada."""
    endpoint = FakeEmbeddingsEndpoint()
    _provider(endpoint, batch_size=3).embed(["a-1", "b-2", "c-3"])
    assert len(endpoint.calls) == 1


# --- Validación de la respuesta ------------------------------------------------------


def test_raises_external_error_when_vector_dimension_mismatch() -> None:
    """RF-10 / DT-03: un vector de dimensión distinta → ExternalServiceError en español."""
    endpoint = FakeEmbeddingsEndpoint(dims=DIMS + 1)
    with pytest.raises(ExternalServiceError) as info:
        _provider(endpoint).embed(["texto-1"])
    assert "dimensiones" in str(info.value)
    assert info.value.service == "ollama"


def test_raises_external_error_when_vector_count_mismatch() -> None:
    """RF-10: número de vectores distinto al de textos → ExternalServiceError."""
    endpoint = FakeEmbeddingsEndpoint(drop_one=True)
    with pytest.raises(ExternalServiceError) as info:
        _provider(endpoint).embed(["texto-1", "texto-2"])
    assert "número de embeddings" in str(info.value)


# --- Mapeo de errores del SDK --------------------------------------------------------


def test_maps_rate_limit_with_retry_after_when_429() -> None:
    """CA-00-03 / D-14: 429 con retry-after → RateLimitError con retry_after float."""
    error = openai.RateLimitError(
        "limite", response=_response(429, {"retry-after": "7"}), body=None
    )
    with pytest.raises(RateLimitError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    assert info.value.retry_after == 7.0
    assert isinstance(info.value.retry_after, float)
    _assert_safe_message(info.value)


@pytest.mark.parametrize("header", [{}, {"retry-after": "no-numerico"}])
def test_maps_rate_limit_without_retry_after_when_header_missing_or_invalid(
    header: dict[str, str],
) -> None:
    """CA-00-03 (negativo): sin cabecera válida → retry_after None."""
    error = openai.RateLimitError("limite", response=_response(429, header), body=None)
    with pytest.raises(RateLimitError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    assert info.value.retry_after is None


def test_maps_authentication_error_when_401() -> None:
    """CA-00-03: AuthenticationError de openai → AuthenticationError del dominio."""
    error = openai.AuthenticationError("no", response=_response(401), body=None)
    with pytest.raises(AuthenticationError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    _assert_safe_message(info.value)


def test_maps_not_found_to_pull_hint_when_model_missing() -> None:
    """CA-00-03: NotFoundError → ExternalServiceError que sugiere `ollama pull`."""
    error = openai.NotFoundError("no", response=_response(404), body=None)
    with pytest.raises(ExternalServiceError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    assert "ollama pull bge-m3" in str(info.value)
    _assert_safe_message(info.value)


def test_maps_connection_error_when_ollama_unreachable() -> None:
    """CA-00-03: APIConnectionError → ExternalServiceError sin la base_url."""
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    error = openai.APIConnectionError(message=f"fallo {BASE_URL}", request=request)
    with pytest.raises(ExternalServiceError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    assert type(info.value) is ExternalServiceError
    _assert_safe_message(info.value)


def test_maps_timeout_error_when_ollama_slow() -> None:
    """CA-00-03: APITimeoutError → ExternalServiceError."""
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    with pytest.raises(ExternalServiceError) as info:
        _provider(FakeEmbeddingsEndpoint(error=openai.APITimeoutError(request))).embed(["t-1"])
    _assert_safe_message(info.value)


def test_maps_generic_api_error_when_500() -> None:
    """CA-00-03: otro APIError (500) → ExternalServiceError genérico."""
    error = openai.InternalServerError(RESPONSE_DETAIL, response=_response(500), body=None)
    with pytest.raises(ExternalServiceError) as info:
        _provider(FakeEmbeddingsEndpoint(error=error)).embed(["texto-1"])
    _assert_safe_message(info.value)


# --- Integración ---------------------------------------------------------------------


def _ollama_base_url_with_bge_m3() -> str | None:
    base_url = Settings().ollama_base_url
    if not base_url:
        return None
    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        response = httpx.get(f"{root}/api/tags", timeout=2.0)
        response.raise_for_status()
        names = [m.get("name", "") for m in response.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return None
    return base_url if any(name.startswith("bge-m3") for name in names) else None


@pytest.mark.integration
def test_embeds_with_real_ollama_when_available() -> None:
    """RF-10 / CA-00-03: Ollama real con bge-m3 devuelve vectores de 1024 dimensiones."""
    base_url = _ollama_base_url_with_bge_m3()
    if base_url is None:
        pytest.skip("Ollama no disponible o sin el modelo bge-m3 (ollama pull bge-m3)")
    provider = OllamaEmbeddings("bge-m3", 1024, base_url, batch_size=2)
    vectors = provider.embed(
        [
            "El vecino solicita el empadronamiento en Villaficticia.",
            "Consulta del estado de una licencia de obra ficticia.",
            "Pago de la tasa de basuras de prueba.",
        ]
    )
    assert len(vectors) == 3
    assert all(len(v) == 1024 for v in vectors)
    assert vectors[0] != vectors[1]
