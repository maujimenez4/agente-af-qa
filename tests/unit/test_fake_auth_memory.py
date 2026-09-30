"""Comportamiento de FakeAuthProvider y FakeMemoryGenerator (CA-00-03)."""

from uuid import uuid4

import pytest

from adapters.base import User
from schemas.artifact import Artifact
from schemas.common import ArtifactStatus, ArtifactType, SourceRef
from schemas.memory import Memory
from tests.fakes import FakeAuthProvider, FakeMemoryGenerator, dataset
from tests.fakes.llm import renewal_test_suite

# --- Auth -------------------------------------------------------------------------------


@pytest.mark.parametrize("username", list(dataset.DEMO_USERS))
def test_authenticate_demo_user_with_correct_password(username: str) -> None:
    """CA-00-03: los usuarios demo se autentican y devuelven su rol."""
    password, expected = dataset.DEMO_USERS[username]
    user = FakeAuthProvider().authenticate(username, password)
    assert user == expected
    assert isinstance(user, User)


def test_authenticate_wrong_password_returns_none() -> None:
    """CA-00-03 (negativa): contraseña incorrecta → None."""
    assert FakeAuthProvider().authenticate("qa-demo", "clave-incorrecta-demo") is None


def test_authenticate_unknown_user_returns_none() -> None:
    """CA-00-03 (negativa): usuario inexistente → None."""
    assert FakeAuthProvider().authenticate("usuario-ficticio", "demo-password-qa") is None


def test_authenticate_empty_credentials_returns_none() -> None:
    """CA-00-03 (límite): credenciales vacías → None."""
    assert FakeAuthProvider().authenticate("", "") is None


def test_authenticate_password_of_another_user_returns_none() -> None:
    """CA-00-03 (negativa): la contraseña de otro usuario no sirve."""
    assert FakeAuthProvider().authenticate("admin-demo", "demo-password-qa") is None


def test_authenticated_user_is_a_copy() -> None:
    """CA-00-03: modificar el usuario devuelto no altera los usuarios del fake."""
    auth = FakeAuthProvider()
    user = auth.authenticate("af-demo", "demo-password-af")
    assert user is not None
    user.username = "mutado"
    assert auth.authenticate("af-demo", "demo-password-af") == User(
        username="af-demo", role="functional"
    )


# --- MemoryGenerator --------------------------------------------------------------------


def _artifact(content: object, artifact_type: ArtifactType, origin_key: str | None) -> Artifact:
    return Artifact(
        id=uuid4(),
        type=artifact_type,
        status=ArtifactStatus.PUBLISHED,
        version=2,
        origin_key=origin_key,
        content=content,
        created_by="af-demo",
    )


def test_generate_memory_from_user_story_artifact() -> None:
    """CA-00-03: memoria desde un Artifact con UserStory, con CA, RN y dependencias."""
    story = dataset.renewal_story().model_copy(
        update={"sources": [SourceRef(kind="rag", ref="doc-reglamento")]}
    )
    generator = FakeMemoryGenerator()
    memory = generator.generate(_artifact(story, ArtifactType.USER_STORY, "DEMO-3"))
    assert isinstance(memory, Memory)
    assert memory.jira_key == "DEMO-3"
    assert memory.artifact_type == ArtifactType.USER_STORY
    assert memory.version == 2
    assert memory.acceptance_criteria == [
        "CA-01: Renovación permitida",
        "CA-02: Renovación rechazada por reservas",
    ]
    assert [rule.split(":")[0] for rule in memory.business_rules] == ["RN-01", "RN-02"]
    assert memory.dependencies == ["DEMO-2"]
    assert memory.references == ["doc-reglamento"]
    assert generator.generated == [memory]


def test_generate_memory_uses_origin_key_when_story_has_no_jira_key() -> None:
    """CA-00-03: sin jira_key en la HU se usa origin_key del artefacto."""
    story = dataset.renewal_story(jira_key=None)
    memory = FakeMemoryGenerator().generate(_artifact(story, ArtifactType.USER_STORY, "DEMO-3"))
    assert memory.jira_key == "DEMO-3"


def test_generate_memory_from_test_suite_artifact() -> None:
    """CA-00-03: memoria desde un Artifact con TestSuite (agnóstico al tipo, RNF-25)."""
    suite = renewal_test_suite()
    memory = FakeMemoryGenerator().generate(_artifact(suite, ArtifactType.TEST_SUITE, "DEMO-3"))
    assert memory.artifact_type == ArtifactType.TEST_SUITE
    assert memory.jira_key == "DEMO-3"
    assert memory.scope == "2 casos de prueba"
    assert memory.acceptance_criteria == ["CA-01", "CA-02"]
    assert memory.business_rules == ["RN-01", "RN-02"]


def test_memory_to_markdown_contains_header_and_sections() -> None:
    """CA-00-03: to_markdown genera cabecera con metadatos y las secciones de la memoria."""
    memory = FakeMemoryGenerator().generate(
        _artifact(dataset.renewal_story(), ArtifactType.USER_STORY, "DEMO-3")
    )
    markdown = memory.to_markdown()
    assert markdown.startswith("---\njira_key: DEMO-3\nartifact_type: user_story\nversion: 2\n")
    assert "# Memoria · DEMO-3 (v2)" in markdown
    for section in ("## Objetivo", "## Reglas de negocio", "## Criterios de aceptación"):
        assert section in markdown
    assert "- CA-01: Renovación permitida" in markdown
    assert "## Referencias\n—" in markdown


def test_generate_memory_without_jira_key_fails() -> None:
    """CA-00-03 (error): sin clave de Jira (ni en la HU ni en el artefacto) falla."""
    generator = FakeMemoryGenerator()
    story = dataset.renewal_story(jira_key=None)
    with pytest.raises(ValueError, match="clave de Jira"):
        generator.generate(_artifact(story, ArtifactType.USER_STORY, None))
    assert generator.generated == []
