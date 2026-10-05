"""T-33: memorias de ejemplo ficticias (`core/memory/seed_demo.py`) para ver la pestaña Memoria.

Solo en `APP_ENV=development`, sin sobrescribir salvo `--forzar`, explicando cómo quitarlas y sin
tocar Jira, el LLM ni el RAG. Todo en `tmp_path`; nunca se escribe en `data/memory/` real.
"""

import ast
import inspect
from pathlib import Path

import pytest

from core.memory import seed_demo
from core.memory.reader import MemoryReader, parse_memory
from core.memory.seed_demo import DEMO_NUMBERS, FICTITIOUS, demo_memories, main, seed
from schemas.common import ArtifactType
from tests.fakes.vector_store import FakeVectorStore

EXPECTED_FILES = ["DEMO-9001.md", "DEMO-9002.md"]


def _names(directory: Path) -> list[str]:
    return sorted(path.name for path in directory.glob("*.md"))


# --- demo_memories ----------


def test_demo_memories_use_project_keys_9001_and_9002() -> None:
    """T-33 · seed_demo: dos memorias `<PROYECTO>-9001` y `<PROYECTO>-9002` del proyecto dado."""
    memories = demo_memories("ABC")
    assert [m.jira_key for m in memories] == ["ABC-9001", "ABC-9002"]
    assert DEMO_NUMBERS == (9001, 9002)
    assert all(m.artifact_type is ArtifactType.USER_STORY for m in memories)


def test_demo_memories_say_they_are_fictitious() -> None:
    """T-33 · seed_demo: los textos dicen que son ficticias."""
    for memory in demo_memories("DEMO"):
        assert "ficticio" in memory.objective.lower()
        assert FICTITIOUS in memory.scope
        assert "FICTICIA" in memory.to_markdown()


def test_demo_memories_roundtrip_through_parse_memory() -> None:
    """T-33 · seed_demo: el `.md` de cada ejemplo se vuelve a leer igual (incluye listas vacías)."""
    for memory in demo_memories("DEMO"):
        assert parse_memory(memory.to_markdown()) == memory


# --- seed ----------


def test_seed_writes_two_memories_readable_and_not_indexed(tmp_path: Path) -> None:
    """T-33 · seed_demo: escribe las dos `.md`; la pestaña las ve como «no indexadas»."""
    memory_dir = tmp_path / "memoria"
    written, skipped = seed(memory_dir, "DEMO")
    assert [p.name for p in written] == EXPECTED_FILES and skipped == []
    rows = MemoryReader(memory_dir, FakeVectorStore()).summaries(["DEMO"])
    assert sorted(row.key for row in rows) == ["DEMO-9001", "DEMO-9002"]
    assert all(row.indexed is False for row in rows)


def test_seed_creates_missing_directory(tmp_path: Path) -> None:
    """T-33 · seed_demo: crea la carpeta de memorias si no existe."""
    memory_dir = tmp_path / "a" / "b"
    seed(memory_dir, "DEMO")
    assert _names(memory_dir) == EXPECTED_FILES


def test_seed_does_not_overwrite_without_force(tmp_path: Path) -> None:
    """T-33 · seed_demo: sin `force`, las que ya existen se omiten y no se tocan."""
    seed(tmp_path, "DEMO")
    edited = tmp_path / "DEMO-9001.md"
    edited.write_text("contenido editado ficticio", encoding="utf-8")
    written, skipped = seed(tmp_path, "DEMO")
    assert written == [] and [p.name for p in skipped] == EXPECTED_FILES
    assert edited.read_text(encoding="utf-8") == "contenido editado ficticio"


def test_seed_overwrites_with_force(tmp_path: Path) -> None:
    """T-33 · seed_demo: con `force`, se sobrescriben."""
    seed(tmp_path, "DEMO")
    edited = tmp_path / "DEMO-9001.md"
    edited.write_text("contenido editado ficticio", encoding="utf-8")
    written, skipped = seed(tmp_path, "DEMO", force=True)
    assert [p.name for p in written] == EXPECTED_FILES and skipped == []
    assert edited.read_text(encoding="utf-8") == demo_memories("DEMO")[0].to_markdown()


