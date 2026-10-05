"""Prueba de punta a punta del agente con los modelos locales de Ollama (sin escribir en Jira).

Compone la aplicación real (`build_config`, `model_router`, `build_app_container`,
`build_checkpointer`, `build_graph`) y recorre los escenarios con usuarios de demo, sin login:

- a: necesidad nueva en el proyecto de `JIRA_PROJECT_KEY` → aprobar;
- b: evolucionar una HU del seed → aprobar (y memoria de la versión aprobada, sin guardarla);
- c: QA sobre esa HU → aprobar;
- d: necesidad nueva → iterar una vez con feedback → aprobar;
- e: `QualityReviewer` sobre la HU del seed;
- f: `GuidedStart.propose` con un texto que nombra la clave en minúsculas.

De cada escenario imprime los nodos y su tiempo, la versión, los CA/RN, las fuentes, el plan, el
modelo y los tokens de cada llamada al LLM, la aprobación con la huella del payload, el `publish`
de la auditoría (`simulated=true`) y el estado en `conversations.list_for(user)`. Guarda un resumen
JSON por escenario en `docs/pruebas/salidas/e2e-<escenario>.json`.

Nunca `live`: si `JIRA_PUBLISH_MODE` no es `simulation`, se detiene antes de componer nada.

Uso: uv run python -m eval.e2e_local {a,b,c,d,e,f,all} [--story-key CLAVE] [--fakes]
(`--fakes`: ensayo del script en segundos con `tests/fakes`, sin Jira, LLM ni BD)
"""

import argparse
import json
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from langgraph.types import Command

from adapters.base import LLMProvider, LLMResult, Message, StructuredResult, TaskType, User
from core.config import AppConfig, build_config
from core.container import Container
from core.conversations import new_conversation_config
from core.factories import (
    build_app_container,
    build_checkpointer,
    build_handoffs,
    model_router,
)
from core.graph import build_graph
from core.graph.state import initial_state
from core.guided_start import GuidedStart
from core.memory.generator import LLMMemoryGenerator
from core.quality import QualityReviewer
from schemas.artifact import Artifact
from schemas.test_case import TestSuite
from schemas.user_story import UserStory

OUT_DIR = Path("docs/pruebas/salidas")
ANALYST = User(username="af-demo", role="functional")
QA = User(username="qa-demo", role="qa")
SEED_STORY = "[HU-02]"  # «Renovar un préstamo» del seed de Villaficticia
NEED = (
    "Como persona socia de la Biblioteca Municipal de Villaficticia quiero reservar un "
    "ejemplar desde la web para recogerlo en el mostrador (necesidad ficticia)."
)
EVOLVE_FEEDBACK = (
    "Permitir renovar también desde la app móvil, con el mismo límite de renovaciones."
)
ITERATE_FEEDBACK = (
    "Añade un criterio de aceptación para cuando la persona socia ya tiene 3 reservas activas."
)


# --- Observación del LLM -----------------------------------------------------------------------


@dataclass
class CountingLLM:
    """Envuelve el `LLMProvider` real y anota cada llamada (tarea, modelo, tokens y tiempo)."""

    inner: LLMProvider
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, messages: list[Message], task: TaskType) -> LLMResult:
        start = time.perf_counter()
        try:
            result = self.inner.generate(messages, task)
        except Exception as exc:
            self._failed(task, start, exc)
            raise
        self._record(task, result, start)
        return result

    def generate_structured[T](
        self, messages: list[Message], schema: type[T], task: TaskType
    ) -> StructuredResult[T]:
        start = time.perf_counter()
        try:
            result = self.inner.generate_structured(messages, schema, task)  # type: ignore[type-var]
        except Exception as exc:
            self._failed(task, start, exc)
            raise
        self._record(task, result, start)
        return result

    def _record(self, task: TaskType, result: Any, start: float) -> None:
        self.calls.append(
            {
                "task": task.value,
                "model": f"{result.provider}/{result.model}",
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "seconds": round(time.perf_counter() - start, 1),
            }
        )

    def _failed(self, task: TaskType, start: float, exc: Exception) -> None:
        self.calls.append(
            {
                "task": task.value,
                "error": type(exc).__name__,
                "seconds": round(time.perf_counter() - start, 1),
            }
        )


