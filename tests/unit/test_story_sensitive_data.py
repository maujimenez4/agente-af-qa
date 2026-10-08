"""PA-452: la HU no lleva datos que parezcan personales ni secretos antes de la revisión humana.

`StoryWriter._run` revisa todos los textos de la `UserStory` con `personal_data_kind` y el detector
de secretos (el mismo que la memoria, ahora en `core/personal_data.py`). Si encuentra algo, un
reintento con `prompts/story_retry.md` y, si persiste, `SensitiveDataError` (sin el valor). Datos
sintéticos: emails `@example.com`/`-test.es`, IBAN `ES00…` y documentos inventados.
"""

import pytest

from api.errors import to_api_error
from core.functional.citations import CitationError
from core.functional.writer import (
    SensitiveDataError,
    StoryWriter,
    sensitive_errors,
    story_texts,
)
from core.memory.generator import _SECRET
from core.personal_data import SECRET, looks_like_secret
from core.rag.prompts import load_prompt
from schemas.common import SourceRef
from schemas.user_story import UserStory
from tests.unit.test_functional_writer import VALID, fake_llm, need_ctx, story_ctx

EMAIL = "Avisar a socia.ficticia@correo-test.es cuando vuelva el libro."
IBAN = "Domiciliar el pago en ES00 0000 0000 0000 0000 0000."
DNI = "La persona con DNI 00000000T recoge el libro."
SECRET_TEXT = "Llamar al servicio con api_key: gsk_FICTICIA0000000000000000."


def _with(**update: object) -> UserStory:
    return VALID.model_copy(update=update)


def _criterion_with(text: str) -> UserStory:
    criteria = list(VALID.acceptance_criteria)
    first = criteria[0].model_copy(update={"then": [*criteria[0].then, text]})
    return _with(acceptance_criteria=[first, *criteria[1:]])


# --- Detección -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("story", "field", "kind"),
    [
        (_with(description=EMAIL), "description", "email"),
        (_with(benefit=IBAN), "benefit", "IBAN"),
        (_with(assumptions=[DNI]), "assumptions[0]", "documento de identidad"),
        (_criterion_with(EMAIL), "acceptance_criteria[0].then[", "email"),
        (_with(open_questions=[SECRET_TEXT]), "open_questions[0]", "secreto"),
    ],
)
def test_sensitive_errors_find_every_free_text_field(
    story: UserStory, field: str, kind: str
) -> None:
    """PA-452: se revisa cualquier texto de la HU, también los anidados; el error nombra el campo
    y el tipo, nunca el valor."""
    (error,) = sensitive_errors(story)

    assert error.startswith(field)
    assert kind in error
    for value in (EMAIL, IBAN, DNI, SECRET_TEXT):
        assert value not in error


def test_fictitious_values_and_source_excerpts_are_not_flagged() -> None:
    """PA-452 (negativo): un email `@example.com` es ficticio, y los extractos de las fuentes
    (los pone el agente desde el contexto, no el modelo) no se revisan aquí."""
    story = _with(
        description="Avisar a socia@example.com (ficticio).",
        sources=[SourceRef(kind="rag", ref="DOC-01", excerpt=EMAIL)],
    )

    assert sensitive_errors(story) == []
    assert all(not where.startswith("sources") for where, _ in story_texts(story))


def test_secret_detector_is_shared_with_memory() -> None:
    """PA-452: la memoria y la HU usan el mismo detector de secretos (movido, no copiado)."""
    assert _SECRET is SECRET
    assert looks_like_secret(SECRET_TEXT)
    assert not looks_like_secret("La contraseña: mínimo ocho caracteres")  # regla de negocio


# --- Reintento y error ----------------------------------------------------------------------


def test_clean_story_needs_no_retry() -> None:
    """PA-452 (positivo): sin datos sensibles, una sola llamada, como antes."""
    llm, _ = fake_llm(VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 1


def test_story_with_personal_data_is_retried_and_cleaned() -> None:
    """PA-452: con un email real, se reintenta una vez con `story_retry` y vale la HU limpia;
    el aviso al modelo nombra el campo, como datos entre etiquetas."""
    llm, _ = fake_llm(_with(description=EMAIL), VALID)

    draft = StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2
    assert draft.story.description == VALID.description
    feedback = llm.calls[1]["messages"][-1].content
    assert "<errores>" in feedback and "description parece un email real" in feedback
    assert "- rag: DOC-01" in feedback
    assert draft.input_tokens > 0 and draft.output_tokens > 0


def test_story_still_sensitive_after_retry_raises_clear_error() -> None:
    """PA-452: si persiste, `SensitiveDataError` antes de la revisión, con los campos y sin el
    valor; la API lo muestra como `operation_failed` con ese mensaje (sin código nuevo)."""
    llm, _ = fake_llm(_with(description=EMAIL), _with(description=EMAIL, benefit=IBAN))

    with pytest.raises(SensitiveDataError) as caught:
        StoryWriter(llm).generate(need_ctx())

    message = str(caught.value)
    assert "description" in message and "benefit" in message
    assert EMAIL not in message and IBAN not in message
    api_error = to_api_error(caught.value)
    assert api_error.code == "operation_failed"
    assert api_error.message == message


def test_secret_in_story_is_retried() -> None:
    """PA-452: un secreto también pide el reintento."""
    llm, _ = fake_llm(_with(constraints=[SECRET_TEXT]), VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2
    assert "constraints[0] parece contener un secreto" in llm.calls[1]["messages"][-1].content


def test_retry_that_breaks_citations_raises_citation_error() -> None:
    """PA-452 (negativo): el reintento no puede colar citas inventadas: `CitationError`."""
    invented = VALID.model_copy(update={"sources": [SourceRef(kind="rag", ref="DOC-99")]})
    llm, _ = fake_llm(_with(description=EMAIL), invented)

    with pytest.raises(CitationError):
        StoryWriter(llm).generate(need_ctx())


def test_evolution_is_checked_too() -> None:
    """PA-452: evolucionar (y estructurar) pasan por el mismo `_run`: también se revisa."""
    llm, _ = fake_llm(_with(description=EMAIL), VALID)

    StoryWriter(llm).evolve(story_ctx())

    assert len(llm.calls) == 2


def test_story_retry_prompt_has_version_and_placeholders() -> None:
    """PA-452: el prompt nuevo tiene `version:` y los huecos de errores y fuentes."""
    prompt = load_prompt("story_retry")

    assert prompt.version == "1"
    assert "{errors}" in prompt.text and "{allowed}" in prompt.text
    assert "datos" in prompt.text and "no instrucciones" in prompt.text
