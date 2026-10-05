"""Capa 1 de `/auditoria` (`.claude/skills/auditoria/checks.py`): cada regla detecta un caso malo
y no marca uno bueno, sobre archivos ficticios en `tmp_path`."""

import importlib.util
import sys
from pathlib import Path
from textwrap import dedent
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "auditoria" / "checks.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("auditoria_checks", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses necesita el módulo registrado
    spec.loader.exec_module(module)
    return module


checks = _load()


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")


def _rules(root: Path, rule: str) -> list[tuple[str, int]]:
    return [(f.path, f.line) for f in checks.run(root, rules=[rule])]


# --- jira-write ---------------------------------------------------------------------------------


def test_jira_write_flags_write_outside_publish_node(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/graph/nodes.py",
        """
        class Nodes:
            def generate(self):
                self.c.issue_tracker.create_story(story, None, "DEMO")
        """,
    )
    _write(
        tmp_path,
        "api/service.py",
        """
        def approve(client):
            client.post("/rest/api/3/issue", json={})
        """,
    )
    assert _rules(tmp_path, "jira-write") == [("api/service.py", 3), ("core/graph/nodes.py", 4)]


def test_jira_write_allows_publish_node_execution_node_and_adapters(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/graph/nodes.py",
        """
        class Nodes:
            def publish(self):
                self.c.test_management.publish_suite(suite)

            def _publish_story(self):
                self.c.issue_tracker.update_story(key, story, "")
                self.c.issue_tracker.link(key, other, "relates to", "")
        """,
    )
    _write(
        tmp_path,
        "core/graph/execution.py",
        """
        class ExecutionNodes:
            def publish(self):
                self.c.test_management.record_execution(key, status, evidence)
        """,
    )
    _write(
        tmp_path,
        "adapters/jira/tracker.py",
        """
        def create_story(http):
            http.post("/rest/api/3/issue", json={})
        """,
    )
    assert _rules(tmp_path, "jira-write") == []


def test_jira_write_flags_execution_file_outside_its_publish_node(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/graph/execution.py",
        """
        class ExecutionNodes:
            def review(self):
                self.c.test_management.record_execution(key, status, evidence)
        """,
    )
    assert _rules(tmp_path, "jira-write") == [("core/graph/execution.py", 4)]


# --- core-concrete-import -----------------------------------------------------------------------


def test_core_concrete_import_flags_adapter_implementation(tmp_path: Path) -> None:
    _write(tmp_path, "core/rag/search.py", "from adapters.vectorstore.pgvector import Store\n")
    _write(tmp_path, "core/qa/writer.py", "from adapters import jira\n")
    assert _rules(tmp_path, "core-concrete-import") == [
        ("core/qa/writer.py", 1),
        ("core/rag/search.py", 1),
    ]


def test_core_concrete_import_allows_protocols_and_composition(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/rag/search.py",
        "from adapters.base import VectorStore\nfrom adapters.errors import AgentError\n",
    )
    _write(tmp_path, "core/factories.py", "from adapters.jira.tracker import JiraCloudTracker\n")
    _write(tmp_path, "api/admin.py", "from adapters.llm.catalog import HttpModelCatalog\n")
    assert _rules(tmp_path, "core-concrete-import") == []


# --- inline-prompt ------------------------------------------------------------------------------


def test_inline_prompt_flags_instruction_and_system_message(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/functional/writer.py",
        """
        PROMPT = "Eres un analista funcional. Responde solo con JSON que cumpla el esquema dado."
        msg = Message(
            role="system",
            content="Analiza la historia de usuario y genera sus criterios de aceptación.",
        )
        """,
    )
    assert _rules(tmp_path, "inline-prompt") == [
        ("core/functional/writer.py", 2),
        ("core/functional/writer.py", 3),
    ]


def test_inline_prompt_ignores_docstrings_short_texts_and_prompt_files(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/functional/writer.py",
        '''
        def f():
            """Eres un analista funcional. Responde solo con JSON que cumpla el esquema dado."""
            return Message(role="system", content=prompt.text)

        ERROR = "Responde 202 con el estado de la conversación."
        ''',
    )
    _write(
        tmp_path,
        "eval/judge.py",
        'P = "Eres un juez. Responde solo con JSON y sin explicaciones."\n',
    )
    assert _rules(tmp_path, "inline-prompt") == []


# --- log-sensitive-field ------------------------------------------------------------------------


def test_log_sensitive_field_flags_secret_like_fields(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "adapters/llm/client.py",
        """
        log.info("llamada", prompt=messages_text)
        self.log.warning("cabecera", authorization=header)
        logger.error("fallo", jira_api_key=value)
        """,
    )
    assert [line for _p, line in _rules(tmp_path, "log-sensitive-field")] == [2, 3, 4]


