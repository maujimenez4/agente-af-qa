"""PA-316: `ConversationOut.jira_baseline` (la HU de Jira estructurada, versión de partida) y
PA-285: texto de la opción «HU nueva en la épica …» del arranque guiado.

Sobre `fake_runtime` con `run_inline` (la respuesta trae el estado final). Solo fakes de
`tests/fakes/`, sin red, sin `.env`, sin Jira ni LLM reales; datos 100 % ficticios.
"""

from pathlib import Path
from typing import Any

import pytest

from adapters.errors import RateLimitError
from api.runtime import Runtime
from core.container import Container
from core.guided_start import GuidedStart
from schemas.user_story import UserStory
from tests.fakes.api import fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.llm import FakeLLMProvider
from tests.unit.test_api_app import EVOLVE, NEED, QA, TESTS, Api

NEED_IN_EPIC = {"flow": "need", "origin": {"kind": "epic", "key": "DEMO-1", "project": "DEMO"}}


@pytest.fixture
def llm() -> FakeLLMProvider:
    return FakeLLMProvider()


@pytest.fixture
def rt(tmp_path: Path, llm: FakeLLMProvider) -> Runtime:
    return fake_runtime(tmp_path, llm=llm)


@pytest.fixture
def api(rt: Runtime) -> Api:
    a = Api(rt)
    assert a.login().status_code == 200
    return a


def _container(rt: Runtime) -> Container:
    return rt.workspace_factory().container


def _saved_baseline(rt: Runtime, conv: dict[str, Any]) -> Any:
    artifact_id = conv["versions"][-1]["artifact"]["id"]
    return (_container(rt).state_store.load(str(artifact_id)) or {}).get("baseline")


def _evolve(api: Api) -> dict[str, Any]:
    conv = api.post("/conversations", EVOLVE).json()
    assert conv["state"] == "in_review", conv
    return dict(conv)


# --- Evolución: la versión de partida, sin LLM -------------------------------------------------


def test_jira_baseline_in_evolution_is_the_saved_starting_version(
    rt: Runtime, api: Api, llm: FakeLLMProvider
) -> None:
    """PA-316: al evolucionar una HU, `jira_baseline` es la HU estructurada que el grafo guardó
    (la primera llamada al LLM, «estructurar»), válida como `UserStory`."""
    conv = _evolve(api)

    baseline = conv["jira_baseline"]
    assert baseline is not None
    saved = _saved_baseline(rt, conv)
    assert saved is not None
    assert UserStory.model_validate(baseline) == UserStory.model_validate(saved)
    assert baseline["title"] and baseline["acceptance_criteria"]
    assert llm.calls[0]["schema"] is UserStory  # estructurar la HU de Jira


def test_jira_baseline_never_calls_the_llm_on_get(
    rt: Runtime, api: Api, llm: FakeLLMProvider
) -> None:
    """PA-316: pedir `GET` varias veces no hace llamadas al LLM, ni aunque esté caído."""
    conv = _evolve(api)
    calls = len(llm.calls)
    llm.error = RateLimitError("Límite ficticio del LLM.", "llm", 5)

    bodies = [api.get(f"/conversations/{conv['id']}").json() for _ in range(3)]

    assert len(llm.calls) == calls
    assert all(b["jira_baseline"] == conv["jira_baseline"] for b in bodies)


def test_jira_baseline_stays_the_same_after_iterating(api: Api, llm: FakeLLMProvider) -> None:
    """PA-316: al iterar, la versión de Jira no cambia (no se vuelve a estructurar)."""
    conv = _evolve(api)
    structured = sum(1 for c in llm.calls if c["task"].value == "evolve_story")

    iterated = api.post(f"/conversations/{conv['id']}/iterate", {"feedback": "Cambio ficticio."})

    body = iterated.json()
    assert body["state"] == "in_review" and body["review"]["version"] == 2
    assert body["jira_baseline"] == conv["jira_baseline"]
    # Solo una llamada más (evolucionar), nunca la de estructurar.
    assert sum(1 for c in llm.calls if c["task"].value == "evolve_story") == structured + 1


def test_jira_baseline_is_in_the_conversation_list_detail_only(api: Api) -> None:
    """PA-316: el campo forma parte de `ConversationOut` (detalle) y es serializable a JSON."""
    conv = _evolve(api)

    detail = api.get(f"/conversations/{conv['id']}").json()

    assert set(detail["jira_baseline"]) >= {"title", "acceptance_criteria", "business_rules"}


# --- Null: HU nueva, QA, sin primera versión --------------------------------------------------


@pytest.mark.parametrize("body", [NEED, NEED_IN_EPIC], ids=["necesidad", "epica"])
def test_jira_baseline_is_null_for_a_new_story(api: Api, body: dict[str, Any]) -> None:
    """PA-316: en una HU nueva (necesidad o desde una épica) → `null`."""
    conv = api.post("/conversations", body).json()

    assert conv["state"] == "in_review", conv
    assert conv["jira_baseline"] is None
    assert api.get(f"/conversations/{conv['id']}").json()["jira_baseline"] is None


def test_jira_baseline_is_null_in_qa_even_with_a_saved_baseline(rt: Runtime) -> None:
    """PA-316: en QA → `null`, aunque el grafo sí guardó la versión de partida de la suite."""
    qa = Api(rt)
    assert qa.login(QA).status_code == 200

    conv = qa.post("/conversations", TESTS).json()

    assert conv["state"] == "in_review", conv
    assert _saved_baseline(rt, conv) is not None  # existe, pero no se expone en QA
    assert conv["jira_baseline"] is None


