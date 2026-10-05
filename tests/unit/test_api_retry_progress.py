"""Progreso de un reintento (PA-276): el paso que se repite sale «en curso» y lo anterior, hecho.

Hallazgo de la prueba de la web contra la API (2026-10-05): tras «Reintentar», el SSE dejaba
todos los pasos en `pending` hasta el final, sin ningún `running`, y la Q no se animaba.
"""

import pytest

from api.runtime import Run, RunRegistry
from api.service import GENERATION_NODES, PUBLISH_NODES, _progress, retry_nodes


def _run(operation: str, rerun: tuple[str, ...] = (), nodes: list[str] | None = None) -> Run:
    registry = RunRegistry()
    run = Run(
        thread_id="hilo-ficticio",
        owner="af-ficticio",
        flow="evolve",
        mode="functional",
        project="DEMO",
        title="Evolucionar DEMO-3",
    )
    registry.add(run)
    assert registry.begin(run, operation, rerun)
    run.nodes.extend(nodes or [])
    return run


def _states(run: Run, values: dict[str, object] | None = None) -> dict[str, str]:
    return {step.node: step.state for step in _progress("generating", run, values or {})}


@pytest.mark.parametrize(
    ("failed", "expected"),
    [
        (["load_origin"], GENERATION_NODES),
        (["retrieve_context"], ("retrieve_context", "generate")),
        (["generate"], ("generate",)),
        (["memorize"], ("memorize",)),
        (["publish"], PUBLISH_NODES),
        ([], ()),
        (["nodo-desconocido"], ()),
    ],
)
def test_retry_nodes_from_the_failed_node_to_the_end_of_its_block(
    failed: list[str], expected: tuple[str, ...]
) -> None:
    assert retry_nodes(failed) == expected


def test_retry_of_generate_marks_it_running_and_previous_steps_done() -> None:
    states = _states(_run("retry", ("generate",)))

    assert states == {
        "load_origin": "done",
        "retrieve_context": "done",
        "generate": "running",
        "publish": "pending",
        "memorize": "pending",
    }


def test_retry_from_the_context_advances_step_by_step() -> None:
    run = _run("retry", ("retrieve_context", "generate"))
    assert _states(run)["retrieve_context"] == "running"
    assert _states(run)["generate"] == "pending"

    run.nodes.append("retrieve_context")

    states = _states(run)
    assert states["load_origin"] == states["retrieve_context"] == "done"
    assert states["generate"] == "running"


def test_retry_of_memorize_keeps_generation_and_publication_done() -> None:
    states = _states(_run("retry", ("memorize",)))

    assert [states[n] for n in (*GENERATION_NODES, "publish")] == ["done"] * 4
    assert states["memorize"] == "running"


def test_begin_resets_rerun_for_other_operations() -> None:
    registry = RunRegistry()
    run = _run("retry", ("generate",))
    registry.add(run)
    registry.finish(run)

    assert registry.begin(run, "iterate")
    assert run.rerun == ()
    assert _states(run)["generate"] == "running"


def test_start_without_rerun_is_unchanged() -> None:
    states = _states(_run("start"))

    assert states["load_origin"] == "running"
    assert all(states[n] == "pending" for n in ("retrieve_context", "generate", *PUBLISH_NODES))
