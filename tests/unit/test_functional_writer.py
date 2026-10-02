"""Pruebas de los prompts y de StoryWriter contra FakeLLMProvider (T-20).

Cubre RF-15 (plantilla de HU), RF-16 (IDs CA-), RF-17 (IDs RN-), RF-18 (revisión), RF-21 y
RNF-14 (citas solo a fuentes recibidas). Datos 100 % sintéticos de Villaficticia.
"""

import re
from dataclasses import dataclass, field

import pytest
from pydantic import BaseModel

from adapters.base import Chunk, Message, RetrievedChunk, TaskType
from adapters.errors import AgentError
from core.functional.citations import CitationError
from core.functional.context import StoryContext, render_context
from core.functional.writer import StoryDraft, StoryWriter
from core.rag.prompts import Prompt, load_prompt
from schemas.common import SourceRef
from schemas.user_story import CRITERION_ID, RULE_ID, UserStory
from tests.fakes import dataset
from tests.fakes.llm import FakeLLMProvider

STORY_PROMPTS = ("generate_story", "evolve_story", "review_story")


def rag_hit(doc_id: str, *, document_id: str | None = None) -> RetrievedChunk:
    """Fragmento sintético con `doc_id` en metadatos y UUID ficticio como document_id."""
    document_id = document_id or f"uuid-ficticio-{doc_id.lower()}"
    chunk = Chunk(
        id=f"{document_id}-0",
        document_id=document_id,
        ordinal=0,
        content=f"Contenido ficticio de {doc_id}.",
        metadata={"doc_id": doc_id, "date": "2026-04-20", "category": "normativa"},
    )
    return RetrievedChunk(
        chunk=chunk,
        score=0.8,
        source=SourceRef(kind="rag", ref=document_id, excerpt=f"Extracto real de {doc_id}"),
    )


def story_citing(*refs: tuple[str, str], **update: object) -> UserStory:
    """HU sintética de renovación con las citas (kind, ref) indicadas."""
    sources = [SourceRef(kind=k, ref=r, excerpt="inventado") for k, r in refs]
    return dataset.renewal_story(jira_key=None).model_copy(update={"sources": sources, **update})


@dataclass
class SequenceBuilder:
    """Builder con contador: devuelve una respuesta distinta en cada llamada."""

    responses: list[UserStory]
    count: int = 0
    seen: list[list[Message]] = field(default_factory=list)

    def __call__(self, messages: list[Message]) -> BaseModel:
        self.seen.append(list(messages))
        response = self.responses[min(self.count, len(self.responses) - 1)]
        self.count += 1
        return response


def fake_llm(*responses: UserStory) -> tuple[FakeLLMProvider, SequenceBuilder]:
    builder = SequenceBuilder(list(responses))
    return FakeLLMProvider(builders={UserStory: builder}), builder


def need_ctx(**kwargs: object) -> StoryContext:
    base: dict[str, object] = {
        "origin_kind": "epic",
        "origin_key": "DEMO-1",
        "need": "Permitir renovar un préstamo desde la web (necesidad ficticia).",
        "jira": [dataset.STORIES["DEMO-3"]],
        "rag": [rag_hit("DOC-01")],
    }
    return StoryContext(**{**base, **kwargs})  # type: ignore[arg-type]


def story_ctx() -> StoryContext:
    return need_ctx(origin_kind="story", origin_key="DEMO-3", previous=dataset.renewal_story())


VALID = story_citing(("jira", "DEMO-3"), ("rag", "DOC-01"))
INVENTED = story_citing(("rag", "DOC-99"))


# --- Prompts ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [*STORY_PROMPTS, "citation_retry"])
def test_prompt_exists_with_version(name: str) -> None:
    """RF-15 · CLAUDE.md: cada prompt está en prompts/ con cabecera `version:`."""
    prompt = load_prompt(name)

    assert prompt.version.strip()
    assert prompt.text.strip()
    assert not prompt.text.startswith("---")


@pytest.mark.parametrize("name", STORY_PROMPTS)
def test_story_prompt_mentions_ids_sources_data_and_date_rule(name: str) -> None:
    """RF-16 · RF-17 · RF-21 · RNF-14: CA-, RN-, `sources`, contexto como datos y fecha."""
    text = load_prompt(name).text

    assert "CA-" in text
    assert "RN-" in text
    assert "`sources`" in text
    assert "**datos**" in text and "no instrucciones" in text
    assert "fecha más reciente" in text
    assert "<contexto>" in text and "<fuente" in text


