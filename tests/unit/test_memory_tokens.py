"""Pruebas de `eval.memory_tokens` (T-33 · RNF-11): reducción de tokens de la memoria.

Solo el modo `fake` y funciones puras: el modo `real` llama al LLM y no se ejecuta en pruebas.
"""

import json
import re

import pytest

import core.factories
from core.context.budget import estimate_tokens
from core.functional.writer import StoryWriter
from core.memory.generator import LLMMemoryGenerator
from eval import memory_tokens as mt
from schemas.common import ArtifactStatus, ArtifactType
from tests.fakes import dataset
from tests.fakes.llm import FakeLLMProvider
from tests.fakes.memory_generator import FakeMemoryGenerator


def _row(before: int, after: int, key: str = "DEMO-3") -> mt.TokenRow:
    return mt.TokenRow(key=key, origin="dataset", artifact_tokens=before, memory_tokens=after)


# --- TokenRow ------------------------------------------------------------------------------


def test_row_reduction_is_relative_saving() -> None:
    """RNF-11: reducción = 1 - tokens_memoria / tokens_artefacto."""
    assert _row(200, 50).reduction == pytest.approx(0.75)


def test_row_meets_target_at_exact_threshold() -> None:
    """RNF-11 (límite): una reducción del 60 % exacto cumple."""
    row = _row(100, 40)

    assert row.reduction == pytest.approx(0.60)
    assert row.meets_target is True


def test_row_does_not_meet_target_just_below_threshold() -> None:
    """RNF-11 (límite): 59 % no cumple."""
    assert _row(100, 41).meets_target is False


def test_row_with_zero_artifact_tokens_has_no_reduction() -> None:
    """RNF-11 (borde): sin tokens de artefacto la reducción es 0 y no cumple."""
    row = _row(0, 0)

    assert row.reduction == 0.0
    assert row.meets_target is False


def test_target_constant_is_sixty_percent() -> None:
    """RNF-11: el umbral es el 60 %."""
    assert mt.REDUCTION_TARGET == 0.60


# --- TokenReport ---------------------------------------------------------------------------


def test_report_total_reduction_is_weighted_by_tokens() -> None:
    """RNF-11: la reducción total pondera por tokens, no promedia porcentajes."""
    report = mt.TokenReport(rows=[_row(100, 10, "DEMO-2"), _row(300, 290, "DEMO-3")])

    assert report.total_reduction == pytest.approx(1 - 300 / 400)
    assert report.total_reduction != pytest.approx((0.9 + 1 - 290 / 300) / 2)
    assert report.meets_target is False


def test_report_meets_target_when_total_reaches_threshold() -> None:
    """RNF-11: cumple si la reducción total llega al 60 % aunque una fila no llegue."""
    report = mt.TokenReport(rows=[_row(900, 100, "DEMO-2"), _row(100, 90, "DEMO-3")])

    assert report.rows[1].meets_target is False
    assert report.total_reduction == pytest.approx(0.81)
    assert report.meets_target is True


def test_empty_report_does_not_meet_target() -> None:
    """RNF-11 (borde): un informe vacío no cumple."""
    report = mt.TokenReport(rows=[])

    assert report.total_reduction == 0.0
    assert report.meets_target is False


# --- medición ------------------------------------------------------------------------------


def test_artifact_text_is_story_json() -> None:
    """RNF-11: el artefacto se mide como JSON de su contenido."""
    ((artifact, _),) = mt.dataset_artifacts()

    text = mt.artifact_text(artifact)

    assert json.loads(text) == artifact.content.model_dump(mode="json")


def test_measure_uses_estimated_tokens_of_artifact_and_markdown() -> None:
    """RNF-11: measure compara tokens del artefacto y de `Memory.to_markdown()`."""
    ((artifact, origin),) = mt.dataset_artifacts()
    generator = FakeMemoryGenerator()

    row = mt.measure(artifact, generator, origin)

    (memory,) = generator.generated
    assert row.key == "DEMO-3"
    assert row.origin == "dataset"
    assert row.artifact_tokens == estimate_tokens(mt.artifact_text(artifact))
    assert row.memory_tokens == estimate_tokens(memory.to_markdown())


def test_build_report_has_one_row_per_artifact() -> None:
    """RNF-11: una fila por artefacto, con su origen."""
    artifacts = mt.dataset_artifacts() * 2

    report = mt.build_report(artifacts, FakeMemoryGenerator())

    assert [r.origin for r in report.rows] == ["dataset", "dataset"]


def test_build_report_with_llm_generator_over_fakes() -> None:
    """RNF-11: el informe funciona con LLMMemoryGenerator sobre FakeLLMProvider (sin red)."""
    llm = FakeLLMProvider()

    report = mt.build_report(mt.dataset_artifacts(), LLMMemoryGenerator(llm))

    (row,) = report.rows
    assert row.key == "DEMO-3"
    assert 0 < row.memory_tokens < row.artifact_tokens
    assert all(call["schema"] is not None for call in llm.calls)


