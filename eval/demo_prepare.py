"""Preparación de las conversaciones de la demo (T-36, parte 1).

Con el modelo local en CPU una HU tarda minutos, así que la demo abre conversaciones generadas de
antemano y solo hace en directo los pasos sin LLM (fuentes, recibo, aprobar, pasar a QA, registrar
la ejecución). Este script las genera sobre la **composición real de la API** (`api.runtime`,
mismas funciones de `api/service.py` que usa la UI), así que aparecen en la lista de `af-demo` y
`qa-demo` tal cual. Guion: `docs/demo/GUION.md`.

- **Simulación siempre:** fuerza `JIRA_PUBLISH_MODE=simulation` y se niega a seguir si la
  composición no lo está. Nada se escribe en Jira.
- **Sandbox en `live` (opcional):** `--sandbox-live --confirmo-escritura-AFQP` publica en el
  proyecto sandbox `AFQP` una HU (con su memoria) y sus casos, para los pasos de memoria y de
  registro de la ejecución. Solo con autorización expresa de la persona responsable.
- **Idempotente:** el manifiesto `preparadas.json` relaciona cada nombre con su id; si la
  conversación sigue existiendo, no se repite (`--rehacer NOMBRE` la vuelve a crear).
- **Resumen:** `preparadas.md` con nombre, usuario, id, estado, modelo y segundos. Nunca lleva
  contenido de las HU ni de los prompts.

Uso:
    uv run python -m eval.demo_prepare --fake                 # con los fakes, sin red ni LLM
                                                              # (sin --out, en una carpeta temporal)
    uv run python -m eval.demo_prepare --real [--story DEMO-3] [--qa-story DEMO-3]
    uv run python -m eval.demo_prepare --real --sandbox-live --confirmo-escritura-AFQP \\
        --project AFQP --story AFQP-1

No lo ejecutes contra el LLM real mientras otra sesión mida tiempos en la misma CPU.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from adapters.base import User
from adapters.errors import AgentError

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "demo"
MANIFEST = "preparadas.json"
SUMMARY = "preparadas.md"
SANDBOX_PROJECT = "AFQP"
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
PLAN_KEY_FIELDS = ("key", "epic", "from", "to", "story")
QUALITY_FILE = re.compile(r"^calidad-[A-Z][A-Z0-9_]+-\d+\.md$")
DEFAULT_PROJECT = "DEMO"
DEFAULT_STORY = "DEMO-3"  # «Renovar un préstamo» del seed (data/seed/jira, fila 3)

# Textos sintéticos del dominio ficticio de la Biblioteca Municipal de Villaficticia.
NEED_TEXT = (
    "Las personas socias quieren recibir un aviso cuando una reserva esté lista para recoger, "
    "con el plazo de recogida y el mostrador."
)
NEED_FEEDBACK = "Añade un criterio para cuando la reserva caduca sin que nadie la recoja."
EVOLVE_FEEDBACK = "Permite renovar también desde la aplicación móvil, con las mismas reglas."

Mode = Literal["simulation", "live"]
ExpectedState = Literal["in_review", "simulated", "published", "done"]


@dataclass
class Prepared:
    """Una conversación, ejecución o informe preparado (solo identificadores y metadatos)."""

    name: str
    kind: Literal["conversation", "execution", "quality"]
    user: str
    id: str | None = None
    state: str = "pending"
    expected: ExpectedState = "in_review"
    model: str | None = None
    seconds: float | None = None
    note: str = ""
    handoff_id: str | None = None


@dataclass
class Options:
    project: str = DEFAULT_PROJECT
    story: str = DEFAULT_STORY
    qa_story: str = DEFAULT_STORY
    execution_story: str | None = None
    functional_user: str = "af-demo"
    qa_user: str = "qa-demo"
    sandbox_live: bool = False
    redo: frozenset[str] = frozenset()
    only: frozenset[str] = frozenset()


@dataclass
class _Context:
    rt: Any
    options: Options
    out_dir: Path
    items: dict[str, Prepared] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    workspaces: dict[str, Any] = field(default_factory=dict)

    def user(self, role: str) -> User:
        return self.users[role]

    def ws(self, role: str) -> Any:
        if role not in self.workspaces:
            self.workspaces[role] = self.rt.workspace_factory()
        return self.workspaces[role]


class DemoPrepareError(AgentError):
    """La preparación no puede seguir (modo de publicación, proyecto o confirmación)."""


# --- Pasos -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    role: Literal["functional", "qa"]
    kind: Literal["conversation", "execution", "quality"]
    expected: ExpectedState
    run: Callable[[_Context, Prepared], None]
    needs: tuple[str, ...] = ()


def _need_iterated(ctx: _Context, item: Prepared) -> None:
    body = _body("need", "need", ctx.options.project, text=NEED_TEXT)
    thread = _start(ctx, "functional", body, item)
    _iterate(ctx, "functional", thread, NEED_FEEDBACK, item)


def _evolve_in_review(ctx: _Context, item: Prepared) -> None:
    _start(
        ctx, "functional", _body("evolve", "story", ctx.options.project, ctx.options.story), item
    )


def _evolve_approved(ctx: _Context, item: Prepared) -> None:
    body = _body("evolve", "story", ctx.options.project, ctx.options.story, [EVOLVE_FEEDBACK])
    thread = _start(ctx, "functional", body, item)
    _approve(ctx, "functional", thread, item)


def _chained_qa(source: str) -> Callable[[_Context, Prepared], None]:
    def run(ctx: _Context, item: Prepared) -> None:
        from api import service

        origin = ctx.items[source]
        af, qa = ctx.user("functional"), ctx.user("qa")
        handoff = service.pass_to_qa(ctx.rt, ctx.ws("functional"), af, origin.id)
        item.handoff_id = handoff.id
        run = service.take(ctx.rt, ctx.ws("qa"), qa, handoff.id)
        item.id = run.thread_id
        _settle(ctx, "qa", item)

    return run


def _chained_qa_published(source: str) -> Callable[[_Context, Prepared], None]:
    take = _chained_qa(source)

    def run(ctx: _Context, item: Prepared) -> None:
        take(ctx, item)
        if item.state == "in_review" and item.id:
            _approve(ctx, "qa", item.id, item)

    return run


def _direct_qa_in_review(ctx: _Context, item: Prepared) -> None:
    _start(ctx, "qa", _body("tests", "story", ctx.options.project, ctx.options.qa_story), item)


def _direct_qa_approved(ctx: _Context, item: Prepared) -> None:
    body = _body("tests", "story", ctx.options.project, ctx.options.qa_story)
    thread = _start(ctx, "qa", body, item)
    _approve(ctx, "qa", thread, item)


def _execution(ctx: _Context, item: Prepared) -> None:
    from api import executions

    key = ctx.options.execution_story or ctx.options.qa_story
    ws, qa = ctx.ws("qa"), ctx.user("qa")
    if not ws.container.test_management.list_cases(key):
        item.state = "skipped"
        item.note = f"{key} no tiene casos publicados en Jira (prepara antes el sandbox)."
        return
    item.id = executions.create(ctx.rt, ws, qa, key)
    item.state = executions.describe(ctx.rt, ws, qa, item.id).state


def _quality(ctx: _Context, item: Prepared) -> None:
    from core.quality import QualityReviewer

    key = ctx.options.story
    if not ISSUE_KEY.fullmatch(key):  # también es el nombre del archivo del informe
        raise DemoPrepareError(
            f"Clave de Jira no válida para la revisión de calidad: {key[:50]!r}."
        )
    review = QualityReviewer(ctx.ws("functional").container).review(ctx.user("functional"), key)
    item.id = f"calidad-{key}.md"
    item.model = f"{review.provider}/{review.model}"
    item.state = "done"
    item.note = "Plan B del paso de calidad: el informe se genera en directo al empezar."
    _write_text(ctx.out_dir / item.id, review.report.to_markdown(key))


SIMULATION_STEPS: tuple[Step, ...] = (
    Step("necesidad-iterada", "functional", "conversation", "in_review", _need_iterated),
    Step("evolucion-en-revision", "functional", "conversation", "in_review", _evolve_in_review),
    Step("evolucion-simulada", "functional", "conversation", "simulated", _evolve_approved),
    Step(
        "qa-encadenada-en-revision",
        "qa",
        "conversation",
        "in_review",
        _chained_qa("evolucion-simulada"),
        needs=("evolucion-simulada",),
    ),
    Step("qa-directa-en-revision", "qa", "conversation", "in_review", _direct_qa_in_review),
    Step("qa-directa-simulada", "qa", "conversation", "simulated", _direct_qa_approved),
    Step("ejecucion-en-revision", "qa", "execution", "in_review", _execution),
    Step("calidad", "functional", "quality", "done", _quality),
)

SANDBOX_STEPS: tuple[Step, ...] = (
    Step("sandbox-hu-publicada", "functional", "conversation", "published", _evolve_approved),
    Step(
        "sandbox-casos-publicados",
        "qa",
        "conversation",
        "published",
        _chained_qa_published("sandbox-hu-publicada"),
        needs=("sandbox-hu-publicada",),
    ),
)


# --- Operaciones sobre la API ------------------------------------------------------------------


def _body(
    flow: str,
    kind: str,
    project: str,
    key: str | None = None,
    feedback: list[str] | None = None,
    text: str | None = None,
) -> Any:
    from api.models import ConversationCreateIn

    origin = {"kind": kind, "project": project, "key": key, "text": text}
    return ConversationCreateIn.model_validate(
        {"flow": flow, "origin": origin, "feedback": feedback or []}
    )


def _start(ctx: _Context, role: str, body: Any, item: Prepared) -> str:
    from api import service

    run = service.create_conversation(ctx.rt, ctx.ws(role), ctx.user(role), body)
    item.id = run.thread_id
    _settle(ctx, role, item)
    return run.thread_id


def _iterate(ctx: _Context, role: str, thread_id: str, feedback: str, item: Prepared) -> None:
    from api import service

    if item.state != "in_review":
        return
    answer = service.iterate_answer(feedback)
    service.resume(ctx.rt, ctx.ws(role), ctx.user(role), thread_id, "iterate", answer)
    _settle(ctx, role, item)


def _approve(ctx: _Context, role: str, thread_id: str, item: Prepared) -> None:
    from api import service

    if item.state != "in_review":
        return
    out = service.conversation_out(ctx.rt, ctx.ws(role), ctx.user(role), thread_id)
    if ctx.ws(role).container.publish_mode == "live":
        _check_sandbox_plan(ctx, out.review.plan)
    answer = {"decision": "approve", "fingerprint": out.review.fingerprint}
    service.resume(ctx.rt, ctx.ws(role), ctx.user(role), thread_id, "approve", answer)
    _settle(ctx, role, item)


def _check_sandbox_plan(ctx: _Context, plan: list[dict[str, str]]) -> None:
    """En `live`, el recibo solo puede tocar el proyecto del sandbox (también los vínculos de
    impacto, que salen del contexto de Jira); si no, se para antes de aprobar."""
    project = ctx.options.project
    for operation in plan:
        # Falla cerrado: todo valor de un campo de clave tiene que ser una clave del proyecto.
        values = [operation.get(f) for f in PLAN_KEY_FIELDS if operation.get(f)]
        foreign = [
            v
            for v in values
            if v != "(HU nueva)" and not (ISSUE_KEY.fullmatch(v) and v.startswith(f"{project}-"))
        ]
        if operation.get("project", project) != project or foreign:
            raise DemoPrepareError(
                f"El recibo incluye operaciones fuera del proyecto {project}; no se aprueba. "
                "Revisa los vínculos de la HU en Jira."
            )


def _settle(ctx: _Context, role: str, item: Prepared) -> None:
    """Estado y modelo de la conversación tras la última operación (el `run` ya terminó)."""
    from api import service

    out = service.conversation_out(ctx.rt, ctx.ws(role), ctx.user(role), item.id)
    item.state = out.state
    artifact = out.review.artifact if out.review else _artifact(ctx, role, item.id)
    item.model = getattr(artifact, "model_used", None) or item.model
    if out.error is not None:
        item.note = out.error.message[:200]
    elif out.review is not None and out.review.error:
        item.note = out.review.error[:200]


def _artifact(ctx: _Context, role: str, thread_id: str | None) -> Any:
    config = {"configurable": {"thread_id": thread_id, "user": ctx.user(role).username}}
    return (ctx.ws(role).graph.get_state(config).values or {}).get("artifact")


def _still_exists(ctx: _Context, step: Step, item: Prepared) -> bool:
    """La pieza preparada sigue en el servidor (para no repetirla)."""
    if item.id is None or item.state in ("pending", "error", "failed", "skipped"):
        return False
    if step.kind == "quality":
        # El id sale del manifiesto: solo se acepta el nombre que escribe este script.
        return bool(QUALITY_FILE.fullmatch(item.id)) and (ctx.out_dir / item.id).exists()
    try:
        if step.kind == "execution":
            from api import executions

            item.state = executions.describe(ctx.rt, ctx.ws("qa"), ctx.user("qa"), item.id).state
        else:
            _settle(ctx, step.role, item)
    except AgentError:
        return False
    return True


# --- Orquestación ------------------------------------------------------------------------------


def prepare(rt: Any, options: Options, out_dir: Path, mode: Mode = "simulation") -> list[Prepared]:
    """Prepara los pasos del guion con la composición `rt` y escribe el manifiesto y el resumen."""
    rt.run_inline = True  # cada operación termina antes de seguir con la siguiente
    ctx = _Context(rt=rt, options=options, out_dir=out_dir)
    ctx.users = {
        "functional": User(username=options.functional_user, role="functional"),
        "qa": User(username=options.qa_user, role="qa"),
    }
    _check_mode(ctx, mode)
    if mode == "live":
        _check_live_options(options)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(out_dir)
    steps = SANDBOX_STEPS if mode == "live" else SIMULATION_STEPS
    names = {s.name for s in steps}
    if unknown := sorted((options.only | options.redo) - names):
        raise DemoPrepareError(f"Pasos desconocidos en modo «{mode}»: {', '.join(unknown)}.")
    for step in steps:
        if options.only and step.name not in options.only:
            if step.name in manifest:
                ctx.items[step.name] = manifest[step.name]
            continue
        saved = manifest.get(step.name)
        if saved is not None and step.name not in options.redo and _still_exists(ctx, step, saved):
            if not saved.note.startswith("ya preparada"):
                saved.note = f"ya preparada · {saved.note}" if saved.note else "ya preparada"
            ctx.items[step.name] = saved
            continue
        item = Prepared(
            name=step.name,
            kind=step.kind,
            user=ctx.user(step.role).username,
            expected=step.expected,
        )
        ctx.items[step.name] = item
        missing = [n for n in step.needs if _state_of(ctx, n) != _expected_of(steps, n)]
        if missing:
            item.state, item.note = "skipped", f"Falta preparar antes: {', '.join(missing)}."
            continue
        started = time.perf_counter()
        try:
            step.run(ctx, item)
        except AgentError as exc:
            item.state, item.note = "failed", str(exc)[:200]
        item.seconds = round(time.perf_counter() - started, 1)
    items = list(ctx.items.values())
    # Las entradas del otro modo (simulación o sandbox) se conservan en el mismo manifiesto.
    merged = {**manifest, **ctx.items}
    _save_manifest(out_dir, merged)
    _write_text(out_dir / SUMMARY, render_summary(list(merged.values()), mode))
    return items


def _state_of(ctx: _Context, name: str) -> str | None:
    item = ctx.items.get(name)
    return item.state if item else None


def _expected_of(steps: tuple[Step, ...], name: str) -> str:
    return next(s.expected for s in steps if s.name == name)


def _check_live_options(options: Options) -> None:
    """Defensa en profundidad: en `live`, sandbox confirmado y todas las claves de su proyecto.

    Que el proyecto sea `AFQP` lo exige `options_from` con `--real`; aquí no, para poder probar
    el flujo `live` con los fakes (proyecto `DEMO`).
    """
    keys = [options.story, options.qa_story, options.execution_story]
    outside = [k for k in keys if k and not k.startswith(f"{options.project}-")]
    if not options.sandbox_live or outside:
        raise DemoPrepareError(
            f"La preparación en `live` solo admite el sandbox confirmado y claves de "
            f"{options.project}."
        )


def _check_mode(ctx: _Context, mode: Mode) -> None:
    container = ctx.ws("functional").container
    if container.publish_mode != mode:
        raise DemoPrepareError(
            f"La composición está en modo «{container.publish_mode}» y esta preparación exige "
            f"«{mode}». Revisa JIRA_PUBLISH_MODE."
        )


def render_summary(items: list[Prepared], mode: Mode) -> str:
    """Tabla de `preparadas.md`: solo ids y metadatos (nada de contenido de las HU)."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Conversaciones preparadas para la demo",
        "",
        f"Generado por `eval/demo_prepare.py` el {now}, modo `{mode}`. Ver `docs/demo/GUION.md`.",
        "",
        "| Nombre | Usuario | Id | Estado | Esperado | Modelo | Segundos | Nota |",
        "|---|---|---|---|---|---|---:|---|",
    ]
    for i in items:
        ok = "✅" if i.state == i.expected else "⚠️"
        cells = [
            _cell(str(i.name)),
            _cell(str(i.user)),
            f"`{_cell(str(i.id))}`" if i.id else "—",
            f"{ok} {_cell(str(i.state))}",
            _cell(str(i.expected)),
            _cell(str(i.model)) if i.model else "—",
            f"{i.seconds:.1f}" if i.seconds is not None else "—",
            _cell(i.note) or "—",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|").replace("`", "'")


def _load_manifest(out_dir: Path) -> dict[str, Prepared]:
    path = out_dir / MANIFEST
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw["items"] if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            raise TypeError("items")
        items = {name: Prepared(**data) for name, data in entries.items()}
        if any(i.kind not in ("conversation", "execution", "quality") for i in items.values()):
            raise TypeError("kind")
        return items
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DemoPrepareError(
            f"El manifiesto {MANIFEST} está dañado; bórralo para preparar de nuevo."
        ) from None


def _save_manifest(out_dir: Path, items: dict[str, Prepared]) -> None:
    data = {"version": 1, "items": {name: asdict(item) for name, item in items.items()}}
    _write_text(out_dir / MANIFEST, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


# --- Línea de órdenes --------------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m eval.demo_prepare",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--fake", action="store_true", help="con los fakes, sin red ni LLM")
    target.add_argument("--real", action="store_true", help="composición real (.env, Ollama)")
    parser.add_argument("--out", type=Path, help="carpeta del manifiesto y el resumen")
    parser.add_argument("--project", default=None)
    parser.add_argument("--story", default=None, help=f"HU que se evoluciona ({DEFAULT_STORY})")
    parser.add_argument("--qa-story", default=None, help="HU con clave para la QA directa")
    parser.add_argument("--execution-story", default=None, help="HU con casos publicados (T-47)")
    parser.add_argument("--functional-user", default="af-demo")
    parser.add_argument("--qa-user", default="qa-demo")
    parser.add_argument("--only", action="append", default=[], metavar="NOMBRE")
    parser.add_argument("--rehacer", action="append", default=[], metavar="NOMBRE")
    parser.add_argument(
        "--sandbox-live",
        action="store_true",
        help=f"publica de verdad en el sandbox {SANDBOX_PROJECT}",
    )
    parser.add_argument(
        f"--confirmo-escritura-{SANDBOX_PROJECT}",
        dest="confirm_live",
        action="store_true",
        help="confirmación expresa para --sandbox-live",
    )
    return parser.parse_args(argv)


def options_from(args: argparse.Namespace) -> Options:
    project = args.project or (SANDBOX_PROJECT if args.sandbox_live else DEFAULT_PROJECT)
    story = args.story or DEFAULT_STORY
    if args.sandbox_live:
        if not args.confirm_live:
            raise DemoPrepareError(
                f"--sandbox-live escribe en Jira: añade --confirmo-escritura-{SANDBOX_PROJECT} "
                "solo con autorización expresa."
            )
        if args.real:
            # El proyecto de una evolución sale de la clave de la HU: todas tienen que ser del
            # sandbox, y la HU se indica siempre a mano (nunca la de por defecto).
            keys = [args.story, args.qa_story, args.execution_story]
            outside = [k for k in keys if k and not k.startswith(f"{SANDBOX_PROJECT}-")]
            if project != SANDBOX_PROJECT or not args.story or outside:
                raise DemoPrepareError(
                    f"--sandbox-live solo publica en el proyecto {SANDBOX_PROJECT}: indica "
                    f"--story {SANDBOX_PROJECT}-<n> y ninguna clave de otro proyecto."
                )
    return Options(
        project=project,
        story=story,
        qa_story=args.qa_story or story,
        execution_story=args.execution_story,
        functional_user=args.functional_user,
        qa_user=args.qa_user,
        sandbox_live=args.sandbox_live,
        redo=frozenset(args.rehacer),
        only=frozenset(args.only),
    )


def build(args: argparse.Namespace, mode: Mode) -> tuple[Any, Path]:
    """Composición de la preparación: fakes o la real, con el modo de publicación forzado."""
    if args.fake:
        from tests.fakes.api import fake_runtime

        workdir = Path(tempfile.mkdtemp(prefix="demo-prepare-"))
        return fake_runtime(workdir, publish_mode=mode), args.out or workdir / "demo"
    from api.runtime import build_runtime

    os.environ["JIRA_PUBLISH_MODE"] = mode  # prioridad sobre .env (pydantic-settings)
    return build_runtime(), args.out or DEFAULT_OUT


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    args = parse_args(argv)
    try:
        options = options_from(args)
        mode: Mode = "live" if options.sandbox_live else "simulation"
        rt, out_dir = build(args, mode)
        items = prepare(rt, options, out_dir, mode)
    except AgentError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(render_summary(items, mode))
    sys.stdout.write(f"\nManifiesto y resumen en {out_dir}\n")
    return 0 if all(i.state in (i.expected, "skipped") for i in items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