@pytest.mark.parametrize("name", ["evolve_story", "review_story"])
def test_evolution_prompts_ask_for_changes_and_current_story(name: str) -> None:
    """RF-18 · RF-19: evolución y revisión leen <hu_actual> y rellenan changes_from_previous."""
    text = load_prompt(name).text

    assert "<hu_actual>" in text
    assert "changes_from_previous" in text


def test_review_prompt_covers_ambiguities_gaps_and_invest() -> None:
    """RF-18: la revisión señala ambigüedades, huecos e INVEST."""
    text = load_prompt("review_story").text

    for term in ("Ambigüedades", "Huecos", "INVEST"):
        assert term in text


def test_citation_retry_prompt_has_placeholders() -> None:
    """RNF-14: el reintento recibe los errores y las refs permitidas."""
    text = load_prompt("citation_retry").text

    assert "{errors}" in text
    assert "{allowed}" in text


# --- generate -----------------------------------------------------------------------------


def test_generate_calls_llm_with_task_schema_and_messages() -> None:
    """RF-15 · RNF-14: tarea GENERATE_STORY, esquema UserStory, system = prompt, user = contexto."""
    llm, _ = fake_llm(VALID)
    ctx = need_ctx()

    StoryWriter(llm).generate(ctx)

    [call] = llm.calls
    assert call["task"] is TaskType.GENERATE_STORY
    assert call["schema"] is UserStory
    system, user = call["messages"]
    assert system == Message(role="system", content=load_prompt("generate_story").text)
    assert user == Message(role="user", content=render_context(ctx))


def test_generate_returns_draft_with_traceability_and_tokens() -> None:
    """RF-15 · RF-21: StoryDraft lleva proveedor, modelo, versión del prompt y tokens."""
    llm, _ = fake_llm(VALID)
    llm.provider, llm.model = "fake-prov", "fake-modelo"

    draft = StoryWriter(llm).generate(need_ctx())

    assert isinstance(draft, StoryDraft)
    assert draft.provider == "fake-prov"
    assert draft.model == "fake-modelo"
    assert draft.prompt_version == load_prompt("generate_story").version
    assert draft.input_tokens > 0
    assert draft.output_tokens > 0


def test_generate_uses_injected_prompt_loader() -> None:
    """CLAUDE.md: los prompts se cargan por nombre; la versión viaja al borrador."""
    names: list[str] = []

    def loader(name: str) -> Prompt:
        names.append(name)
        return Prompt(name=name, version="9-ficticia", text=f"Prompt ficticio {name}")

    llm, _ = fake_llm(VALID)

    draft = StoryWriter(llm, prompt_loader=loader).generate(need_ctx())

    assert names == ["generate_story"]
    assert draft.prompt_version == "9-ficticia"
    assert llm.calls[0]["messages"][0].content == "Prompt ficticio generate_story"


def test_generate_replaces_excerpts_with_real_ones() -> None:
    """RF-21: el borrador muestra los extractos reales, no los del LLM."""
    llm, _ = fake_llm(VALID)

    draft = StoryWriter(llm).generate(need_ctx())

    excerpts = {s.ref: s.excerpt for s in draft.story.sources}
    assert excerpts["DOC-01"] == "Extracto real de DOC-01"
    assert excerpts["DEMO-3"].startswith("[HU-02] Renovar un préstamo")
    assert "inventado" not in excerpts.values()


def test_generate_normalizes_alias_citation_to_doc_id() -> None:
    """RF-21: citar el UUID del documento se acepta y se guarda como DOC-NN."""
    llm, _ = fake_llm(story_citing(("rag", "uuid-ficticio-doc-01")))

    draft = StoryWriter(llm).generate(need_ctx())

    assert [(s.kind, s.ref) for s in draft.story.sources] == [("rag", "DOC-01")]
    assert len(llm.calls) == 1


