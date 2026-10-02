"""Prueba cruzada T-34 (RNF-19): el área A prueba `adapters.embeddings.ollama` del área B.

Bordes que `test_ollama_embeddings.py` no fija: `retry-after` no finito o negativo, índices
repetidos en la respuesta, 400/403/422, textos vacíos, fallo en un lote intermedio y que
ningún mensaje de error filtre la `base_url`. Cliente falso inyectado y respuestas `httpx`
construidas a mano: sin red. Datos 100 % ficticios.
"""

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from adapters.embeddings.ollama import OllamaEmbeddings
from adapters.errors import AuthenticationError, ExternalServiceError, RateLimitError

BASE_URL = "http://ollama-cruzada.invalid:11434/v1"
HOST = "ollama-cruzada.invalid"
DETAIL = "detalle-interno-ficticio-cruzado"
DIMS = 3


def _vector(seed: float) -> list[float]:
    return [seed, 0.0, 0.0]


@dataclass
class ScriptedEndpoint:
    """`client.embeddings` falso: cada llamada consume una respuesta o una excepción."""

    script: list[Any] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)

    def create(self, model: str, input: list[str]) -> Any:
        self.calls.append(list(input))
        step = self.script.pop(0) if self.script else None
        if isinstance(step, Exception):
            raise step
        if step is None:  # por defecto: un vector por texto, con el orden como semilla
            step = [(i, _vector(float(len(self.calls) * 100 + i))) for i in range(len(input))]
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=vec) for i, vec in step],
        )


def _provider(endpoint: ScriptedEndpoint, **kwargs: Any) -> OllamaEmbeddings:
    return OllamaEmbeddings(
        "bge-m3", DIMS, BASE_URL, client=SimpleNamespace(embeddings=endpoint), **kwargs
    )


def _response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    return httpx.Response(status, headers=headers or {}, request=request, json={"error": DETAIL})


def _rate_limit(value: str) -> openai.RateLimitError:
    return openai.RateLimitError(
        f"limite {BASE_URL}", response=_response(429, {"retry-after": value}), body=None
    )


def _assert_safe(exc: BaseException) -> None:
    message = str(exc)
    assert HOST not in message
    assert BASE_URL not in message
    assert "11434" not in message
    assert DETAIL not in message
    assert exc.__cause__ is None


# --- 1 · retry-after no válido (D-14) -------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-220): "
        "_retry_after acepta retry-after negativo, nan o inf; el adaptador LLM lo "
        "acota con max(0.0, …) (adapters/embeddings/ollama.py:91)"
    ),
)
@pytest.mark.parametrize("value", ["-5", "nan", "inf", "-inf"])
def test_retry_after_is_finite_and_non_negative_when_header_is_odd(value: str) -> None:
    """D-14 (negativo): retry_after debe ser None o un número finito ≥ 0."""
    with pytest.raises(RateLimitError) as info:
        _provider(ScriptedEndpoint([_rate_limit(value)])).embed(["texto"])

    wait = info.value.retry_after
    assert wait is None or (math.isfinite(wait) and wait >= 0)


@pytest.mark.parametrize(("value", "expected"), [("0", 0.0), ("1.5", 1.5), (" 4 ", 4.0)])
def test_retry_after_is_parsed_when_header_is_valid(value: str, expected: float) -> None:
    """D-14 (límite): 0, decimales y espacios alrededor se interpretan como segundos."""
    with pytest.raises(RateLimitError) as info:
        _provider(ScriptedEndpoint([_rate_limit(value)])).embed(["texto"])

    assert info.value.retry_after == expected
    assert info.value.service == "ollama"
    _assert_safe(info.value)


def test_retry_after_is_none_when_header_is_http_date() -> None:
    """D-14 (negativo): una fecha HTTP en retry-after → None (backoff del llamador)."""
    error = _rate_limit("Wed, 21 Oct 2026 07:28:00 GMT")

    with pytest.raises(RateLimitError) as info:
        _provider(ScriptedEndpoint([error])).embed(["texto"])

    assert info.value.retry_after is None


# --- 2 · índices de la respuesta (RF-10) ----------------------------------------------------