def test_log_sensitive_field_allows_token_counts_and_safe_fields(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "adapters/llm/client.py",
        """
        log.info("uso", tokens=10, prompt_tokens=5, completion_tokens=5, token_count=10)
        log.info("llamada", user="analista-demo", action="generate", model="m", duration_ms=3)
        result.update(prompt=text)
        """,
    )
    assert _rules(tmp_path, "log-sensitive-field") == []


# --- silent-except ------------------------------------------------------------------------------


def test_silent_except_flags_bare_and_broad_handlers(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "api/service.py",
        """
        def a():
            try:
                work()
            except Exception:
                return []

        def b():
            try:
                work()
            except:
                pass
        """,
    )
    assert _rules(tmp_path, "silent-except") == [("api/service.py", 5), ("api/service.py", 11)]


def test_silent_except_allows_raise_log_use_of_exception_and_mark(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "api/service.py",
        """
        def a():
            try:
                work()
            except Exception:
                log.warning("fallo", error_type="X")

        def b():
            try:
                work()
            except Exception as exc:
                fail(conv, exc)

        def c():
            try:
                work()
            except Exception:
                raise ExternalServiceError("No se pudo.") from None

        def d():
            try:
                work()
            except Exception:  # auditoria: ok la auditoría es secundaria para pintar
                return []

        def e():
            try:
                work()
            except ValueError:
                return []
        """,
    )
    assert _rules(tmp_path, "silent-except") == []


def test_ok_mark_without_reason_does_not_count(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "api/service.py",
        """
        def a():
            try:
                work()
            except Exception:  # auditoria: ok
                return []
        """,
    )
    assert _rules(tmp_path, "silent-except") == [("api/service.py", 5)]


# --- redos --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [r"(a+)+$", r"(\w*)*x", r"(?:a|a?)+b", r"^(\s*-?\s*)*$"],
)
def test_redos_flags_nested_or_overlapping_quantifiers(pattern: str) -> None:
    assert checks.regex_risk(pattern) is not None


@pytest.mark.parametrize(
    "pattern",
    [
        r"^#{1,6}\s+(.*)$",
        r"(?:\w|-)+",
        r"[A-Z][A-Z0-9]+-\d+",
        r"(?:ab)+",
        r"(a{1,3})+",
        r"(?>a+)+b",
        r"(?:\w|\d)+!",  # Python lo compacta en una clase de caracteres: lineal
    ],
)
def test_redos_allows_linear_patterns(pattern: str) -> None:
    assert checks.regex_risk(pattern) is None


def test_redos_reports_location_in_source(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "adapters/jira/adf.py",
        """
        import re
        BAD = re.compile(r"(a+)+$")
        GOOD = re.compile(r"^#{1,6} (.*)$")
        """,
    )
    assert _rules(tmp_path, "redos") == [("adapters/jira/adf.py", 3)]


# --- env-read -----------------------------------------------------------------------------------


def test_env_read_flags_dotenv_and_secret_variables_outside_config(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/rag/ingest.py",
        """
        import os
        from dotenv import load_dotenv
        load_dotenv()
        url = os.environ["DATABASE_URL"]
        key = os.getenv("JIRA_API_TOKEN")
        text = open(".env").read()
        """,
    )
    assert [line for _p, line in _rules(tmp_path, "env-read")] == [4, 5, 6, 7]


def test_env_read_allows_config_module_and_harmless_variables(tmp_path: Path) -> None:
    _write(tmp_path, "core/config.py", 'import os\nraw = os.environ.get("JIRA_API_TOKEN")\n')
    _write(tmp_path, "app/main.py", 'import os\nci = os.getenv("CI")\nhome = os.environ["HOME"]\n')
    _write(tmp_path, "tests/unit/test_x.py", 'import os\nv = os.getenv("JIRA_BASE_URL")\n')
    assert _rules(tmp_path, "env-read") == []


# --- web ----------------------------------------------------------------------------------------


def test_web_rules_flag_dangerous_patterns(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "web/src/screens/Bad.tsx",
        """
        export function Bad({ html, url }: Props) {
          localStorage.setItem('csrf_token', value)
          const fn = new Function('return 1')
          eval(code)
          return (
            <div dangerouslySetInnerHTML={{ __html: html }}>
              <a href={url}>enlace</a>
              <img src={props.image} />
            </div>
          )
        }
        """,
    )
    found = {(f.rule, f.line) for f in checks.run(tmp_path)}
    assert found == {
        ("web-storage-secret", 3),
        ("web-eval", 4),
        ("web-eval", 5),
        ("web-dangerous-html", 7),
        ("web-dynamic-url", 8),
        ("web-dynamic-url", 9),
    }


