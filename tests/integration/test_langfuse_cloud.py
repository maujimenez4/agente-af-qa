"""Trazas contra Langfuse Cloud real (T-40 · RNF-24 · DT-09).

Se salta si faltan `LANGFUSE_PUBLIC_KEY` o `LANGFUSE_SECRET_KEY` (entorno o `.env`, leídos solo
mediante `core/config.py`). Manda una traza sintética (sin LLM ni Jira, sin contenido: el
interruptor va desactivado) y comprueba las credenciales con `auth_check`. Nunca imprime claves.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from core.config import Settings
from core.tracing import TracingVectorStore, operation, secret_mask
from tests.fakes.embeddings import FakeEmbeddingProvider
from tests.fakes.vector_store import FakeVectorStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    settings = Settings()
    missing = [
        name
        for name, value in (
            ("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key),
            ("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key),
        )
        if value is None or not value.get_secret_value()
    ]
    if missing:
        pytest.skip(f"Faltan variables de Langfuse: {', '.join(missing)}")
    return settings


@pytest.fixture
def live_tracer(live_settings: Settings) -> Iterator[object]:
    from adapters.observability.langfuse import LangfuseTracer

    assert live_settings.langfuse_public_key and live_settings.langfuse_secret_key
    tracer = LangfuseTracer(
        public_key=live_settings.langfuse_public_key,
        secret_key=live_settings.langfuse_secret_key,
        host=live_settings.langfuse_host,
        capture_content=False,
        mask=secret_mask(live_settings.secret_values()),
    )
    yield tracer
    tracer.shutdown()


def test_langfuse_credentials_are_valid_when_live(live_tracer: object) -> None:
    """RNF-24: las claves de Langfuse Cloud son válidas (`auth_check`)."""
    assert live_tracer._client.auth_check() is True  # type: ignore[attr-defined]


def test_synthetic_trace_is_sent_without_errors_when_live(live_tracer: object) -> None:
    """RNF-24: una traza sintética (operación con un paso del RAG) se envía sin errores."""
    embeddings = FakeEmbeddingProvider()
    store = FakeVectorStore()
    session = f"prueba-integracion-{uuid4()}"
    (query,) = embeddings.embed(["consulta ficticia"])
    with operation(
        live_tracer,  # type: ignore[arg-type]
        "prueba_integracion",
        session_id=session,
        user_id="usuario-ficticio",
        mode="functional",
        flow="need",
        project="DEMO",
    ) as op:
        assert op is not None
        assert TracingVectorStore(store).search(query, "consulta ficticia", 3) == []
    live_tracer._client.flush()  # type: ignore[attr-defined]  # síncrono: falla si no se envía