def test_seed_writes_lf_line_endings(tmp_path: Path) -> None:
    """T-33 · seed_demo: el `.md` es exactamente `to_markdown()` (LF, también en Windows)."""
    seed(tmp_path, "DEMO")
    raw = (tmp_path / "DEMO-9001.md").read_bytes()
    assert b"\r\n" not in raw
    assert raw.decode("utf-8") == demo_memories("DEMO")[0].to_markdown()


# --- main ----------


def test_main_writes_and_explains_how_to_remove(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-33 · seed_demo: en development escribe, dice que son ficticias y cómo quitarlas."""
    code = main([], app_env="development", memory_dir=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert _names(tmp_path) == EXPECTED_FILES
    assert "Escrita: DEMO-9001.md" in out and "Escrita: DEMO-9002.md" in out
    assert "ficticias" in out
    assert "no están indexadas" in out
    assert "borra DEMO-9001.md y DEMO-9002.md" in out
    assert str(tmp_path) in out


def test_main_project_option_is_normalized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-33 · seed_demo: `--proyecto abc` → claves ABC-9001 y ABC-9002."""
    assert main(["--proyecto", " abc "], app_env="development", memory_dir=tmp_path) == 0
    assert _names(tmp_path) == ["ABC-9001.md", "ABC-9002.md"]
    assert "borra ABC-9001.md y ABC-9002.md" in capsys.readouterr().out


@pytest.mark.parametrize("env", ["production", "test", "", "pre-development"])
def test_main_refuses_outside_development(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], env: str
) -> None:
    """T-33 · seed_demo: se niega (código 2) si APP_ENV no es development y no escribe nada."""
    memory_dir = tmp_path / "memoria"
    assert main([], app_env=env, memory_dir=memory_dir) == 2
    assert "APP_ENV=development" in capsys.readouterr().err
    assert not memory_dir.exists()


@pytest.mark.parametrize("env", ["DEVELOPMENT", " development "])
def test_main_accepts_development_case_and_spaces(tmp_path: Path, env: str) -> None:
    """T-33 · seed_demo · límite: APP_ENV sin distinguir mayúsculas ni espacios."""
    assert main([], app_env=env, memory_dir=tmp_path) == 0
    assert _names(tmp_path) == EXPECTED_FILES


@pytest.mark.parametrize("project", ["1ABC", "A", "DEMO-1", "../X"])
def test_main_rejects_invalid_project(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], project: str
) -> None:
    """T-33 · seed_demo · negativa: clave de proyecto no válida → código 2, sin escribir."""
    assert main(["--proyecto", project], app_env="development", memory_dir=tmp_path) == 2
    assert capsys.readouterr().err.strip()
    assert _names(tmp_path) == []


def test_main_without_force_keeps_existing_and_tells_how_to_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-33 · seed_demo: sin `--forzar` no sobrescribe y lo indica."""
    (tmp_path / "DEMO-9001.md").write_text("editada ficticia", encoding="utf-8")
    assert main([], app_env="development", memory_dir=tmp_path) == 0
    out = capsys.readouterr().out
    assert (tmp_path / "DEMO-9001.md").read_text(encoding="utf-8") == "editada ficticia"
    assert "Ya existía (usa --forzar para sobrescribirla): DEMO-9001.md" in out
    assert "Escrita: DEMO-9002.md" in out


def test_main_with_force_overwrites(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """T-33 · seed_demo: `--forzar` sobrescribe las existentes."""
    (tmp_path / "DEMO-9001.md").write_text("editada ficticia", encoding="utf-8")
    assert main(["--forzar"], app_env="development", memory_dir=tmp_path) == 0
    assert "Escrita: DEMO-9001.md" in capsys.readouterr().out
    assert parse_memory((tmp_path / "DEMO-9001.md").read_text(encoding="utf-8")).version == 2


def test_seed_demo_module_does_not_import_jira_llm_or_rag() -> None:
    """T-33 · seed_demo: no toca Jira, LLM ni RAG (ni lo importa)."""
    tree = ast.parse(inspect.getsource(seed_demo))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("adapters", "core.rag", "core.graph", "core.functional", "core.qa", "openai")
    assert not [name for name in imported if name.startswith(forbidden)], imported