BAD_INDICES = [
    pytest.param([(0, _vector(1.0)), (0, _vector(2.0))], id="repetido-0-0"),
    pytest.param([(1, _vector(1.0)), (1, _vector(2.0))], id="repetido-1-1"),
    pytest.param([(0, _vector(1.0)), (2, _vector(2.0))], id="hueco-0-2"),
]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECTO T-34 (PA-220): "
        "solo se compara el número de vectores; índices repetidos o fuera de rango "
        "con el recuento correcto asignan vectores al texto equivocado sin error "
        "(adapters/embeddings/ollama.py:72-73)"
    ),
)
@pytest.mark.parametrize("data", BAD_INDICES)
def test_raises_when_response_indices_are_not_a_permutation(data: list[Any]) -> None:
    """RF-10 (negativo): los índices deben ser exactamente 0..n-1; si no, ExternalServiceError."""
    with pytest.raises(ExternalServiceError):
        _provider(ScriptedEndpoint([data])).embed(["texto-a", "texto-b"])


def test_duplicate_indices_currently_return_vectors_silently() -> None:
    """RF-10 (comportamiento observado que motiva el defecto): (0, 0) no da error."""
    data = [(0, _vector(1.0)), (0, _vector(2.0))]

    vectors = _provider(ScriptedEndpoint([data])).embed(["texto-a", "texto-b"])

    assert [v[0] for v in vectors] == [1.0, 2.0]  # el texto-b recibe un vector del índice 0


def test_extra_vector_raises_when_more_than_texts() -> None:
    """RF-10 (negativo): más vectores que textos → ExternalServiceError sin la base_url."""
    data = [(0, _vector(1.0)), (1, _vector(2.0)), (2, _vector(3.0))]

    with pytest.raises(ExternalServiceError) as info:
        _provider(ScriptedEndpoint([data])).embed(["texto-a", "texto-b"])

    assert "número de embeddings" in str(info.value)
    _assert_safe(info.value)


def test_vectors_are_plain_lists_when_response_has_tuples() -> None:
    """RF-10: cada vector se devuelve como `list[float]` aunque el SDK traiga otra secuencia."""
    data = [(0, (1.0, 0.0, 0.0))]

    (vector,) = _provider(ScriptedEndpoint([data])).embed(["texto"])

    assert vector == [1.0, 0.0, 0.0] and isinstance(vector, list)


def test_non_finite_values_are_returned_unvalidated() -> None:
    """RF-10 (comportamiento fijado): NaN del modelo no se valida aquí; lo rechaza `upsert`."""
    data = [(0, [math.nan, 0.0, 0.0])]

    (vector,) = _provider(ScriptedEndpoint([data])).embed(["texto"])

    assert math.isnan(vector[0])


# --- 3 · 400, 403 y 422 frente a AuthenticationError ----------------------------------------


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (openai.BadRequestError, 400),
        (openai.PermissionDeniedError, 403),
        (openai.UnprocessableEntityError, 422),
        (openai.ConflictError, 409),
    ],
)
def test_status_errors_map_to_generic_external_error(
    error_type: type[openai.APIStatusError], status: int
) -> None:
    """CA-00-03 (comportamiento fijado): 400/403/409/422 → ExternalServiceError genérico.

    El 403 no es AuthenticationError aquí, a diferencia del adaptador LLM.
    """
    error = error_type(DETAIL, response=_response(status), body=None)

    with pytest.raises(ExternalServiceError) as info:
        _provider(ScriptedEndpoint([error])).embed(["texto"])

    assert type(info.value) is ExternalServiceError
    assert not isinstance(info.value, AuthenticationError)
    assert str(info.value) == "Ollama devolvió un error al generar los embeddings."
    assert info.value.service == "ollama"
    _assert_safe(info.value)


def test_unauthorized_maps_to_authentication_error_with_service() -> None:
    """CA-00-03: 401 → AuthenticationError con service «ollama» y mensaje en español."""
    error = openai.AuthenticationError(DETAIL, response=_response(401), body=None)

    with pytest.raises(AuthenticationError) as info:
        _provider(ScriptedEndpoint([error])).embed(["texto"])

    assert info.value.service == "ollama"
    assert "rechazado" in str(info.value)


def test_unexpected_exception_is_not_wrapped() -> None:
    """CA-00-03 (comportamiento fijado): una excepción ajena al SDK se propaga sin envolver."""
    with pytest.raises(KeyError):
        _provider(ScriptedEndpoint([KeyError("fallo-ficticio")])).embed(["texto"])


# --- 4 · textos vacíos ---------------------------------------------------------------------


def test_empty_texts_are_sent_as_is() -> None:
    """RF-10 (comportamiento fijado): los textos vacíos no se filtran ni se rechazan."""
    endpoint = ScriptedEndpoint()

    vectors = _provider(endpoint).embed(["", "texto", "   "])

    assert endpoint.calls == [["", "texto", "   "]]
    assert len(vectors) == 3