def test_generate_makes_single_call_when_citations_valid() -> None:
    """RNF-14: con citas válidas no hay reintento."""
    llm, builder = fake_llm(VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 1
    assert builder.count == 1


def test_generate_result_has_valid_criterion_and_rule_ids() -> None:
    """RF-16 · RF-17: los IDs del resultado cumplen CA-NN y RN-NN."""
    llm, _ = fake_llm(VALID)

    story = StoryWriter(llm).generate(need_ctx()).story

    assert story.acceptance_criteria
    assert all(re.match(CRITERION_ID, c.id) for c in story.acceptance_criteria)
    assert all(re.match(RULE_ID, r.id) for r in story.business_rules)


def test_generate_accepts_story_without_citations_when_context_has_no_sources() -> None:
    """RNF-14 (límite): sin fuentes en el contexto, una HU sin citas es válida."""
    llm, _ = fake_llm(story_citing())
    ctx = StoryContext(origin_kind="need", need="Necesidad ficticia sin fuentes.")

    draft = StoryWriter(llm).generate(ctx)

    assert draft.story.sources == []
    assert len(llm.calls) == 1


def test_generate_propagates_llm_errors() -> None:
    """RNF-28: un error del proveedor no se enmascara."""
    llm = FakeLLMProvider(error=AgentError("Proveedor ficticio caído."))

    with pytest.raises(AgentError, match="Proveedor ficticio caído"):
        StoryWriter(llm).generate(need_ctx())


# --- reintento de citas --------------------------------------------------------------------


def test_generate_retries_once_with_error_and_allowed_refs_when_citation_invented() -> None:
    """RNF-14: una cita inventada provoca un reintento con el error y las refs permitidas."""
    llm, _ = fake_llm(INVENTED, VALID)
    ctx = need_ctx()

    StoryWriter(llm).generate(ctx)

    assert len(llm.calls) == 2
    retry = llm.calls[1]
    assert retry["task"] is TaskType.GENERATE_STORY
    assert retry["schema"] is UserStory
    messages: list[Message] = retry["messages"]
    assert messages[:2] == llm.calls[0]["messages"]
    assistant, user = messages[-2], messages[-1]
    assert assistant.role == "assistant"
    assert UserStory.model_validate_json(assistant.content) == INVENTED
    assert user.role == "user"
    assert "«rag:DOC-99» no está entre las fuentes recibidas" in user.content
    assert "- jira: DEMO-3" in user.content
    assert "- rag: DOC-01" in user.content
    assert "{errors}" not in user.content and "{allowed}" not in user.content


def test_generate_retry_mentions_missing_citations_when_story_cites_nothing() -> None:
    """RNF-14: si el contexto trae fuentes y la HU no cita ninguna, también se reintenta."""
    llm, _ = fake_llm(story_citing(), VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2
    assert "no cita ninguna fuente" in llm.calls[1]["messages"][-1].content


def test_generate_returns_retry_story_with_summed_tokens_when_retry_valid() -> None:
    """RNF-14: si el reintento es válido se devuelve esa HU y los tokens de ambas llamadas."""
    fixed = VALID.model_copy(update={"title": "Renovar un préstamo (corregida)"})
    llm, _ = fake_llm(INVENTED, fixed)
    ctx = need_ctx()

    draft = StoryWriter(llm).generate(ctx)

    assert draft.story.title == "Renovar un préstamo (corregida)"
    assert {s.ref for s in draft.story.sources} == {"DEMO-3", "DOC-01"}
    first_in = sum(max(1, len(m.content) // 4) for m in llm.calls[0]["messages"])
    retry_in = sum(max(1, len(m.content) // 4) for m in llm.calls[1]["messages"])
    assert draft.input_tokens == first_in + retry_in
    out_first = max(1, len(INVENTED.model_dump_json()) // 4)
    out_retry = max(1, len(fixed.model_dump_json()) // 4)
    assert draft.output_tokens == out_first + out_retry


def test_generate_raises_citation_error_after_two_calls_when_retry_invalid() -> None:
    """RNF-14: si el reintento vuelve a inventar, CitationError tras exactamente 2 llamadas."""
    llm, builder = fake_llm(INVENTED, story_citing(("jira", "DEMO-404")))

    with pytest.raises(CitationError) as excinfo:
        StoryWriter(llm).generate(need_ctx())

    assert isinstance(excinfo.value, AgentError)
    assert "fuentes que no están en el contexto" in str(excinfo.value)
    assert len(llm.calls) == 2
    assert builder.count == 2


def test_generate_rejects_wrong_kind_citation_via_retry() -> None:
    """RNF-14: citar DOC-01 como jira es inválido y se corrige en el reintento."""
    llm, _ = fake_llm(story_citing(("jira", "DOC-01")), VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2
    assert "«jira:DOC-01»" in llm.calls[1]["messages"][-1].content


# --- evolve y review ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "method, task, prompt_name",
    [
        ("evolve", TaskType.EVOLVE_STORY, "evolve_story"),
        ("review", TaskType.REVIEW_STORY, "review_story"),
    ],
)
def test_evolve_and_review_use_their_task_and_prompt(
    method: str, task: TaskType, prompt_name: str
) -> None:
    """RF-18 · RF-19: evolución y revisión usan su TaskType y su prompt."""
    llm, _ = fake_llm(VALID)
    ctx = story_ctx()

    draft = getattr(StoryWriter(llm), method)(ctx)

    [call] = llm.calls
    assert call["task"] is task
    assert call["schema"] is UserStory
    assert call["messages"][0].content == load_prompt(prompt_name).text
    assert "<hu_actual>" in call["messages"][1].content
    assert draft.prompt_version == load_prompt(prompt_name).version


@pytest.mark.parametrize("method, verb", [("evolve", "evolucionar"), ("review", "revisar")])
def test_evolve_and_review_raise_value_error_without_previous(method: str, verb: str) -> None:
    """RF-18 · RF-19 (error): sin HU previa no se llama al LLM."""
    llm, _ = fake_llm(VALID)

    with pytest.raises(ValueError, match=verb):
        getattr(StoryWriter(llm), method)(need_ctx())

    assert llm.calls == []


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_keep_identity_of_previous_story(method: str) -> None:
    """RF-19 · RF-21: la HU resultante conserva jira_key e internal_id de la HU previa."""
    changed = VALID.model_copy(update={"jira_key": "DEMO-777", "internal_id": "HU-99"})
    llm, _ = fake_llm(changed)

    story = getattr(StoryWriter(llm), method)(story_ctx()).story

    assert story.jira_key == "DEMO-3"
    assert story.internal_id == "HU-02"


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_fall_back_to_origin_key_when_previous_has_no_key(method: str) -> None:
    """RF-19 (límite): si la HU previa no tiene clave se usa origin_key."""
    previous = dataset.renewal_story(jira_key=None)
    ctx = need_ctx(origin_kind="story", origin_key="DEMO-3", previous=previous)
    llm, _ = fake_llm(VALID.model_copy(update={"jira_key": "DEMO-777"}))

    story = getattr(StoryWriter(llm), method)(ctx).story

    assert story.jira_key == "DEMO-3"


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_keep_draft_internal_id_when_previous_has_none(method: str) -> None:
    """RF-19 (límite): sin internal_id previo se mantiene el propuesto por el LLM."""
    previous = dataset.renewal_story().model_copy(update={"internal_id": None})
    ctx = need_ctx(origin_kind="story", origin_key="DEMO-3", previous=previous)
    llm, _ = fake_llm(VALID.model_copy(update={"internal_id": "HU-05"}))

    story = getattr(StoryWriter(llm), method)(ctx).story

    assert story.internal_id == "HU-05"


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_keep_traceability_and_real_excerpts(method: str) -> None:
    """RF-21: la identidad conservada no pierde proveedor, tokens ni extractos reales."""
    llm, _ = fake_llm(VALID)

    draft = getattr(StoryWriter(llm), method)(story_ctx())

    assert (draft.provider, draft.model) == ("fake", "fake-model")
    assert draft.input_tokens > 0 and draft.output_tokens > 0
    assert {s.excerpt for s in draft.story.sources} >= {"Extracto real de DOC-01"}


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_retry_and_fail_like_generate(method: str) -> None:
    """RNF-14: evolución y revisión aplican el mismo reintento único de citas."""
    llm, _ = fake_llm(INVENTED, INVENTED)

    with pytest.raises(CitationError):
        getattr(StoryWriter(llm), method)(story_ctx())

    assert len(llm.calls) == 2


def test_evolve_keeps_changes_from_previous() -> None:
    """RF-19: la evolución devuelve changes_from_previous tal como lo propone el LLM."""
    evolved = VALID.model_copy(
        update={"changes_from_previous": ["RN-01: el máximo pasa de 2 a 3 renovaciones"]}
    )
    llm, _ = fake_llm(evolved)

    story = StoryWriter(llm).evolve(story_ctx()).story

    assert story.changes_from_previous == ["RN-01: el máximo pasa de 2 a 3 renovaciones"]


# --- Sustitución de marcadores en una sola pasada ------------------------------------------


def test_fill_placeholders_does_not_reinterpret_values() -> None:
    """Una ref inventada con forma de marcador («{allowed}») aparece literal en el error."""
    from core.functional.writer import fill_placeholders

    text = fill_placeholders(
        "Errores:\n{errors}\nPermitidas:\n{allowed}",
        {"errors": "- «rag:{allowed}» no está", "allowed": "- rag: DOC-01"},
    )

    assert "- «rag:{allowed}» no está" in text
    assert text.endswith("- rag: DOC-01")


# --- Identidad de la HU (cierre de spec-checker) -------------------------------------------


def test_generate_discards_jira_key_invented_by_llm() -> None:
    """RNF-14: una HU nueva no tiene clave de Jira aunque el LLM proponga una."""
    llm, _ = fake_llm(VALID.model_copy(update={"jira_key": "DEMO-777"}))

    story = StoryWriter(llm).generate(need_ctx()).story

    assert story.jira_key is None


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_ignore_origin_key_when_origin_is_not_a_story(method: str) -> None:
    """RF-19 (límite): la clave de una épica de origen no se asigna a la HU."""
    previous = dataset.renewal_story(jira_key=None)
    ctx = need_ctx(origin_kind="epic", origin_key="DEMO-1", previous=previous)
    llm, _ = fake_llm(VALID)

    story = getattr(StoryWriter(llm), method)(ctx).story

    assert story.jira_key is None


# --- T-58 · Prompts para modelos locales pequeños (RNF-09, RNF-12) ------------------------------

T58_MIN_VERSIONS = {
    "generate_story": 2,
    "evolve_story": 3,
    "structure_story": 2,
    "citation_retry": 2,
    "review_quality": 2,
    "quality_retry": 2,
}


@pytest.mark.parametrize(("name", "minimum"), T58_MIN_VERSIONS.items())
def test_prompt_version_raised_when_t58_changes_it(name: str, minimum: int) -> None:
    """F · T-58: los prompts modificados suben su `version:`."""
    assert int(load_prompt(name).version) >= minimum


@pytest.mark.parametrize("name", ["generate_story", "evolve_story"])
def test_story_prompt_numbers_ids_even_when_sources_use_other_ids(name: str) -> None:
    """F · T-58: la regla de numeración menciona los IDs de las fuentes (`RN-RES-01`)."""
    text = load_prompt(name).text

    assert "RN-RES-01" in text
    assert "CA-" in text and "RN-" in text


def test_structure_prompt_numbers_ids_when_issue_uses_other_format() -> None:
    """F · T-58: `structure_story` pide CA-01/RN-01 aunque la incidencia use otro formato."""
    text = load_prompt("structure_story").text

    assert "CA-01" in text and "RN-01" in text
    assert "otro formato" in text


@pytest.mark.parametrize(
    "name", ["generate_story", "evolve_story", "structure_story", "review_quality"]
)
def test_prompt_forbids_empty_sources(name: str) -> None:
    """F · T-58: `sources` nunca puede quedar vacío (las mediciones devolvían `sources: []`)."""
    text = load_prompt(name).text
    rule = next(line for line in text.splitlines() if "`sources`" in line and "nunca" in line)

    assert "vacío" in rule


def test_citation_retry_prompt_requires_non_empty_sources() -> None:
    """F · T-58: el reintento de citas pide que `sources` no quede vacío si hay fuentes."""
    text = load_prompt("citation_retry").text

    assert "`sources`" in text
    assert "no puede quedar vacío" in text
    assert "al menos una" in text


def test_quality_retry_prompt_requires_at_least_one_citation() -> None:
    """F · T-58: el reintento de calidad pide al menos una cita si la lista no está vacía."""
    text = load_prompt("quality_retry").text

    assert "al menos una" in text
    assert "{allowed}" in text


# --- T-58 · Cita vacía con contexto con fuentes (RNF-14) ----------------------------------------

EMPTY_SOURCES = story_citing()  # HU válida sin ninguna cita


def test_generate_retries_with_citation_retry_when_first_story_has_empty_sources() -> None:
    """G · T-58: `sources=[]` con fuentes en el contexto → reintento con citation_retry."""
    llm, _ = fake_llm(EMPTY_SOURCES, VALID)

    StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2
    retry = llm.calls[1]["messages"]
    assert UserStory.model_validate_json(retry[-2].content).sources == []
    feedback = retry[-1].content
    assert "no cita ninguna fuente" in feedback
    assert "no puede quedar vacío" in feedback
    assert "- jira: DEMO-3" in feedback and "- rag: DOC-01" in feedback


def test_generate_accepts_retry_when_second_story_cites_a_valid_source() -> None:
    """G · T-58: si el reintento trae una cita válida, se acepta con el extracto real."""
    llm, _ = fake_llm(EMPTY_SOURCES, story_citing(("rag", "DOC-01")))

    draft = StoryWriter(llm).generate(need_ctx())

    assert [(s.kind, s.ref) for s in draft.story.sources] == [("rag", "DOC-01")]
    assert draft.story.sources[0].excerpt != "inventado"
    assert len(llm.calls) == 2


def test_generate_raises_citation_error_when_sources_stay_empty_after_retry() -> None:
    """G · T-58 (error): si el reintento sigue sin citas → CitationError tras 2 llamadas."""
    llm, _ = fake_llm(EMPTY_SOURCES, EMPTY_SOURCES)

    with pytest.raises(CitationError):
        StoryWriter(llm).generate(need_ctx())

    assert len(llm.calls) == 2


def test_generate_citation_error_explains_missing_citations_when_sources_stay_empty() -> None:
    """G · T-58 (error): el mensaje debería explicar que la propuesta no cita ninguna fuente."""
    llm, _ = fake_llm(EMPTY_SOURCES, EMPTY_SOURCES)

    with pytest.raises(CitationError) as info:
        StoryWriter(llm).generate(need_ctx())

    assert "no están en el contexto" not in str(info.value)


@pytest.mark.parametrize("method", ["evolve", "review"])
def test_evolve_and_review_retry_when_first_story_has_empty_sources(method: str) -> None:
    """G · T-58: evolución y revisión siguen el mismo camino ante `sources=[]`."""
    llm, _ = fake_llm(EMPTY_SOURCES, VALID)

    getattr(StoryWriter(llm), method)(story_ctx())

    assert len(llm.calls) == 2
    assert "no cita ninguna fuente" in llm.calls[1]["messages"][-1].content


def test_structure_retries_when_first_story_has_empty_sources() -> None:
    """G · T-58: `structure` (HU de Jira a plantilla) también reintenta si no cita la incidencia."""
    llm, _ = fake_llm(EMPTY_SOURCES, story_citing(("jira", "DEMO-3")))

    draft = StoryWriter(llm).structure(story_ctx())

    assert len(llm.calls) == 2
    assert "no cita ninguna fuente" in llm.calls[1]["messages"][-1].content
    assert [s.ref for s in draft.story.sources] == ["DEMO-3"]


def test_forced_citation_without_sources_is_dropped_not_an_error() -> None:
    """RNF-14 · `schema_hints`: el esquema pide una cita; sin fuentes en el contexto, la cita
    que traiga la respuesta solo puede ser inventada y se quita (sin reintento ni error)."""
    llm, _ = fake_llm(story_citing(("rag", "DOC-INVENTADO")))
    ctx = StoryContext(origin_kind="need", need="Necesidad ficticia sin fuentes.")

    draft = StoryWriter(llm).generate(ctx)

    assert draft.story.sources == []
    assert len(llm.calls) == 1


def test_invented_citation_with_sources_still_triggers_retry() -> None:
    """Con fuentes en el contexto, una cita inventada sigue siendo un error (reintento)."""
    llm, _ = fake_llm(story_citing(("rag", "DOC-INVENTADO")))
    with pytest.raises(CitationError):
        StoryWriter(llm).generate(need_ctx())
    assert len(llm.calls) == 2
