"""PA-453 · `update_story` a medias: la HU se actualiza en Jira y falla el comentario del diff.

La auditoría `interrupted` guarda la clave ya escrita y, tras reiniciar la API, la conversación
aprobada sin publicación terminada se ve como error (sin decir que no se escribió nada).
Datos ficticios (proyecto DEMO).
"""

from pathlib import Path

import httpx
import pytest
from langgraph.types import Command

from adapters.errors import PublishError
from adapters.jira.tracker import PartialPublishError
from api.service import PUBLISH_UNFINISHED, RESTART
from core.audit import InMemoryAuditTrail
from core.graph import Origin, build_graph, initial_state
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fakes.test_management import FakeTestManagement
from tests.unit.test_api_app import QA, Api
from tests.unit.test_jira_tracker import error_response, make_tracker

STORY_ORIGIN: Origin = {"kind": "story", "key": "DEMO-3"}


# --- Adaptador ---------------------------------------------------------------------------------


def test_update_story_reports_written_key_when_comment_fails() -> None:
    """PA-453: el PUT va bien y el comentario falla → error con la clave ya escrita."""
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        if request.method == "PUT":
            return httpx.Response(204)
        return error_response(500)

    with pytest.raises(PartialPublishError) as exc:
        make_tracker(handler).update_story("DEMO-3", dataset.renewal_story(), "Diff ficticio")

    assert isinstance(exc.value, PublishError)
    assert exc.value.written_keys == ["DEMO-3"]
    assert "se ha actualizado" in str(exc.value)
    assert requests == ["PUT", "POST"]


def test_update_story_failing_put_is_not_partial() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return error_response(500)

    with pytest.raises(PublishError) as exc:
        make_tracker(handler).update_story("DEMO-3", dataset.renewal_story(), "Diff ficticio")
    assert not isinstance(exc.value, PartialPublishError)


# --- Grafo ---------------------------------------------------------------------------------------


class CommentFailsTracker(FakeIssueTracker):
    """Actualiza la HU y falla al comentar, como el real (`PartialPublishError`)."""

    def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
        super().update_story(key, story, diff_comment_md)
        raise PartialPublishError(
            f"La HU {key} se ha actualizado, pero no se pudo añadir el comentario.",
            written_keys=[key],
        )


def test_interrupted_publish_audits_the_key_already_written(tmp_path: Path) -> None:
    """PA-453: la auditoría `interrupted` lleva la clave de la HU ya actualizada."""
    tracker = CommentFailsTracker()
    container = fake_container(tmp_path, issue_tracker=tracker)
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-pa453"}}
    graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    fingerprint = task.interrupts[-1].value["fingerprint"]

    with pytest.raises(PartialPublishError):
        graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), config)

    assert ("update_story", {"key": "DEMO-3"}) in tracker.writes
    audit = container.audit
    assert isinstance(audit, InMemoryAuditTrail)
    publish = [e for e in audit.recorded if e.action == "publish"][-1]
    assert publish.detail["interrupted"] is True
    assert publish.detail["error_type"] == "PartialPublishError"
    assert publish.jira_keys == ["DEMO-3"]


def test_interrupted_publish_without_written_keys_audits_none(tmp_path: Path) -> None:
    """Un fallo sin claves escritas sigue auditándose sin `jira_keys`."""

    class PutFails(FakeIssueTracker):
        def update_story(self, key: str, story: UserStory, diff_comment_md: str) -> None:
            raise PublishError("Jira no responde (ficticio).")

    container = fake_container(tmp_path, issue_tracker=PutFails())
    graph = build_graph(container)
    config = {"configurable": {"thread_id": "hilo-pa453-b"}}
    graph.invoke(initial_state("af-demo", "functional", STORY_ORIGIN), config)
    (task,) = [t for t in graph.get_state(config).tasks if t.interrupts]
    fingerprint = task.interrupts[-1].value["fingerprint"]
    with pytest.raises(PublishError):
        graph.invoke(Command(resume={"decision": "approve", "fingerprint": fingerprint}), config)

    audit = container.audit
    assert isinstance(audit, InMemoryAuditTrail)
    publish = [e for e in audit.recorded if e.action == "publish"][-1]
    assert publish.detail["interrupted"] is True and publish.jira_keys == []


# --- API tras reiniciar --------------------------------------------------------------------------


def test_approved_conversation_without_run_shows_unfinished_publication(tmp_path: Path) -> None:
    """PA-453: la HU se actualiza y falla el comentario; tras reiniciar la API (sin operación en
    memoria), la conversación aprobada se ve como error y el mensaje no dice que no se escribió
    nada en Jira."""
    container = fake_container(
        tmp_path, require_actor=True, publish_mode="live", issue_tracker=CommentFailsTracker()
    )
    rt = fake_runtime(tmp_path, container=container)
    api = Api(rt)
    assert api.login().status_code == 200
    conv = api.post(
        "/conversations",
        {"flow": "evolve", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}},
    ).json()
    fingerprint = api.get(f"/conversations/{conv['id']}").json()["review"]["fingerprint"]
    api.post(f"/conversations/{conv['id']}/approve", {"fingerprint": fingerprint})
    rt.runs._runs.clear()  # como al reiniciar la API: no queda ninguna operación

    after = api.get(f"/conversations/{conv['id']}").json()

    assert after["state"] == "error"
    assert after["error"]["code"] == "restart"
    assert after["error"]["message"] == PUBLISH_UNFINISHED
    assert "nada se ha escrito" not in PUBLISH_UNFINISHED
    assert "nada se ha escrito" in RESTART


@pytest.mark.parametrize("restart", [False, True], ids=["en-memoria", "tras-reiniciar"])
def test_partially_published_suite_stays_approved_with_failed_ids(
    tmp_path: Path, restart: bool
) -> None:
    """PA-324 (no regresión de PA-453): una suite con algún caso sin crear termina `publish`;
    la conversación sigue `approved` con sus fallos, también tras reiniciar la API."""
    container = fake_container(
        tmp_path,
        require_actor=True,
        publish_mode="live",
        test_management=FakeTestManagement(fail_case_ids={"CP-01"}),
    )
    rt = fake_runtime(tmp_path, container=container)
    api = Api(rt)
    assert api.login(QA).status_code == 200
    conv = api.post(
        "/conversations",
        {"flow": "tests", "origin": {"kind": "story", "key": "DEMO-3", "project": "DEMO"}},
    ).json()
    fingerprint = api.get(f"/conversations/{conv['id']}").json()["review"]["fingerprint"]
    api.post(f"/conversations/{conv['id']}/approve", {"fingerprint": fingerprint})
    if restart:
        rt.runs._runs.clear()

    after = api.get(f"/conversations/{conv['id']}").json()

    assert after["state"] == "approved"
    assert after["error"] is None
    assert after["result"]["failed_ids"] == ["CP-01"]
    assert after["result"]["published_keys"]


def test_messages_do_not_offer_to_discard_a_conversation_in_error() -> None:
    """Auditoría 2026-10-08: una conversación en error no se puede descartar; los textos de la
    cancelación y del tope de rechazos ofrecen empezar una conversación nueva."""
    import inspect

    from api.cancel import CANCELLED_MESSAGE
    from core.graph import nodes

    assert "descartar" not in CANCELLED_MESSAGE
    assert "conversación nueva" in CANCELLED_MESSAGE
    source = inspect.getsource(nodes.GraphNodes.human_review)
    assert "descarta la" not in source
    assert "empieza una " in source
