"""PA-451: la edición manual (RF-32) pasa las mismas validaciones que la salida del modelo.

En HU: citas del contexto y datos que parecen personales o secretos. En suites: CA/RN que existen,
citas y datos personales (`blocking_errors`, como al generar). Si falla, la edición se rechaza
(nueva pausa con `error`, sin efectos: D-1). Datos sintéticos: emails `@example.com`/`-test.es`,
IBAN `ES00…` y documentos inventados.
"""

import copy
from pathlib import Path
from typing import Any

import pytest

from core.graph import build_graph
from tests.fakes.container import fake_container
from tests.unit.test_review_contract import (
    QA_USER,
    _config,
    _edit_command,
    _edited_story,
    _payload,
    _rejected,
    _snapshot,
    _start,
    _testmgmt,
    _tracker,
)

# Valores que el detector toma por reales (no son de nadie: formatos de prueba).
REAL_LOOKING = {
    "email": "Avisar a socia.ficticia@correo-test.es cuando vuelva el libro.",
    "IBAN": "Domiciliar en ES00 0000 0000 0000 0000 0000.",
    "documento de identidad": "La persona con DNI 00000000T recoge el libro.",
    "secreto": "Usar la api_key: gsk_FICTICIA0000000000000000 para avisar.",
}


def _story_session(tmp_path: Path) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    return container, graph, config, _payload(_start(graph, config))


def _suite_session(tmp_path: Path) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    container = fake_container(tmp_path)
    graph = build_graph(container)
    config = _config()
    return container, graph, config, _payload(_start(graph, config, mode="qa", user=QA_USER))


# --- HU -------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(REAL_LOOKING))
def test_edited_story_with_personal_data_or_secret_is_rejected(tmp_path: Path, kind: str) -> None:
    """PA-451: una HU editada con un dato que parece real se rechaza sin efectos y sin repetir
    el valor en el motivo."""
    container, graph, config, first = _story_session(tmp_path)
    content = _edited_story(first["artifact"]["content"], description=REAL_LOOKING[kind])
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert rejected["error"].startswith("La edición no se puede guardar: description ")
    assert REAL_LOOKING[kind] not in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_edited_story_with_fictitious_email_is_accepted(tmp_path: Path) -> None:
    """PA-451 (positivo): un email de dominio reservado (`@example.com`) es ficticio: se acepta."""
    _container, graph, config, first = _story_session(tmp_path)
    content = _edited_story(
        first["artifact"]["content"], description="Avisar a socia@example.com (ficticio)."
    )

    second = _payload(graph.invoke(_edit_command(content, first["fingerprint"]), config))

    assert second["error"] is None
    assert second["version"] == 2


def test_edited_story_citing_a_source_outside_the_context_is_rejected(tmp_path: Path) -> None:
    """PA-451: una cita que no estaba en el contexto de la conversación se rechaza."""
    container, graph, config, first = _story_session(tmp_path)
    content = copy.deepcopy(first["artifact"]["content"])
    content["sources"] = [{"kind": "rag", "ref": "DOC-99-INVENTADO", "excerpt": None}]
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "DOC-99-INVENTADO" in rejected["error"]
    assert "no está entre las fuentes recibidas" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_edited_story_without_sources_is_rejected_when_context_had_them(tmp_path: Path) -> None:
    """PA-451: quitar todas las citas cuando el contexto traía fuentes se rechaza (RNF-14)."""
    container, graph, config, first = _story_session(tmp_path)
    content = _edited_story(first["artifact"]["content"], sources=[], title="Título editado")
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "no cita ninguna fuente" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_valid_story_edit_still_creates_a_version(tmp_path: Path) -> None:
    """PA-451 (positivo): una edición válida sigue creando la versión nueva y no escribe en Jira."""
    container, graph, config, first = _story_session(tmp_path)
    content = _edited_story(first["artifact"]["content"])

    second = _payload(graph.invoke(_edit_command(content, first["fingerprint"]), config))

    assert second["error"] is None
    assert second["version"] == 2
    assert _tracker(container).writes == []


# --- Suite ----------------------------------------------------------------------------------


def test_edited_suite_with_personal_data_is_rejected(tmp_path: Path) -> None:
    """PA-451: un dato que parece personal en la suite editada (iría a Jira) se rechaza."""
    container, graph, config, first = _suite_session(tmp_path)
    content = copy.deepcopy(first["artifact"]["content"])
    content["cases"][0]["steps"][0]["data"] = "Email: lector.ficticio@biblioteca-test.es"
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert rejected["error"].startswith("La edición no se puede guardar:")
    assert "email" in rejected["error"]
    assert "lector.ficticio" not in rejected["error"]
    assert _snapshot(container, graph, config) == before
    assert _testmgmt(container).publish_calls == 0


def test_edited_suite_pointing_to_a_missing_criterion_is_rejected(tmp_path: Path) -> None:
    """PA-451: un caso que apunta a un CA que la HU no tiene (CA-99) se rechaza."""
    container, graph, config, first = _suite_session(tmp_path)
    content = copy.deepcopy(first["artifact"]["content"])
    content["cases"][0]["criterion_ids"] = ["CA-99"]
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "CA-99" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_edited_suite_citing_a_source_outside_the_context_is_rejected(tmp_path: Path) -> None:
    """PA-451: una suite editada que cita una fuente que no estaba en el contexto se rechaza."""
    container, graph, config, first = _suite_session(tmp_path)
    content = copy.deepcopy(first["artifact"]["content"])
    content["sources"] = [{"kind": "rag", "ref": "DOC-99-INVENTADO", "excerpt": None}]
    before = _snapshot(container, graph, config)

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "DOC-99-INVENTADO" in rejected["error"]
    assert _snapshot(container, graph, config) == before


def test_valid_suite_edit_still_creates_a_version(tmp_path: Path) -> None:
    """PA-451 (positivo): una edición válida de la suite sigue creando la versión 2."""
    _container, graph, config, first = _suite_session(tmp_path)
    content = copy.deepcopy(first["artifact"]["content"])
    content["cases"][0]["title"] = "Caso editado a mano (ficticio)"

    second = _payload(graph.invoke(_edit_command(content, first["fingerprint"]), config))

    assert second["error"] is None
    assert second["version"] == 2


def test_edited_suite_without_its_story_is_rejected(tmp_path: Path) -> None:
    """PA-451 (negativo): sin la HU de la suite no se puede comprobar: se rechaza, no se acepta
    a ciegas."""
    container, graph, config, first = _suite_session(tmp_path)
    artifact_id = first["artifact"]["id"]
    saved = container.state_store.load(artifact_id) or {}
    saved.pop("baseline", None)
    container.state_store.save(artifact_id, saved)
    content = copy.deepcopy(first["artifact"]["content"])
    content["cases"][0]["title"] = "Caso editado a mano (ficticio)"

    rejected = _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert "falta la HU de origen" in rejected["error"]


def test_edit_validation_does_not_call_the_model(tmp_path: Path) -> None:
    """PA-451: las validaciones no llaman al modelo (la edición sigue sin LLM)."""
    container, graph, config, first = _story_session(tmp_path)
    calls = len(container.llm.calls)
    content = _edited_story(first["artifact"]["content"], description=REAL_LOOKING["email"])

    _rejected(graph, config, _edit_command(content, first["fingerprint"]), first)

    assert len(container.llm.calls) == calls