def test_jira_baseline_is_null_before_the_first_version(api: Api, llm: FakeLLMProvider) -> None:
    """PA-316: sin primera versión (el LLM falló) → `null`, sin error añadido."""
    llm.error = RateLimitError("Límite ficticio del LLM.", "llm", 5)

    conv = api.post("/conversations", EVOLVE).json()

    assert conv["state"] == "error"
    assert conv["error"]["code"] == "rate_limited"
    assert conv["jira_baseline"] is None


# --- Null tras descartar o publicar ------------------------------------------------------------


def test_jira_baseline_is_null_after_discard(api: Api) -> None:
    """PA-316: tras descartar → `null` (la versión de partida se olvida)."""
    conv = _evolve(api)

    discarded = api.post(f"/conversations/{conv['id']}/discard").json()

    assert discarded["state"] == "discarded"
    assert discarded["jira_baseline"] is None
    assert api.get(f"/conversations/{conv['id']}").json()["jira_baseline"] is None


def test_jira_baseline_is_null_after_publishing(tmp_path: Path) -> None:
    """PA-316: tras publicar en Jira (modo `live` con fakes) → `null`."""
    rt = fake_runtime(tmp_path, publish_mode="live")
    a = Api(rt)
    assert a.login().status_code == 200
    conv = _evolve(a)

    published = a.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()

    assert published["state"] == "published", published
    assert published["jira_baseline"] is None


def test_jira_baseline_is_null_after_simulated_publish(api: Api) -> None:
    """PA-316 (límite): aprobada en simulación (la conversación termina) → `null`, como tras
    publicar: ya no se itera."""
    conv = _evolve(api)

    simulated = api.post(
        f"/conversations/{conv['id']}/approve", {"fingerprint": conv["review"]["fingerprint"]}
    ).json()

    assert simulated["state"] == "simulated", simulated
    assert simulated["jira_baseline"] is None


# --- Versión de partida dañada: null sin error -------------------------------------------------


@pytest.mark.parametrize(
    "damaged",
    [{"title": 12345}, "texto-roto-ficticio", ["lista", "ficticia"], {}],
    ids=["campos-invalidos", "texto", "lista", "vacia"],
)
def test_damaged_baseline_is_null_without_error(rt: Runtime, api: Api, damaged: Any) -> None:
    """PA-316 (error): una versión de partida dañada en el `state_store` → `null`; el GET
    responde 200 y la revisión sigue disponible."""
    conv = _evolve(api)
    store = _container(rt).state_store
    artifact_id = str(conv["versions"][-1]["artifact"]["id"])
    state = store.load(artifact_id) or {}
    state["baseline"] = damaged
    store.save(artifact_id, state)

    response = api.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["jira_baseline"] is None
    assert body["state"] == "in_review" and body["review"]["version"] == 1


def test_unreadable_state_store_gives_null_baseline(
    rt: Runtime, api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PA-316 (error): si el `state_store` falla al leer → `null`, sin 500."""
    conv = _evolve(api)
    store = _container(rt).state_store

    def broken(_artifact_id: str) -> Any:
        raise OSError("almacén ficticio no disponible")

    monkeypatch.setattr(store, "load", broken)

    response = api.get(f"/conversations/{conv['id']}")

    assert response.status_code == 200
    assert response.json()["jira_baseline"] is None


# --- PA-285: «HU nueva en la épica …» ----------------------------------------------------------


def test_guided_start_labels_epic_option_as_new_story_in_epic(tmp_path: Path) -> None:
    """PA-285: el arranque guiado propone «HU nueva en la épica DEMO-1» para una épica."""
    proposal = GuidedStart(fake_container(tmp_path)).propose("algo para DEMO-1", "DEMO")

    (option,) = proposal.options
    assert option.kind == "new_story_in_epic"
    assert option.label == "HU nueva en la épica DEMO-1"
    assert not option.label.startswith("Nueva HU")


def test_guided_start_label_through_the_api(api: Api) -> None:
    """PA-285: `POST /start/propose` devuelve la misma etiqueta al frontend."""
    response = api.post("/start/propose", {"text": "algo para DEMO-1", "project": "DEMO"})

    assert response.status_code == 200, response.text
    labels = [o["label"] for o in response.json()["options"]]
    assert labels == ["HU nueva en la épica DEMO-1"]


def test_guided_start_never_writes_to_jira(tmp_path: Path) -> None:
    """PA-285: proponer el arranque no escribe nada en Jira."""
    container = fake_container(tmp_path)

    GuidedStart(container).propose("algo para DEMO-1", "DEMO")

    tracker = container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker) and tracker.writes == []


def test_published_examples_follow_the_jira_baseline_rule() -> None:
    """Contrato (spec-checker): los ejemplos que sirve la API simulada respetan PA-316: solo hay
    `jira_baseline` al evolucionar en un estado en que se itera y con alguna versión."""
    import yaml

    from api.export_openapi import OPENAPI_PATH

    def examples(node: object) -> list[dict]:
        found: list[dict] = []
        if isinstance(node, dict):
            if "jira_baseline" in node and isinstance(node.get("state"), str) and "mode" in node:
                found.append(node)
            for value in node.values():
                found += examples(value)
        elif isinstance(node, list):
            for value in node:
                found += examples(value)
        return found

    published = examples(yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8")))
    assert published
    for conversation in published:
        iterable = conversation["state"] in ("in_review", "error") or (
            conversation["state"] == "generating" and conversation.get("versions")
        )
        allowed = conversation["mode"] == "functional" and conversation["flow"] == "evolve"
        if conversation["jira_baseline"] is not None:
            assert allowed and iterable, conversation["id"]