@dataclass
class App:
    config: AppConfig
    container: Container
    llm: CountingLLM
    graph: Any


def compose() -> App:
    config = build_config()
    if config.settings.jira_publish_mode != "simulation":
        raise SystemExit("JIRA_PUBLISH_MODE no es «simulation»: esta prueba nunca escribe en Jira.")
    router = model_router(config)
    base = build_app_container(config, router=router)
    llm = CountingLLM(base.llm)
    container = replace(base, llm=llm, memory_generator=LLMMemoryGenerator(llm))
    if container.publish_mode != "simulation":
        raise SystemExit("El contenedor no está en modo simulación.")
    graph = build_graph(
        container, checkpointer=build_checkpointer(config), handoffs=build_handoffs(config)
    )
    return App(config, container, llm, graph)


# --- Grafo -------------------------------------------------------------------------------------


def run_until_pause(app: App, graph_input: Any, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Ejecuta hasta la siguiente pausa o el final; un registro por nodo con su tiempo y sus LLM."""
    steps: list[dict[str, Any]] = []
    last = time.perf_counter()
    seen = len(app.llm.calls)
    for update in app.graph.stream(graph_input, config, stream_mode="updates"):
        now = time.perf_counter()
        for node in update:
            if node.startswith("__"):
                continue
            calls = app.llm.calls[seen:]
            seen = len(app.llm.calls)
            steps.append({"node": node, "seconds": round(now - last, 1), "llm": calls})
            print(f"  · {node:<17} {now - last:7.1f} s  {_calls_text(calls)}", flush=True)
        last = now
    return steps


def _calls_text(calls: list[dict[str, Any]]) -> str:
    return " | ".join(
        f"{c['task']} {c.get('model', c.get('error'))} "
        f"{c.get('input_tokens', '-')}→{c.get('output_tokens', '-')} tok {c['seconds']} s"
        for c in calls
    )


def pending(app: App, config: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = app.graph.get_state(config)
    values = [
        i.value
        for task in snapshot.tasks or ()
        for i in getattr(task, "interrupts", ()) or ()
        if isinstance(getattr(i, "value", None), dict)
    ]
    return values[-1] if values else None


def describe(payload: dict[str, Any]) -> dict[str, Any]:
    artifact = Artifact.model_validate(payload["artifact"])
    content = artifact.content
    info: dict[str, Any] = {
        "version": artifact.version,
        "status": artifact.status.value,
        "model_used": artifact.model_used,
        "prompt_version": artifact.prompt_version,
        "target": payload.get("target"),
        "plan": payload.get("plan"),
        "error": payload.get("error"),
        "fingerprint": str(payload.get("fingerprint", ""))[:16] + "…",
    }
    if isinstance(content, UserStory):
        info |= {
            "title": content.title,
            "acceptance_criteria": len(content.acceptance_criteria),
            "business_rules": len(content.business_rules),
            "sources": [f"{s.kind}:{s.ref}" for s in content.sources],
            "open_questions": len(content.open_questions),
        }
    elif isinstance(content, TestSuite):
        info |= {
            "story_jira_key": content.story_jira_key,
            "cases": len(content.cases),
            "coverage": sorted(content.coverage()),
            "sources": [f"{s.kind}:{s.ref}" for s in content.sources],
        }
    if artifact.impact:
        info["impact"] = {
            "diffs": len(artifact.impact.diffs),
            "affected": [i.jira_key for i in artifact.impact.affected],
            "regression_notes": len(artifact.impact.regression_notes),
        }
    for key, value in info.items():
        print(f"    {key}: {value}", flush=True)
    return info


def approve(app: App, config: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    print(f"  → aprobar con la huella del payload ({str(payload['fingerprint'])[:16]}…)")
    answer = {"decision": "approve", "fingerprint": payload["fingerprint"]}
    return run_until_pause(app, Command(resume=answer), config)


def audit_and_list(app: App, config: dict[str, Any], user: User) -> dict[str, Any]:
    values = app.graph.get_state(config).values
    artifact = values.get("artifact")
    entries = app.container.audit.entries(artifact.id) if artifact else []
    publishes = [
        {"action": e.action, "detail_simulated": (e.detail or {}).get("simulated")}
        for e in entries
        if e.action == "publish"
    ]
    thread_id = config["configurable"]["thread_id"]
    rows = [
        r for r in app.container.conversations.list_for(user.username) if r.thread_id == thread_id
    ]
    result = {
        "artifact_status": artifact.status.value if artifact else None,
        "audit_actions": [e.action for e in entries],
        "audit_publish": publishes,
        "conversation_status": rows[0].status if rows else None,
        "errors": values.get("errors"),
    }
    for key, value in result.items():
        print(f"    {key}: {value}", flush=True)
    return result


def graph_flow(
    app: App,
    summary: dict[str, Any],
    user: User,
    mode: str,
    origin: dict[str, Any],
    feedback: list[str] | None = None,
    iterate_with: str | None = None,
) -> None:
    """Rellena `summary` a medida que avanza: un fallo posterior no pierde lo ya medido."""
    config = new_conversation_config(user.username)
    state = initial_state(user.username, mode, origin, feedback=feedback)  # type: ignore[arg-type]
    started = time.perf_counter()
    summary |= {"user": user.username, "mode": mode, "origin": origin, "steps": []}
    summary["thread_id"] = config["configurable"]["thread_id"]
    summary["steps"] += run_until_pause(app, state, config)
    payload = pending(app, config)
    if payload is None:
        summary["error"] = "el grafo terminó sin pausa de revisión"
        return
    summary["review"] = [describe(payload)]
    if iterate_with:
        print(f"  → iterar: {iterate_with}")
        answer = {"decision": "iterate", "feedback": iterate_with}
        summary["steps"] += run_until_pause(app, Command(resume=answer), config)
        payload = pending(app, config)
        if payload is None:
            summary["error"] = "la iteración terminó sin pausa de revisión"
            return
        summary["review"].append(describe(payload))
    summary["steps"] += approve(app, config, payload)
    summary["total_seconds"] = round(time.perf_counter() - started, 1)
    summary["_final_artifact"] = app.graph.get_state(config).values.get("artifact")
    try:
        summary["after_approve"] = audit_and_list(app, config, user)
    except Exception as exc:  # solo una nota: lo medido ya está en `summary`
        summary["after_approve"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        print(f"    ✗ auditoría/lista: {summary['after_approve']['error']}", flush=True)


# --- Escenarios --------------------------------------------------------------------------------


def seed_story_key(app: App, project: str) -> str:
    jql = f'project = "{project}" AND issuetype in standardIssueTypes() ORDER BY key ASC'
    for issue in app.container.issue_tracker.search(jql, limit=100):
        if issue.summary.startswith(SEED_STORY):
            return issue.key
    raise SystemExit(f"No se encuentra la HU {SEED_STORY} del seed en {project}.")


def scenario_a(app: App, project: str, _key: str, summary: dict[str, Any]) -> None:
    origin = {"kind": "need", "text": NEED, "project": project}
    graph_flow(app, summary, ANALYST, "functional", origin)


def scenario_b(app: App, _project: str, key: str, summary: dict[str, Any]) -> None:
    origin = {"kind": "story", "key": key}
    graph_flow(app, summary, ANALYST, "functional", origin, feedback=[EVOLVE_FEEDBACK])
    artifact = summary.get("_final_artifact")
    if isinstance(artifact, Artifact):
        # La memoria solo se genera al publicar (D-07); aquí se mide sin guardarla ni indexarla.
        print("  · memoria (synthesize_memory, sin guardar)")
        seen = len(app.llm.calls)
        start = time.perf_counter()
        try:
            memory = app.container.memory_generator.generate(artifact)
        except Exception as exc:
            summary["memory"] = {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
        else:
            summary["memory"] = {
                "jira_key": memory.jira_key,
                "business_rules": len(memory.business_rules),
                "markdown_chars": len(memory.to_markdown()),
            }
        summary["memory"] |= {
            "seconds": round(time.perf_counter() - start, 1),
            "llm": app.llm.calls[seen:],
        }
        print(f"    {summary['memory']}", flush=True)


def scenario_c(app: App, _project: str, key: str, summary: dict[str, Any]) -> None:
    graph_flow(app, summary, QA, "qa", {"kind": "story", "key": key})


def scenario_d(app: App, project: str, _key: str, summary: dict[str, Any]) -> None:
    origin = {"kind": "need", "text": NEED, "project": project}
    graph_flow(app, summary, ANALYST, "functional", origin, iterate_with=ITERATE_FEEDBACK)


def scenario_e(app: App, _project: str, key: str, summary: dict[str, Any]) -> None:
    seen = len(app.llm.calls)
    start = time.perf_counter()
    review = QualityReviewer(app.container).review(ANALYST, key)
    report = review.report
    summary |= {
        "jira_key": review.jira_key,
        "model": f"{review.provider}/{review.model}",
        "prompt_version": review.prompt_version,
        "tokens": [review.input_tokens, review.output_tokens],
        "invest": {c.letter: c.verdict for c in report.invest},
        "findings": len(report.findings),
        "open_questions": len(report.open_questions),
        "sources": [f"{s.kind}:{s.ref}" for s in report.sources],
        "seconds": round(time.perf_counter() - start, 1),
        "llm": app.llm.calls[seen:],
    }
    for k, v in summary.items():
        print(f"    {k}: {v}", flush=True)


def scenario_f(app: App, project: str, key: str, summary: dict[str, Any]) -> None:
    text = f"quiero evolucionar la {key.lower()} para que se pueda renovar desde el móvil"
    start = time.perf_counter()
    proposal = GuidedStart(app.container).propose(text, project)
    summary |= {
        "text": text,
        "project": proposal.project,
        "project_changed": proposal.project_changed,
        "recognized": [i.key for i in proposal.recognized],
        "options": [
            {"kind": o.kind, "label": o.label, "origin": dict(o.origin)} for o in proposal.options
        ],
        "seconds": round(time.perf_counter() - start, 2),
    }
    for k, v in summary.items():
        print(f"    {k}: {v}", flush=True)


SCENARIOS = {
    "a": scenario_a,
    "b": scenario_b,
    "c": scenario_c,
    "d": scenario_d,
    "e": scenario_e,
    "f": scenario_f,
}


def _jsonable(summary: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in summary.items() if not k.startswith("_")}


def compose_fakes() -> tuple[App, str, str]:
    """Ensayo del script en segundos: los fakes de `tests/fakes`, en simulación y sin servicios."""
    from tests.fakes import dataset
    from tests.fakes.container import fake_container

    base = fake_container(Path(tempfile.mkdtemp()), publish_mode="simulation")
    llm = CountingLLM(base.llm)
    container = replace(base, llm=llm)
    graph = build_graph(container)  # checkpointer en memoria
    return App(None, container, llm, graph), dataset.PROJECT_KEY, dataset.STORY_KEYS[1]  # type: ignore[arg-type]


def run(
    names: list[str], story_key: str | None, fakes: bool = False
) -> Iterator[tuple[str, dict[str, Any]]]:
    if fakes:
        app, project, key = compose_fakes()
        out_dir = Path(tempfile.mkdtemp(prefix="e2e-fakes-"))
    else:
        app = compose()
        project = app.config.settings.jira_project_key or ""
        key = story_key or seed_story_key(app, project)
        out_dir = OUT_DIR
    print(f"Proyecto {project} · HU {key} · modo {app.container.publish_mode}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        print(f"\n=== Escenario ({name})", flush=True)
        start = time.perf_counter()
        summary: dict[str, Any] = {}
        try:
            SCENARIOS[name](app, project, key, summary)
        except Exception as exc:  # se anota el fallo, se conserva lo medido y se sigue
            summary["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
            print(f"  ✗ {summary['error']}", flush=True)
        summary["scenario_seconds"] = round(time.perf_counter() - start, 1)
        print(f"  = {summary['scenario_seconds']} s", flush=True)
        path = out_dir / f"e2e-{name}.json"
        path.write_text(
            json.dumps(_jsonable(summary), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        yield name, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", choices=[*SCENARIOS, "all"])
    parser.add_argument("--story-key", help="HU del seed (por defecto, la [HU-02] del proyecto)")
    parser.add_argument(
        "--fakes", action="store_true", help="ensayo con los fakes (sin Jira, LLM ni BD)"
    )
    args = parser.parse_args()
    names = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    failed = [n for n, s in run(names, args.story_key, args.fakes) if "error" in s]
    if failed:
        raise SystemExit(f"Escenarios con error: {', '.join(failed)}")


if __name__ == "__main__":
    main()
