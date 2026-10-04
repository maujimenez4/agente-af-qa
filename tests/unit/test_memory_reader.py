"""T-33 (RF-36/RF-38): lectura de memorias publicadas (`core/memory/reader.py`).

`parse_memory` como inverso de `Memory.to_markdown()`, `memory_title` y `MemoryReader` (lista,
detalle, «indexada», filtros, orden y defensas de ruta). Solo fakes de `tests/fakes/` y datos
100 % ficticios (Biblioteca de Villaficticia); sin red, sin `.env`, sin LLM ni Jira.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from adapters.base import Chunk
from core.memory.reader import (
    MAX_FILE_BYTES,
    MAX_LIMIT,
    TITLE_MAX_CHARS,
    MemoryReader,
    memory_title,
    parse_memory,
)
from schemas.common import ArtifactType
from schemas.memory import Memory
from tests.fakes.vector_store import FakeVectorStore

VISIBLE = ["DEMO"]
BASE_TIME = 1_790_000_000  # instante fijo y ficticio para los mtime


def make_memory(key: str = "DEMO-9001", **changes: object) -> Memory:
    values: dict[str, object] = {
        "artifact_type": ArtifactType.USER_STORY,
        "jira_key": key,
        "version": 1,
        "objective": f"Objetivo ficticio de {key}: renovar préstamos en Villaficticia.",
        "scope": "Alcance ficticio: solo la web de la biblioteca.",
        "business_rules": ["RN-1: regla ficticia."],
        "decisions": ["Decisión ficticia."],
        "dependencies": [],
        "changes": [],
        "acceptance_criteria": ["CA-1: criterio ficticio."],
        "references": [key],
    }
    return Memory.model_validate(values | changes)


def write(directory: Path, memory: Memory, *, mtime: int | None = None, name: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name or f"{memory.jira_key}.md")
    path.write_text(memory.to_markdown(), encoding="utf-8", newline="\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def indexed_store(*document_ids: str) -> FakeVectorStore:
    store = FakeVectorStore()
    store.upsert(
        [
            Chunk(
                id=f"{document_id}-0",
                document_id=document_id,
                ordinal=0,
                content="Fragmento ficticio de memoria.",
                embedding=[1.0, 0.0],
                metadata={"category": "memoria"},
            )
            for document_id in document_ids
        ]
    )
    return store


@dataclass
class SpyVectorStore(FakeVectorStore):
    asked: list[str] = field(default_factory=list)

    def has_document(self, document_id: str) -> bool:
        self.asked.append(document_id)
        return super().has_document(document_id)


# --- parse_memory: ida y vuelta ----------


def test_parse_memory_roundtrip_returns_equal_memory() -> None:
    """T-33 · CA ida y vuelta: `parse_memory(m.to_markdown()) == m` con todos los campos."""
    memory = make_memory(
        version=3,
        dependencies=["DEMO-9002: reservas ficticias."],
        changes=["v3: cambio ficticio."],
        references=["DEMO-9001", "Corpus ficticio: normativa.md"],
    )
    assert parse_memory(memory.to_markdown()) == memory


def test_parse_memory_roundtrip_with_empty_lists_and_empty_texts() -> None:
    """T-33 · ida y vuelta: listas vacías y textos vacíos (se escriben como «—»)."""
    memory = make_memory(
        objective="",
        scope="",
        business_rules=[],
        decisions=[],
        dependencies=[],
        changes=[],
        acceptance_criteria=[],
        references=[],
    )
    assert "—" in memory.to_markdown()
    assert parse_memory(memory.to_markdown()) == memory


def test_parse_memory_roundtrip_with_multiline_items_and_texts() -> None:
    """T-33 · ida y vuelta: elementos y textos con saltos de línea (incluida una línea vacía)."""
    memory = make_memory(
        objective="Primera línea ficticia.\nSegunda línea ficticia.",
        scope="Párrafo uno.\n\nPárrafo dos.",
        business_rules=["RN-1: línea uno\ncontinúa en la línea dos.", "RN-2: otra."],
        acceptance_criteria=["CA-1: dado algo\n\ncuando otra cosa", "CA-2: simple."],
    )
    assert parse_memory(memory.to_markdown()) == memory


def test_parse_memory_roundtrip_with_other_heading_inside_text() -> None:
    """T-33 · ida y vuelta: un `## Algo` (y `---`) dentro del texto del LLM no abre sección."""
    memory = make_memory(
        objective="Texto ficticio\n## Algo\nmás texto\n---\nfin",
        scope="## Objetivo\nrepetido dentro del alcance",
        business_rules=["RN-1: con encabezado\n## Algo dentro"],
        references=["## Referencias ficticias anidadas"],
    )
    assert parse_memory(memory.to_markdown()) == memory


def test_parse_memory_accepts_crlf_line_endings() -> None:
    """T-33: un `.md` guardado con CRLF (Windows) se lee igual."""
    memory = make_memory(business_rules=["a\nb"])
    assert parse_memory(memory.to_markdown().replace("\n", "\r\n")) == memory


def test_parse_memory_roundtrip_test_suite_artifact_type() -> None:
    """T-33: también memorias de suites de pruebas (otro `artifact_type`)."""
    memory = make_memory(artifact_type=ArtifactType.TEST_SUITE)
    assert parse_memory(memory.to_markdown()) == memory


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# Memoria sin cabecera\n\n## Objetivo\nx\n",
        "---\njira_key: DEMO-1\n",  # cabecera sin cerrar
        "No es una memoria.",
    ],
)
def test_parse_memory_rejects_text_without_header(text: str) -> None:
    """T-33 · negativa: un texto sin la cabecera de memoria da `ValueError`."""
    with pytest.raises(ValueError):
        parse_memory(text)


def test_parse_memory_rejects_missing_section() -> None:
    """T-33 · negativa: falta una sección (p. ej. «Referencias»)."""
    text = make_memory().to_markdown()
    broken = text.split("## Referencias")[0]
    with pytest.raises(ValueError):
        parse_memory(broken)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("version: 1", "version: uno"),
        ("version: 1", "version: 0"),
        ("artifact_type: user_story", "artifact_type: otro_ficticio"),
        ("jira_key: DEMO-9001", "jira_key: "),
    ],
)
def test_parse_memory_rejects_invalid_header_values(old: str, new: str) -> None:
    """T-33 · negativa: valores de cabecera no válidos → `ValueError` (no `ValidationError`)."""
    text = make_memory().to_markdown()
    assert old in text
    with pytest.raises(ValueError):
        parse_memory(text.replace(old, new, 1))


def test_parse_memory_rejects_list_section_with_free_text() -> None:
    """T-33 · negativa: una sección de lista con texto que no es viñeta ni «—»."""
    text = make_memory().to_markdown().replace("- RN-1: regla ficticia.", "texto suelto")
    with pytest.raises(ValueError):
        parse_memory(text)


def test_parse_memory_roundtrip_with_empty_list_item() -> None:
    """T-33 · límite: un elemento vacío en una lista (salida posible del LLM) debería
    sobrevivir la ida y vuelta; hoy `parse_memory` lanza `ValueError` y la memoria desaparece de
    la pestaña."""
    memory = make_memory(business_rules=[""])
    assert parse_memory(memory.to_markdown()) == memory


def test_parse_memory_roundtrip_with_next_section_heading_inside_text() -> None:
    """T-33 · PA-288: un `## Alcance` dentro del objetivo (el título de la sección siguiente)
    no abre la sección: `to_markdown` lo escapa."""
    memory = make_memory(objective="Texto ficticio\n## Alcance\nsigue el objetivo")
    assert parse_memory(memory.to_markdown()) == memory


@pytest.mark.parametrize(
    "fields",
    [
        {"scope": "Alcance ficticio\n## Reglas de negocio\n- no es una regla"},
        {"business_rules": ["Regla ficticia\n- no es otra regla", "-5 grados como dato"]},
        {"decisions": ["Decisión ficticia\n## Dependencias\n—"]},
        {"objective": "—"},
        {"changes": ["\\ya empezaba por barra", "C:\\ruta\\ficticia"]},
        {"references": ["# título de markdown ficticio"]},
    ],
)
def test_parse_memory_roundtrip_with_structure_like_lines(fields: dict[str, object]) -> None:
    """PA-288: líneas del LLM que parecen estructura (títulos, `- `, «—», barra) vuelven igual."""
    memory = make_memory(**fields)
    assert parse_memory(memory.to_markdown()) == memory


def test_to_markdown_escapes_only_structure_like_lines() -> None:
    """PA-288: el escape es el de markdown (una barra delante) y solo en las líneas que lo
    necesitan; el resto del texto no cambia."""
    markdown = make_memory(objective="Objetivo ficticio\n## Alcance\nfin").to_markdown()
    assert "Objetivo ficticio\n\\## Alcance\nfin" in markdown
    assert "\n## Alcance\n" in markdown  # el título real de la sección sigue intacto


# --- memory_title ----------


def test_memory_title_is_objective_in_one_line() -> None:
    """T-33: el título es el objetivo en una sola línea (espacios y saltos colapsados)."""
    memory = make_memory(objective="  Renovar\npréstamos   ficticios\n\n en la web ")
    assert memory_title(memory) == "Renovar préstamos ficticios en la web"


@pytest.mark.parametrize("objective", ["", "   ", "\n\n"])
def test_memory_title_falls_back_to_key_when_objective_empty(objective: str) -> None:
    """T-33: sin objetivo, «Memoria de CLAVE»."""
    assert memory_title(make_memory(objective=objective)) == "Memoria de DEMO-9001"


def test_memory_title_keeps_objective_of_exactly_max_chars() -> None:
    """T-33 · límite: 120 caracteres exactos no se recortan."""
    objective = "a" * TITLE_MAX_CHARS
    assert memory_title(make_memory(objective=objective)) == objective


def test_memory_title_truncates_long_objective_with_ellipsis() -> None:
    """T-33 · límite: 121 caracteres → recortado a 120 con «…» al final."""
    title = memory_title(make_memory(objective="b" * (TITLE_MAX_CHARS + 1)))
    assert len(title) == TITLE_MAX_CHARS
    assert title == "b" * (TITLE_MAX_CHARS - 1) + "…"


def test_memory_title_truncation_strips_trailing_space_before_ellipsis() -> None:
    """T-33: si el corte cae tras un espacio, no queda «palabra …»."""
    objective = "c" * (TITLE_MAX_CHARS - 2) + " " + "d" * 10
    title = memory_title(make_memory(objective=objective))
    assert title == "c" * (TITLE_MAX_CHARS - 2) + "…"


# --- MemoryReader.summaries ----------


def test_summaries_lists_memories_with_summary_fields(tmp_path: Path) -> None:
    """T-33 · lista: clave, proyecto, título, versión, fecha (UTC) e indexada."""
    write(tmp_path, make_memory("DEMO-9001", version=2), mtime=BASE_TIME)
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)
    assert len(rows) == 1
    row = rows[0]
    assert row.key == "DEMO-9001"
    assert row.project == "DEMO"
    assert row.title == memory_title(make_memory("DEMO-9001"))
    assert row.version == 2
    assert row.updated_at.timestamp() == BASE_TIME
    assert (
        row.updated_at.utcoffset() is not None and row.updated_at.utcoffset().total_seconds() == 0
    )
    assert row.indexed is False


def test_summaries_empty_directory_returns_empty_list(tmp_path: Path) -> None:
    """T-33 · lista vacía: carpeta sin memorias."""
    assert MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE) == []


def test_summaries_missing_directory_returns_empty_list(tmp_path: Path) -> None:
    """T-33 · lista vacía: la carpeta de memorias aún no existe (no se crea al leer)."""
    missing = tmp_path / "no-existe"
    assert MemoryReader(missing, FakeVectorStore()).summaries(VISIBLE) == []
    assert not missing.exists()


def test_summaries_marks_indexed_when_vector_store_has_document(tmp_path: Path) -> None:
    """T-33 · indexada: true si el vector store tiene `memoria-<CLAVE>`, false si no."""
    write(tmp_path, make_memory("DEMO-9001"), mtime=BASE_TIME + 1)
    write(tmp_path, make_memory("DEMO-9002"), mtime=BASE_TIME)
    store = indexed_store("memoria-DEMO-9001", "DEMO-9002")  # el segundo sin el prefijo
    rows = MemoryReader(tmp_path, store).summaries(VISIBLE)
    assert {row.key: row.indexed for row in rows} == {"DEMO-9001": True, "DEMO-9002": False}


def test_summaries_orders_most_recent_first(tmp_path: Path) -> None:
    """T-33 · orden: más recientes primero según la fecha de modificación."""
    write(tmp_path, make_memory("DEMO-1"), mtime=BASE_TIME + 10)
    write(tmp_path, make_memory("DEMO-2"), mtime=BASE_TIME + 30)
    write(tmp_path, make_memory("DEMO-3"), mtime=BASE_TIME + 20)
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)
    assert [row.key for row in rows] == ["DEMO-2", "DEMO-3", "DEMO-1"]


def test_summaries_same_mtime_has_stable_order(tmp_path: Path) -> None:
    """T-33 · orden: con la misma fecha, orden estable (por clave, descendente)."""
    for key in ("DEMO-1", "DEMO-3", "DEMO-2"):
        write(tmp_path, make_memory(key), mtime=BASE_TIME)
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)
    assert [row.key for row in rows] == ["DEMO-3", "DEMO-2", "DEMO-1"]


def test_summaries_hides_projects_not_visible(tmp_path: Path) -> None:
    """T-33 · proyecto no visible: sus memorias no aparecen en la lista."""
    write(tmp_path, make_memory("DEMO-1"))
    write(tmp_path, make_memory("OTRO-1"))
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)
    assert [row.key for row in rows] == ["DEMO-1"]
    assert MemoryReader(tmp_path, FakeVectorStore()).summaries([]) == []


def test_summaries_filters_by_project(tmp_path: Path) -> None:
    """T-33 · filtro `project`: solo ese proyecto, y nunca uno que no sea visible."""
    write(tmp_path, make_memory("DEMO-1"))
    write(tmp_path, make_memory("OTRO-1"))
    write(tmp_path, make_memory("AJENO-1"))
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert [r.key for r in reader.summaries(["DEMO", "OTRO"], project="OTRO")] == ["OTRO-1"]
    assert [r.key for r in reader.summaries(["DEMO", "OTRO"], project="DEMO")] == ["DEMO-1"]
    assert reader.summaries(["DEMO", "OTRO"], project="AJENO") == []


def test_summaries_query_matches_key_case_insensitive(tmp_path: Path) -> None:
    """T-33 · búsqueda `q`: en la clave, sin distinguir mayúsculas."""
    write(tmp_path, make_memory("DEMO-9001"))
    write(tmp_path, make_memory("DEMO-9002"))
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, query="demo-9002")
    assert [row.key for row in rows] == ["DEMO-9002"]


def test_summaries_query_matches_text_case_insensitive(tmp_path: Path) -> None:
    """T-33 · búsqueda `q`: en el texto de la memoria, sin distinguir mayúsculas."""
    write(tmp_path, make_memory("DEMO-1", scope="Incluye la cola de RESERVAS ficticias."))
    write(tmp_path, make_memory("DEMO-2", business_rules=["RN-1: sobre reservas ficticias."]))
    write(tmp_path, make_memory("DEMO-3"))
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, query="  Reservas ")
    assert sorted(row.key for row in rows) == ["DEMO-1", "DEMO-2"]


def test_summaries_query_without_match_returns_empty(tmp_path: Path) -> None:
    """T-33 · búsqueda `q` sin coincidencias."""
    write(tmp_path, make_memory("DEMO-1"))
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert reader.summaries(VISIBLE, query="xyzzy-inexistente") == []


def test_summaries_blank_query_returns_all(tmp_path: Path) -> None:
    """T-33 · búsqueda `q` en blanco equivale a no buscar."""
    write(tmp_path, make_memory("DEMO-1"))
    write(tmp_path, make_memory("DEMO-2"))
    assert len(MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, query="   ")) == 2


def test_summaries_limit_returns_most_recent(tmp_path: Path) -> None:
    """T-33 · `limit`: se devuelven las N más recientes."""
    for number in range(1, 6):
        write(tmp_path, make_memory(f"DEMO-{number}"), mtime=BASE_TIME + number)
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, limit=2)
    assert [row.key for row in rows] == ["DEMO-5", "DEMO-4"]


@pytest.mark.parametrize(("limit", "expected"), [(0, 1), (-5, 1)])
def test_summaries_limit_below_one_is_clamped_to_one(
    tmp_path: Path, limit: int, expected: int
) -> None:
    """T-33 · límite: `limit` < 1 se ajusta a 1."""
    write(tmp_path, make_memory("DEMO-1"))
    write(tmp_path, make_memory("DEMO-2"))
    assert (
        len(MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, limit=limit)) == expected
    )


def test_summaries_limit_above_max_is_clamped(tmp_path: Path) -> None:
    """T-33 · límite: `limit` > 200 se ajusta a 200."""
    for number in range(1, MAX_LIMIT + 2):
        write(tmp_path, make_memory(f"DEMO-{number}"))
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE, limit=10_000)
    assert len(rows) == MAX_LIMIT


def test_summaries_asks_vector_store_only_for_returned_rows(tmp_path: Path) -> None:
    """T-33: el vector store solo se consulta para lo que se devuelve."""
    for number in range(1, 4):
        write(tmp_path, make_memory(f"DEMO-{number}"), mtime=BASE_TIME + number)
    spy = SpyVectorStore()
    MemoryReader(tmp_path, spy).summaries(VISIBLE, limit=1)
    assert spy.asked == ["memoria-DEMO-3"]


def test_summaries_ignores_non_memory_files(tmp_path: Path) -> None:
    """T-33 · seguridad: archivos que no son memorias se ignoran sin romper la lista."""
    write(tmp_path, make_memory("DEMO-1"))
    (tmp_path / "README.md").write_text("# Léeme ficticio\n", encoding="utf-8")
    (tmp_path / "DEMO-2.md").write_text("No es una memoria.", encoding="utf-8")
    (tmp_path / "DEMO-3.md").write_bytes(b"\xff\xfe\x00 bytes no utf-8 \x80")
    (tmp_path / "DEMO-4.txt").write_text(make_memory("DEMO-4").to_markdown(), encoding="utf-8")
    (tmp_path / "demo-5.md").write_text("minúsculas no son clave", encoding="utf-8")
    (tmp_path / "DEMO-6.md").mkdir()  # una carpeta con nombre de memoria
    rows = MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)
    assert [row.key for row in rows] == ["DEMO-1"]


def test_summaries_ignores_file_whose_header_key_differs(tmp_path: Path) -> None:
    """T-33 · seguridad: la cabecera `jira_key` no puede hacerse pasar por otra HU."""
    write(tmp_path, make_memory("DEMO-1"), name="DEMO-2.md")
    write(tmp_path, make_memory("OTRO-1"), name="DEMO-3.md")  # proyecto no visible disfrazado
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert reader.summaries(VISIBLE) == []
    assert reader.get("DEMO-2", VISIBLE) is None
    assert reader.get("DEMO-3", VISIBLE) is None


def test_summaries_ignores_file_larger_than_limit(tmp_path: Path) -> None:
    """T-33 · seguridad / límite: > 256 KB se ignora; exactamente 256 KB se lee."""
    base = make_memory("DEMO-1", objective="x").to_markdown().encode("utf-8")
    exact = make_memory("DEMO-1", objective="x" * (MAX_FILE_BYTES - len(base) + 1))
    over = make_memory("DEMO-2", objective="x" * (MAX_FILE_BYTES - len(base) + 2))
    write(tmp_path, exact)
    write(tmp_path, over)
    assert (tmp_path / "DEMO-1.md").stat().st_size == MAX_FILE_BYTES
    assert (tmp_path / "DEMO-2.md").stat().st_size == MAX_FILE_BYTES + 1
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert [row.key for row in reader.summaries(VISIBLE)] == ["DEMO-1"]
    assert reader.get("DEMO-2", VISIBLE) is None
    assert reader.get("DEMO-1", VISIBLE) is not None


def test_summaries_reads_crlf_file(tmp_path: Path) -> None:
    """T-33: un `.md` con finales CRLF aparece en la lista."""
    path = tmp_path / "DEMO-1.md"
    path.write_bytes(make_memory("DEMO-1").to_markdown().replace("\n", "\r\n").encode("utf-8"))
    assert [row.key for row in MemoryReader(tmp_path, FakeVectorStore()).summaries(VISIBLE)] == [
        "DEMO-1"
    ]


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"El sistema no permite crear enlaces simbólicos: {type(exc).__name__}")


def test_symlink_pointing_outside_memory_dir_is_ignored(tmp_path: Path) -> None:
    """T-33 · seguridad: un enlace simbólico a un archivo fuera de `memory_dir` no se lee."""
    memory_dir = tmp_path / "memoria"
    outside = write(tmp_path / "fuera", make_memory("DEMO-7"))
    memory_dir.mkdir()
    _symlink(memory_dir / "DEMO-7.md", outside)
    reader = MemoryReader(memory_dir, FakeVectorStore())
    assert reader.summaries(VISIBLE) == []
    assert reader.get("DEMO-7", VISIBLE) is None


def test_symlinked_memory_dir_is_followed(tmp_path: Path) -> None:
    """T-33: si la propia carpeta de memorias es un enlace, sus archivos sí se leen."""
    real = tmp_path / "real"
    write(real, make_memory("DEMO-8"))
    link = tmp_path / "enlace"
    _symlink(link, real)
    reader = MemoryReader(link, FakeVectorStore())
    assert [row.key for row in reader.summaries(VISIBLE)] == ["DEMO-8"]
    assert reader.get("DEMO-8", VISIBLE) is not None


# --- MemoryReader.get ----------


def test_get_returns_document_with_summary_memory_and_markdown(tmp_path: Path) -> None:
    """T-33 · detalle: resumen, memoria estructurada y el `.md` tal cual."""
    memory = make_memory("DEMO-9001", version=2)
    path = write(tmp_path, memory, mtime=BASE_TIME)
    document = MemoryReader(tmp_path, indexed_store("memoria-DEMO-9001")).get("DEMO-9001", VISIBLE)
    assert document is not None
    assert document.memory == memory
    assert document.markdown == path.read_text(encoding="utf-8")
    assert document.summary.key == "DEMO-9001"
    assert document.summary.version == 2
    assert document.summary.indexed is True
    assert document.summary.updated_at.timestamp() == BASE_TIME


@pytest.mark.parametrize("raw", ["demo-9001", "  DEMO-9001 ", "Demo-9001"])
def test_get_normalizes_key_case_and_spaces(tmp_path: Path, raw: str) -> None:
    """T-33: la clave se normaliza (mayúsculas, sin espacios)."""
    write(tmp_path, make_memory("DEMO-9001"))
    document = MemoryReader(tmp_path, FakeVectorStore()).get(raw, VISIBLE)
    assert document is not None and document.summary.key == "DEMO-9001"


def test_get_returns_none_when_memory_missing(tmp_path: Path) -> None:
    """T-33 · negativa: memoria inexistente → None."""
    write(tmp_path, make_memory("DEMO-1"))
    assert MemoryReader(tmp_path, FakeVectorStore()).get("DEMO-404", VISIBLE) is None


def test_get_returns_none_when_directory_missing(tmp_path: Path) -> None:
    """T-33 · negativa: carpeta de memorias inexistente → None."""
    assert MemoryReader(tmp_path / "no-existe", FakeVectorStore()).get("DEMO-1", VISIBLE) is None


def test_get_returns_none_for_project_not_visible(tmp_path: Path) -> None:
    """T-33 · proyecto no visible: el archivo existe pero la conexión no ve el proyecto."""
    write(tmp_path, make_memory("OTRO-1"))
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert reader.get("OTRO-1", VISIBLE) is None
    assert reader.get("OTRO-1", ["OTRO"]) is not None


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "DEMO",
        "DEMO-",
        "-1",
        "1DEMO-1",
        "DEMO-1.md",
        "DEMO-1/",
        "../DEMO-1",
        "..\\DEMO-1",
        "DEMO-1/../DEMO-1",
        "fuera/DEMO-1",
        "DEMO-1\x00",
        "DEMO-1\nDEMO-2",
    ],
)
def test_get_returns_none_for_invalid_key_or_traversal(tmp_path: Path, raw: str) -> None:
    """T-33 · seguridad: clave no válida o con `../` → None, aunque exista el archivo."""
    memory_dir = tmp_path / "memoria"
    write(memory_dir, make_memory("DEMO-1"))
    write(tmp_path, make_memory("DEMO-1"))  # una «memoria» fuera de memory_dir
    write(tmp_path / "fuera", make_memory("DEMO-1"))
    assert MemoryReader(memory_dir, FakeVectorStore()).get(raw, VISIBLE) is None


def test_get_returns_none_for_unreadable_file(tmp_path: Path) -> None:
    """T-33 · negativa: archivo ilegible (no UTF-8) o que no es memoria → None."""
    (tmp_path / "DEMO-1.md").write_bytes(b"\x80\x81\x82")
    (tmp_path / "DEMO-2.md").write_text("texto ficticio sin formato", encoding="utf-8")
    reader = MemoryReader(tmp_path, FakeVectorStore())
    assert reader.get("DEMO-1", VISIBLE) is None
    assert reader.get("DEMO-2", VISIBLE) is None