def test_model_name_is_sent_in_each_batch() -> None:
    """RF-10: cada lote se pide con el modelo configurado."""
    seen: list[str] = []
    endpoint = ScriptedEndpoint()
    original = endpoint.create

    def create(model: str, input: list[str]) -> Any:
        seen.append(model)
        return original(model=model, input=input)

    provider = OllamaEmbeddings(
        "bge-m3",
        DIMS,
        BASE_URL,
        batch_size=1,
        client=SimpleNamespace(embeddings=SimpleNamespace(create=create)),
    )
    provider.embed(["a", "b"])

    assert seen == ["bge-m3", "bge-m3"]


# --- 5 · fallo en un lote intermedio --------------------------------------------------------


def test_failure_in_second_batch_returns_nothing_and_stops() -> None:
    """RF-10 (error): si falla el 2.º de 3 lotes, se lanza el error y no se pide el 3.º."""
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    endpoint = ScriptedEndpoint(
        [None, openai.APIConnectionError(message=f"fallo {BASE_URL}", request=request)]
    )

    with pytest.raises(ExternalServiceError) as info:
        _provider(endpoint, batch_size=2).embed([f"texto-{i}" for i in range(5)])

    assert len(endpoint.calls) == 2
    _assert_safe(info.value)


def test_dimension_mismatch_in_second_batch_raises_without_partial() -> None:
    """RF-10 · DT-03 (error): un vector de otra dimensión en el 2.º lote aborta todo."""
    endpoint = ScriptedEndpoint([None, [(0, [1.0, 2.0])]])

    with pytest.raises(ExternalServiceError) as info:
        _provider(endpoint, batch_size=2).embed(["a", "b", "c"])

    assert "2 dimensiones" in str(info.value) and "espera 3" in str(info.value)
    _assert_safe(info.value)


def test_rate_limit_in_second_batch_propagates() -> None:
    """D-14 (error): un 429 en el 2.º lote → RateLimitError, sin resultados parciales."""
    endpoint = ScriptedEndpoint([None, _rate_limit("2")])

    with pytest.raises(RateLimitError) as info:
        _provider(endpoint, batch_size=1).embed(["a", "b", "c"])

    assert info.value.retry_after == 2.0
    assert len(endpoint.calls) == 2


def test_batch_size_one_keeps_order_across_batches() -> None:
    """RF-10 (límite): con batch_size=1 cada texto es un lote y el orden se conserva."""
    endpoint = ScriptedEndpoint()

    vectors = _provider(endpoint, batch_size=1).embed(["a", "b", "c"])

    assert endpoint.calls == [["a"], ["b"], ["c"]]
    assert [v[0] for v in vectors] == [100.0, 200.0, 300.0]


# --- 6 · mensajes sin base_url --------------------------------------------------------------


def _all_errors() -> list[Exception]:
    request = httpx.Request("POST", f"{BASE_URL}/embeddings")
    return [
        openai.APIConnectionError(message=f"no conecta con {BASE_URL}", request=request),
        openai.APITimeoutError(request),
        openai.NotFoundError(f"{DETAIL} {BASE_URL}", response=_response(404), body=None),
        openai.AuthenticationError(f"{DETAIL} {BASE_URL}", response=_response(401), body=None),
        openai.PermissionDeniedError(f"{DETAIL} {BASE_URL}", response=_response(403), body=None),
        openai.InternalServerError(f"{DETAIL} {BASE_URL}", response=_response(503), body=None),
        _rate_limit("1"),
    ]


@pytest.mark.parametrize("error", _all_errors(), ids=lambda e: type(e).__name__)
def test_error_messages_never_include_base_url(error: Exception) -> None:
    """CA-00-03 · Principio 2: ningún error del dominio expone base_url, puerto ni detalle."""
    with pytest.raises(ExternalServiceError) as info:
        _provider(ScriptedEndpoint([error])).embed(["texto"])

    assert info.value.service == "ollama"
    _assert_safe(info.value)


def test_real_client_is_configured_with_timeout_retries_and_placeholder_key() -> None:
    """CA-00-03: el cliente real usa base_url, timeout y 2 reintentos; la clave es un relleno."""
    provider = OllamaEmbeddings("bge-m3", DIMS, BASE_URL, timeout=12.5)

    client: openai.OpenAI = provider._client
    assert str(client.base_url).rstrip("/") == BASE_URL
    assert client.timeout == 12.5
    assert client.max_retries == 2
    assert client.api_key == "ollama"