def test_published_story_sets_key_and_published_status() -> None:
    """RNF-11: published_story devuelve un artefacto publicado con la clave indicada."""
    artifact = mt.published_story(dataset.renewal_story(jira_key=None), "VF-2")

    assert artifact.type is ArtifactType.USER_STORY
    assert artifact.status is ArtifactStatus.PUBLISHED
    assert artifact.version == 1
    assert artifact.origin_key == "VF-2"
    assert artifact.content.jira_key == "VF-2"


def test_dataset_artifacts_cite_dataset_documents() -> None:
    """RNF-11: la HU del dataset cita los documentos del corpus ficticio."""
    ((artifact, origin),) = mt.dataset_artifacts()

    assert origin == "dataset"
    assert [s.ref for s in artifact.content.sources] == list(dataset.DOCUMENTS)


# --- seed ----------------------------------------------------------------------------------


def test_seed_issues_returns_thirteen_stories_with_fictitious_keys() -> None:
    """RNF-11: el seed aporta 13 HU con claves VF-n y épica padre, sin llamar a Jira."""
    issues = mt.seed_issues()

    assert len(issues) == 13
    assert all(re.fullmatch(r"VF-\d+", i.key) for i in issues)
    assert len({i.key for i in issues}) == 13
    assert all(i.issue_type == "Story" for i in issues)
    assert all(i.parent_key and re.fullmatch(r"VF-\d+", i.parent_key) for i in issues)
    assert all(i.summary and i.description_text for i in issues)


def test_seed_artifacts_with_fake_llm_do_not_need_network() -> None:
    """RNF-11: seed_artifacts estructura HU con StoryWriter sobre FakeLLMProvider."""
    issues = mt.seed_issues()[:2]
    llm = FakeLLMProvider()

    artifacts = mt.seed_artifacts(StoryWriter(llm), issues)

    assert [origin for _, origin in artifacts] == ["seed", "seed"]
    assert [a.content.jira_key for a, _ in artifacts] == [i.key for i in issues]
    assert all(a.status is ArtifactStatus.PUBLISHED for a, _ in artifacts)
    assert len(llm.calls) >= 2


def test_seed_artifacts_empty_list_returns_nothing() -> None:
    """RNF-11 (borde): sin incidencias no hay artefactos ni llamadas."""
    llm = FakeLLMProvider()

    assert mt.seed_artifacts(StoryWriter(llm), []) == []
    assert llm.calls == []


# --- formato y CLI -------------------------------------------------------------------------


def test_format_report_renders_table_and_verdict() -> None:
    """RNF-11: tabla Markdown con una fila por HU y veredicto."""
    text = mt.format_report(mt.TokenReport(rows=[_row(100, 40)]))

    assert "| Clave | Origen | Tokens HU | Tokens memoria | Reducción | ≥ 60 % |" in text
    assert "| DEMO-3 | dataset | 100 | 40 | 60% | sí |" in text
    assert "Reducción total: 60% · RNF-11 CUMPLE" in text


def test_format_report_empty_says_not_met() -> None:
    """RNF-11 (borde): el informe vacío dice NO CUMPLE."""
    assert "RNF-11 NO CUMPLE" in mt.format_report(mt.TokenReport(rows=[]))


def test_main_fake_mode_returns_zero_and_prints_table(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """RNF-11: `--mode fake` mide el dataset sin LLM real y escribe la tabla."""

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("el modo fake no debe construir un proveedor LLM real")

    monkeypatch.setattr(core.factories, "build_llm_provider", forbidden)

    code = mt.main(["--mode", "fake"])

    out = capsys.readouterr().out
    assert code == 0
    assert "| Clave | Origen |" in out
    assert "| DEMO-3 | dataset |" in out
    assert "RNF-11 CUMPLE" in out


def test_main_defaults_to_fake_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """RNF-11: sin argumentos el modo es fake."""
    assert mt.main([]) == 0
    assert "| DEMO-3 | dataset |" in capsys.readouterr().out


@pytest.mark.parametrize("limit", ["0", "-3"])
def test_main_rejects_non_positive_limit(limit: str, capsys: pytest.CaptureFixture[str]) -> None:
    """RNF-11 (error): `--limit` no positivo es un error de argparse (código 2)."""
    with pytest.raises(SystemExit) as info:
        mt.main(["--limit", limit])

    assert info.value.code == 2
    assert "--limit debe ser un entero positivo" in capsys.readouterr().err


def test_main_rejects_unknown_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """RNF-11 (error): un modo desconocido es un error de argparse."""
    with pytest.raises(SystemExit) as info:
        mt.main(["--mode", "otro"])

    assert info.value.code == 2
    assert "'otro'" in capsys.readouterr().err