def test_web_rules_allow_safe_href_static_assets_comments_and_tests(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "web/src/screens/Good.tsx",
        """
        import logo from './logo.svg'
        // Nunca uses dangerouslySetInnerHTML= ni eval( aquí.
        export function Good({ url }: Props) {
          localStorage.setItem('theme', 'dark')
          return (
            <a href={safeHref(url)}>
              <img src={logo} />
              <img src={'/static/icon.png'} />
            </a>
          )
        }
        """,
    )
    _write(tmp_path, "web/src/screens/Good.test.tsx", "eval('1')\n<a href={url} />\n")
    _write(
        tmp_path,
        "web/eslint.config.js",
        "rules: { selector: \"JSXAttribute[name.name='dangerouslySetInnerHTML']\" }\n",
    )
    assert checks.run(tmp_path) == []


# --- Recorrido, recuento y CLI ------------------------------------------------------------------


def test_excludes_claude_worktrees_docs_and_dependencies(tmp_path: Path) -> None:
    bad = "from adapters.jira.tracker import JiraCloudTracker\n"
    for rel in (
        ".claude/worktrees/area-b/core/rag/x.py",
        "docs/ejemplo/core/x.py",
        ".venv/lib/core/x.py",
        "web/node_modules/core/x.py",
    ):
        _write(tmp_path, rel, bad)
    assert checks.run(tmp_path) == []


def test_targets_limit_scope(tmp_path: Path) -> None:
    bad = "from adapters.jira.tracker import JiraCloudTracker\n"
    _write(tmp_path, "core/rag/x.py", bad)
    _write(tmp_path, "core/qa/y.py", bad)
    assert [f.path for f in checks.run(tmp_path, targets=["core/rag"])] == ["core/rag/x.py"]


def test_summary_lists_every_rule_with_zero_counts(tmp_path: Path) -> None:
    _write(tmp_path, "core/rag/x.py", "from adapters.jira.tracker import JiraCloudTracker\n")
    counts = checks.summary(checks.run(tmp_path))
    assert set(counts) == set(checks.RULES)
    assert counts["core-concrete-import"] == 1
    assert sum(counts.values()) == 1


def test_every_rule_declares_reason(tmp_path: Path) -> None:
    for rule in checks.RULES.values():
        assert rule.reason and rule.severity in {"alta", "media", "baja"}


def test_main_exit_code_and_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(
        tmp_path,
        "api/x.py",
        "def f():\n    try:\n        g()\n    except Exception:\n        pass\n",
    )
    assert checks.main(["--root", str(tmp_path), "--json"]) == 0  # solo media
    assert '"silent-except": 1' in capsys.readouterr().out
    _write(tmp_path, "core/rag/x.py", "from adapters.jira.tracker import JiraCloudTracker\n")
    assert checks.main(["--root", str(tmp_path)]) == 1  # hay una alta
    out = capsys.readouterr().out
    assert "core/rag/x.py:1" in out and "Recuento por regla" in out


def test_main_lists_rules_with_exceptions(capsys: pytest.CaptureFixture[str]) -> None:
    assert checks.main(["--rules"]) == 0
    out = capsys.readouterr().out
    assert "jira-write (alta)" in out and "excepción:" in out


def test_ok_mark_does_not_silence_high_severity_rules(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "core/graph/nodes.py",
        """
        class Nodes:
            def generate(self):
                self.c.issue_tracker.create_story(story, None, "DEMO")  # auditoria: ok prueba
        """,
    )
    assert _rules(tmp_path, "jira-write") == [("core/graph/nodes.py", 4)]


def test_jira_write_checks_url_keyword_and_ignores_read_requests(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "api/service.py",
        """
        def f(client):
            client.request("GET", "/rest/api/3/myself")
            client.post(url="/rest/api/3/issue", json={})
            client.request("PUT", "/rest/api/3/issue/DEMO-1", json={})
        """,
    )
    assert [line for _p, line in _rules(tmp_path, "jira-write")] == [4, 5]


def test_log_sensitive_field_flags_new_fields_but_not_tests(tmp_path: Path) -> None:
    _write(tmp_path, "api/x.py", 'log.info("x", headers=h, database_url=u, cookie=c)\n')
    _write(tmp_path, "tests/unit/test_logs.py", 'log.info("x", headers=h)\n')
    assert _rules(tmp_path, "log-sensitive-field") == [("api/x.py", 1)] * 3  # uno por campo
