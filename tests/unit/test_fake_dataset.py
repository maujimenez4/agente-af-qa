"""Coherencia del conjunto de datos sintético de los fakes (CA-00-03)."""

from schemas import test_case as tc
from schemas.user_story import UserStory
from tests.fakes import dataset
from tests.fakes.llm import renewal_test_suite

ALL_KEYS = {dataset.EPIC_KEY, *dataset.STORIES}


def test_dataset_has_epic_and_three_stories() -> None:
    """CA-00-03: épica DEMO-1 y HU DEMO-2..4."""
    assert dataset.EPIC.key == "DEMO-1"
    assert dataset.EPIC.issue_type == "Epic"
    assert set(dataset.STORIES) == {"DEMO-2", "DEMO-3", "DEMO-4"}
    assert tuple(dataset.STORIES) == dataset.STORY_KEYS


def test_stories_have_epic_as_parent() -> None:
    """CA-00-03: todas las HU cuelgan de DEMO-1 y usan el prefijo [HU-XX]."""
    for key, story in dataset.STORIES.items():
        assert story.key == key
        assert story.issue_type == "Story"
        assert story.parent_key == dataset.EPIC_KEY
        assert story.summary.startswith("[HU-")


def test_links_point_to_existing_keys() -> None:
    """CA-00-03: los vínculos del dataset apuntan a claves existentes."""
    links = [link for story in dataset.STORIES.values() for link in story.links]
    assert links
    for link in links:
        assert link.key in ALL_KEYS


def test_renewal_story_is_valid_user_story() -> None:
    """CA-00-03: renewal_story() es una UserStory válida coherente con DEMO-3."""
    story = dataset.renewal_story()
    assert UserStory.model_validate(story.model_dump()) == story
    assert story.jira_key == "DEMO-3"
    assert story.internal_id == "HU-02"
    assert dataset.STORIES["DEMO-3"].summary.startswith(f"[{story.internal_id}]")
    assert all(dep in ALL_KEYS for dep in story.dependencies)


def test_renewal_story_without_jira_key_when_requested() -> None:
    """CA-00-03: renewal_story(jira_key=None) representa una HU aún no publicada."""
    assert dataset.renewal_story(jira_key=None).jira_key is None


def test_renewal_suite_covers_all_criteria_and_rules() -> None:
    """CA-00-03: renewal_test_suite() cubre todos los CA y RN de renewal_story()."""
    story = dataset.renewal_story()
    suite = renewal_test_suite()
    assert isinstance(suite, tc.TestSuite)
    assert suite.story_jira_key == story.jira_key
    expected = {c.id for c in story.acceptance_criteria} | {r.id for r in story.business_rules}
    assert set(suite.coverage()) == expected
    assert all(cases for cases in suite.coverage().values())


def test_fictional_regulation_is_coherent_with_stories() -> None:
    """CA-00-03: el reglamento ficticio (3 reservas, 2 renovaciones, 21 días) es coherente."""
    regulation = dataset.DOCUMENTS["doc-reglamento"]["content"]
    assert "3 reservas" in regulation
    assert "2 renovaciones" in regulation
    assert "21 días" in regulation
    assert "3 reservas" in dataset.STORIES["DEMO-2"].description_text
    assert "2 renovaciones" in dataset.STORIES["DEMO-3"].description_text
    story = dataset.renewal_story()
    rules = {r.id: r.description for r in story.business_rules}
    assert "2 renovaciones" in rules["RN-01"]
    assert any("21 días" in then for c in story.acceptance_criteria for then in c.then)


def test_documents_have_title_category_and_content() -> None:
    """CA-00-03: doc-reglamento y doc-glosario con título, categoría y contenido."""
    assert set(dataset.DOCUMENTS) == {"doc-reglamento", "doc-glosario"}
    for document in dataset.DOCUMENTS.values():
        assert {"title", "category", "content"} <= set(document)
        assert "ficticio" in document["title"]
        assert document["content"]


def test_demo_users_cover_every_role() -> None:
    """CA-00-03: usuarios demo con los tres roles y contraseñas claramente ficticias."""
    roles = {user.role for _, user in dataset.DEMO_USERS.values()}
    assert roles == {"functional", "qa", "admin"}
    for username, (password, user) in dataset.DEMO_USERS.items():
        assert user.username == username
        assert "demo" in username
        assert password.startswith("demo-")


def test_summary_of_copies_basic_fields() -> None:
    """CA-00-03: summary_of reduce un IssueDetail a IssueSummary."""
    summary = dataset.summary_of(dataset.STORIES["DEMO-2"])
    assert summary.model_dump() == {
        "key": "DEMO-2",
        "summary": "[HU-01] Reservar un libro disponible",
        "issue_type": "Story",
        "status": "Hecho",
    }
