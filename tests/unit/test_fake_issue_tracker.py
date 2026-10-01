"""Comportamiento de FakeIssueTracker (CA-00-03)."""

import pytest

from adapters.errors import AuthenticationError, NotFoundError
from tests.fakes import FakeIssueTracker, dataset


@pytest.fixture
def tracker() -> FakeIssueTracker:
    return FakeIssueTracker()


def test_test_connection_succeeds_when_connected(tracker: FakeIssueTracker) -> None:
    """CA-00-03: test_connection no lanza con connected=True."""
    tracker.test_connection()


def test_test_connection_raises_authentication_error_when_disconnected() -> None:
    """CA-00-03: connected=False → AuthenticationError con mensaje en español."""
    with pytest.raises(AuthenticationError, match="No se pudo conectar") as info:
        FakeIssueTracker(connected=False).test_connection()
    assert info.value.service == "jira"


def test_search_returns_all_when_jql_has_no_supported_filter(tracker: FakeIssueTracker) -> None:
    """CA-00-03: JQL sin filtros reconocidos devuelve todas las incidencias."""
    keys = {i.key for i in tracker.search("project = DEMO")}
    assert keys == {"DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4"}


def test_search_filters_by_text(tracker: FakeIssueTracker) -> None:
    """CA-00-03: `text ~ "…"` filtra por summary y descripción (todas las palabras)."""
    assert [i.key for i in tracker.search('text ~ "renovaciones reservas"')] == ["DEMO-3"]
    assert [i.key for i in tracker.search('text ~ "RENOVAR"')] == ["DEMO-1", "DEMO-3"]
    assert tracker.search('text ~ "palabrainexistente"') == []


def test_search_filters_by_parent(tracker: FakeIssueTracker) -> None:
    """CA-00-03: `parent = DEMO-1` devuelve las HU hijas."""
    keys = [i.key for i in tracker.search("parent = DEMO-1")]
    assert keys == ["DEMO-2", "DEMO-3", "DEMO-4"]


def test_search_filters_by_key(tracker: FakeIssueTracker) -> None:
    """CA-00-03: `key = DEMO-4` devuelve solo esa incidencia."""
    assert [i.key for i in tracker.search("key = DEMO-4")] == ["DEMO-4"]


def test_search_respects_limit(tracker: FakeIssueTracker) -> None:
    """CA-00-03 (límite): `limit` recorta el resultado; 0 devuelve lista vacía."""
    assert len(tracker.search("project = DEMO", limit=2)) == 2
    assert tracker.search("project = DEMO", limit=0) == []


def test_get_issue_returns_detail_with_relations(tracker: FakeIssueTracker) -> None:
    """CA-00-03: get_issue devuelve descripción, parent, links y comentarios."""
    issue = tracker.get_issue("DEMO-2")
    assert issue.parent_key == "DEMO-1"
    assert [link.key for link in issue.links] == ["DEMO-3"]
    assert issue.comments


def test_get_issue_raises_not_found_for_unknown_key(tracker: FakeIssueTracker) -> None:
    """CA-00-03 (error): clave inexistente → NotFoundError."""
    with pytest.raises(NotFoundError, match="DEMO-999"):
        tracker.get_issue("DEMO-999")


def test_get_issue_returns_copy(tracker: FakeIssueTracker) -> None:
    """CA-00-03: modificar lo devuelto no altera el estado del fake."""
    tracker.get_issue("DEMO-3").comments.append("mutación")
    assert tracker.get_issue("DEMO-3").comments == []


def test_list_epics_filters_by_project(tracker: FakeIssueTracker) -> None:
    """CA-00-03: list_epics devuelve las épicas del proyecto."""
    assert [e.key for e in tracker.list_epics("DEMO")] == ["DEMO-1"]
    assert tracker.list_epics("OTRO") == []


def test_list_children_returns_epic_stories(tracker: FakeIssueTracker) -> None:
    """CA-00-03: list_children devuelve las HU de la épica."""
    assert [c.key for c in tracker.list_children("DEMO-1")] == ["DEMO-2", "DEMO-3", "DEMO-4"]
    assert tracker.list_children("DEMO-4") == []


