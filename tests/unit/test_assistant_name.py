"""PA-479, PA-480, PA-481 · El asistente se llama FAQ fuera de la web (diseño PA-478).

Una sola constante (`core/assistant.py`), leída al construir los textos: el comentario que se
publica en Jira, el mensaje de un CA sin caso, el servidor MCP y Streamlit. Nada de lo que se
publica dice «el agente». Datos ficticios (proyecto DEMO).
"""

import json
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from streamlit.testing.v1 import AppTest

from adapters.base import User
from adapters.jira.story_template import story_to_adf
from adapters.testmgmt.jira_native import attachment_files, case_to_adf, execution_comment
from core import assistant
from core.graph.nodes import _diff_comment_md, missing_cases
from mcp_server.server import SERVER_NAME, build_server, instructions, read_only_message
from schemas.impact import ImpactAnalysis, StoryDiff
from schemas.test_case import ExecutionStatus
from tests.fakes import dataset
from tests.fakes.container import fake_container
from tests.fakes.llm import renewal_test_suite
from tests.unit.test_app_smoke import composed, container, quality_store  # noqa: F401

FUNCTIONAL = User(username="af-ficticio", role="functional")
APP = Path(__file__).resolve().parents[2] / "app" / "main.py"


def _impact() -> ImpactAnalysis:
    return ImpactAnalysis(
        diffs=[StoryDiff(field="title", before="Antes", after="Después")],
        affected=[],
        regression_notes=[],
    )


# --- La constante ------------------------------------------------------------------------------


def test_assistant_is_faq_and_brand_is_qaracter() -> None:
    assert assistant.ASSISTANT_NAME == "FAQ"
    assert assistant.BRAND == "Qaracter"
    assert assistant.display_name() == "FAQ · Qaracter"


# --- PA-479 · Jira -----------------------------------------------------------------------------


def test_diff_comment_is_signed_by_faq() -> None:
    comment = _diff_comment_md(_impact())
    assert comment.splitlines()[0] == "**Cambios propuestos por FAQ y aprobados**"
    assert "agente" not in comment


def test_published_texts_do_not_say_the_agent() -> None:
    """Descripción de una HU, subtareas CP, estrategia, matriz y comentario de ejecución."""
    suite = renewal_test_suite()
    published = [
        json.dumps(story_to_adf(dataset.renewal_story()), ensure_ascii=False),
        *(json.dumps(case_to_adf(c, "DEMO-3"), ensure_ascii=False) for c in suite.cases),
        *attachment_files(suite).values(),
        json.dumps(
            execution_comment(ExecutionStatus.PASSED, "Evidencia ficticia."), ensure_ascii=False
        ),
        _diff_comment_md(_impact()),
    ]
    assert all("agente" not in text.lower() for text in published)


def test_missing_cases_message_names_faq() -> None:
    message = missing_cases("CA-02")
    assert message == "Falta al menos un caso para CA-02: pídeselo a FAQ antes de aprobar."


# --- PA-480 · Servidor MCP --------------------------------------------------------------------


def test_mcp_is_named_faq_and_shows_faq(tmp_path: Path) -> None:
    server = build_server(fake_container(tmp_path), FUNCTIONAL)
    assert server.name == SERVER_NAME == "faq"  # el nombre con el que se registra en `.mcp.json`
    assert server.title == "FAQ · Qaracter"


def test_mcp_instructions_and_tools_name_faq(tmp_path: Path) -> None:
    text = instructions(FUNCTIONAL)
    assert text.startswith("Herramientas de solo lectura de FAQ, el asistente")
    assert "agente" not in text
    assert "FAQ" in read_only_message() and "agente" not in read_only_message()

    server = build_server(fake_container(tmp_path), FUNCTIONAL)

    async def tools() -> Any:
        async with Client(server) as client:
            return await client.list_tools()

    descriptions = {t.name: t.description or "" for t in anyio.run(tools).tools}
    assert all("agente" not in d for d in descriptions.values())
    for name in ("revisar_calidad", "fuentes_de_contexto", "proponer_inicio", "mis_conversaciones"):
        assert "FAQ" in descriptions[name], name


# --- PA-481 · Streamlit ------------------------------------------------------------------------


@pytest.mark.usefixtures("composed")
def test_streamlit_title_is_faq(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con la composición sustituida por los fakes (`composed`: sin `.env` ni PostgreSQL)."""
    import streamlit as st

    configured: dict[str, Any] = {}
    original = st.set_page_config

    def spy(**kwargs: Any) -> None:
        configured.update(kwargs)
        original(**kwargs)

    monkeypatch.setattr(st, "set_page_config", spy)
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not at.exception, at.exception

    assert configured["page_title"] == "FAQ · Qaracter"
    assert [t.value for t in at.title][:1] == ["FAQ"]


# --- Cambiar la constante cambia los textos ----------------------------------------------------


def test_changing_the_constant_changes_the_texts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assistant, "ASSISTANT_NAME", "Ficticio")
    monkeypatch.setattr(assistant, "BRAND", "Marca ficticia")

    assert "propuestos por Ficticio y aprobados" in _diff_comment_md(_impact())
    assert "pídeselo a Ficticio" in missing_cases("CA-01")
    assert "de Ficticio, el asistente" in instructions(FUNCTIONAL)
    assert "memorias de Ficticio" in read_only_message()
    assert build_server(fake_container(tmp_path), FUNCTIONAL).title == "Ficticio · Marca ficticia"