def test_create_story_returns_new_key_with_prefix_and_records_write(
    tracker: FakeIssueTracker,
) -> None:
    """CA-00-03: create_story crea clave nueva, prefijo [HU-XX] y registra en `writes`."""
    story = dataset.renewal_story(jira_key=None)
    key = tracker.create_story(story, "DEMO-1", "DEMO")
    assert key.startswith("DEMO-")
    assert key not in dataset.STORIES
    created = tracker.get_issue(key)
    assert created.summary == "[HU-02] Renovar un préstamo"
    assert created.parent_key == "DEMO-1"
    assert tracker.writes == [
        ("create_story", {"key": key, "epic_key": "DEMO-1", "project": "DEMO"})
    ]
    assert key in {c.key for c in tracker.list_children("DEMO-1")}


def test_create_story_generates_distinct_keys(tracker: FakeIssueTracker) -> None:
    """CA-00-03: dos creaciones consecutivas generan claves distintas."""
    story = dataset.renewal_story(jira_key=None)
    assert tracker.create_story(story, None, "DEMO") != tracker.create_story(story, None, "DEMO")


def test_create_story_without_internal_id_has_no_prefix(tracker: FakeIssueTracker) -> None:
    """CA-00-03 (límite): sin internal_id el summary es solo el título."""
    story = dataset.renewal_story(jira_key=None).model_copy(update={"internal_id": None})
    key = tracker.create_story(story, None, "DEMO")
    assert tracker.get_issue(key).summary == "Renovar un préstamo"
    assert tracker.get_issue(key).parent_key is None


def test_update_story_adds_diff_comment(tracker: FakeIssueTracker) -> None:
    """CA-00-03: update_story actualiza la descripción y añade el comentario del diff."""
    story = dataset.renewal_story()
    tracker.update_story("DEMO-3", story, "## Cambios\n- Nuevo CA-02")
    issue = tracker.get_issue("DEMO-3")
    assert issue.comments[-1] == "## Cambios\n- Nuevo CA-02"
    assert issue.description_text == story.description
    assert tracker.writes == [("update_story", {"key": "DEMO-3"})]


def test_update_story_unknown_key_raises_not_found(tracker: FakeIssueTracker) -> None:
    """CA-00-03 (error): actualizar una clave inexistente falla sin registrar escritura."""
    with pytest.raises(NotFoundError):
        tracker.update_story("DEMO-999", dataset.renewal_story(), "diff")
    assert tracker.writes == []


def test_link_adds_link_and_optional_comment(tracker: FakeIssueTracker) -> None:
    """CA-00-03: link añade el vínculo, el comentario opcional y registra la escritura."""
    tracker.link("DEMO-4", "DEMO-2", "relates to", "Impacto: comparte reservas")
    issue = tracker.get_issue("DEMO-4")
    assert [(lk.link_type, lk.key) for lk in issue.links] == [("relates to", "DEMO-2")]
    assert issue.comments == ["Impacto: comparte reservas"]
    assert tracker.writes == [("link", {"from": "DEMO-4", "to": "DEMO-2", "type": "relates to"})]


def test_link_without_comment_adds_no_comment(tracker: FakeIssueTracker) -> None:
    """CA-00-03 (límite): comment_md=None no añade comentario."""
    tracker.link("DEMO-4", "DEMO-3", "blocks")
    assert tracker.get_issue("DEMO-4").comments == []


@pytest.mark.parametrize(("from_key", "to_key"), [("DEMO-4", "DEMO-999"), ("DEMO-999", "DEMO-2")])
def test_link_to_unknown_key_fails(tracker: FakeIssueTracker, from_key: str, to_key: str) -> None:
    """CA-00-03 (error): vincular con una clave inexistente → NotFoundError, sin escritura."""
    with pytest.raises(NotFoundError):
        tracker.link(from_key, to_key, "relates to")
    assert tracker.writes == []
    assert tracker.get_issue("DEMO-4").links == []


def test_writes_do_not_mutate_shared_dataset() -> None:
    """CA-00-03: cada fake trabaja sobre una copia; el dataset no cambia."""
    FakeIssueTracker().update_story("DEMO-3", dataset.renewal_story(), "diff")
    assert dataset.STORIES["DEMO-3"].comments == []
    assert FakeIssueTracker().get_issue("DEMO-3").comments == []


def test_list_projects_returns_synthetic_project() -> None:
    (project,) = FakeIssueTracker().list_projects()
    assert (project.key, project.name) == (dataset.PROJECT_KEY, dataset.PROJECT_NAME)
