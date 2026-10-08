"""Preparación de las conversaciones de la demo (T-36, parte 1).

Con la configuración mixta de modelos (PA-443) la HU, la evolución y la revisión de calidad salen
con Groq en segundos, pero la suite de QA, con el modelo local, tarda 6–8 minutos. La demo abre
esas piezas generadas de antemano (guion: `web/DEMO.md`, variante B, y `docs/demo/HU-AFQP.md`).
Este script las genera sobre la **composición real de la API** (`api.runtime`, las mismas
funciones de `api/service.py` y el mismo almacén de revisiones de calidad que usa la web), así que
aparecen en la lista de `af-demo` y `qa-demo` tal cual.

Qué prepara (por defecto, en el proyecto sintético `AFQP`, Biblioteca de Villaficticia):
- `qa-suite-en-revision` (`qa-demo`): una suite de QA **en revisión** de `AFQP-28`. Se niega si
  la HU ya tiene casos publicados en Jira (PA-450: nunca una segunda suite de `AFQP-27`).
- `evolucion-iterada` (`af-demo`): respaldo de la evolución de `AFQP-3` iterada una vez.
- `calidad` (`af-demo`): respaldo de la revisión de calidad de `AFQP-3`, terminada («Informe
  listo» en la lista).

- **Simulación siempre:** fuerza `JIRA_PUBLISH_MODE=simulation` y se niega a seguir si la
  composición no lo está. Nada se escribe en Jira.
- **Sandbox en `live` (opcional, desactivado):** `--sandbox-live --confirmo-escritura-AFQP`
  publica de verdad en `AFQP` la evolución de `--story` y los casos de `--qa-story` (las dos hay
  que indicarlas a mano). Solo con autorización expresa de la persona responsable: la bandera
  equivale a aprobar **sin ver el contenido** (como `af-demo` y `qa-demo`), con el recibo
  limitado a `AFQP` y PA-450 comprobado otra vez justo antes de aprobar la suite.
- **Idempotente:** el manifiesto `preparadas.json` relaciona cada nombre con su id; si la pieza
  sigue existiendo, no se repite (`--rehacer NOMBRE` la vuelve a crear; la anterior sigue
  abierta en la lista: descártala en la web para no aprobar dos suites de la misma HU). Una
  pieza que se aprobó o descartó en un ensayo sale con ⚠️: rehazla con `--rehacer`.
- **Resumen:** `preparadas.md` con nombre, usuario, id, estado, modelo y segundos. Nunca lleva
  contenido de las HU ni de los prompts.

Uso:
    uv run python -m eval.demo_prepare --fake                 # con los fakes, sin red ni LLM
                                                              # (proyecto DEMO de los fakes y,
                                                              # sin --out, carpeta temporal)
    uv run python -m eval.demo_prepare --real                 # AFQP-28 (QA) y AFQP-3 (AF)
    uv run python -m eval.demo_prepare --real --only qa-suite-en-revision --qa-story AFQP-28
    uv run python -m eval.demo_prepare --real --rehacer evolucion-iterada
    uv run python -m eval.demo_prepare --real --sandbox-live --confirmo-escritura-AFQP \\
        --story AFQP-<n> --qa-story AFQP-<m>

Con `--real` usa el `.env` y `config/models.yaml` de la API (Groq y Ollama encendidos, PostgreSQL
con las migraciones). Al componer, la API marca como interrumpidas las revisiones de calidad en
marcha: no lo lances mientras alguien revisa la calidad en la web. No lo ejecutes contra el LLM
real mientras otra sesión mida tiempos en la misma CPU.
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
from uuid import uuid4

from adapters.base import User
from adapters.errors import AgentError
from api.errors import ApiError

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "docs" / "demo"
MANIFEST = "preparadas.json"
SUMMARY = "preparadas.md"
SANDBOX_PROJECT = "AFQP"
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
PLAN_KEY_FIELDS = ("key", "epic", "from", "to", "story")

# Demo real (variante B de `web/DEMO.md`): proyecto sintético AFQP.
DEFAULT_PROJECT = "AFQP"
DEFAULT_STORY = "AFQP-3"  # HU-02 «Renovar un préstamo» sembrada en AFQP (HU-AFQP.md, §4)
DEFAULT_QA_STORY = "AFQP-28"  # sin casos publicados; AFQP-27 ya tiene AFQP-29…34 (PA-450)
# Con `--fake`: el proyecto del conjunto de datos sintético de los fakes.
FAKE_PROJECT = "DEMO"
FAKE_STORY = "DEMO-3"

# Textos sintéticos del dominio ficticio de la Biblioteca Municipal de Villaficticia.
EVOLVE_FEEDBACK = (
    "Añade que un préstamo no se puede renovar si otra persona socia tiene ese libro reservado. "
    "En ese caso se muestra el mensaje «No se puede renovar: este libro está reservado por otra "
    "persona» y se indica la fecha de devolución."
)
ITERATE_FEEDBACK = "Añade un criterio para cuando la persona intenta renovar con el carné caducado."

Mode = Literal["simulation", "live"]
Kind = Literal["conversation", "quality"]
ExpectedState = Literal["in_review", "published", "done"]
KINDS = ("conversation", "quality")


@dataclass
class Prepared:
    """Una conversación o revisión de calidad preparada (solo identificadores y metadatos)."""

    name: str
    kind: Kind
    user: str
    id: str | None = None
    state: str = "pending"
    expected: ExpectedState = "in_review"
    model: str | None = None
    seconds: float | None = None
    note: str = ""


@dataclass
class Options:
    project: str = DEFAULT_PROJECT
    story: str = DEFAULT_STORY
    qa_story: str = DEFAULT_QA_STORY
    quality_story: str = DEFAULT_STORY
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
    """La preparación no puede seguir (modo de publicación, proyecto, HU o confirmación)."""


# --- Pasos -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    role: Literal["functional", "qa"]
    kind: Kind
    expected: ExpectedState
    run: Callable[[_Context, Prepared], None]


def _qa_in_review(ctx: _Context, item: Prepared) -> None:
    key = ctx.options.qa_story
    _check_without_cases(ctx, key)
    _start(ctx, "qa", _body("tests", "story", ctx.options.project, key), item)


def _qa_published(ctx: _Context, item: Prepared) -> None:
    _qa_in_review(ctx, item)
    if item.id:
        _approve(ctx, "qa", item.id, item)


def _evolve_iterated(ctx: _Context, item: Prepared) -> None:
    body = _body("evolve", "story", ctx.options.project, ctx.options.story, [EVOLVE_FEEDBACK])
    thread = _start(ctx, "functional", body, item)
    _iterate(ctx, "functional", thread, ITERATE_FEEDBACK, item)


def _evolve_published(ctx: _Context, item: Prepared) -> None:
    body = _body("evolve", "story", ctx.options.project, ctx.options.story, [EVOLVE_FEEDBACK])
    thread = _start(ctx, "functional", body, item)
    _approve(ctx, "functional", thread, item)


def _quality(ctx: _Context, item: Prepared) -> None:
    """Como `POST /quality-reviews` de la API: se guarda en el almacén y sale en la lista.

    Sin traza de Langfuse (`traced_operation`): es una preparación, no una petición de la web.
    """
    from api.errors import to_api_error
    from core.permissions import require
    from core.projects import normalize_issue_key
    from core.quality import REVIEW_PERMISSION, QualityReviewer, new_review

    try:
        key = normalize_issue_key(ctx.options.quality_story)
    except ValueError:
        raise DemoPrepareError(
            f"Clave de Jira no válida para la revisión de calidad: "
            f"{ctx.options.quality_story[:50]!r}."
        ) from None
    user = ctx.user("functional")
    require(user, REVIEW_PERMISSION)
    review = new_review(str(uuid4()), user.username, key)
    ctx.rt.quality.create(review)
    item.id = review.id
    try:
        result = QualityReviewer(ctx.ws("functional").container).review(user, key)
    except Exception as exc:  # como la API: el mensaje de lista blanca queda en la revisión
        error = to_api_error(exc).body
        ctx.rt.quality.fail(review.id, error.code, error.message, error.retry_after)
        item.state, item.note = "failed", error.message[:200]
        return
    ctx.rt.quality.finish(review.id, result)
    item.model = f"{result.provider}/{result.model}"
    item.state = "done"


SIMULATION_STEPS: tuple[Step, ...] = (
    Step("qa-suite-en-revision", "qa", "conversation", "in_review", _qa_in_review),
    Step("evolucion-iterada", "functional", "conversation", "in_review", _evolve_iterated),
    Step("calidad", "functional", "quality", "done", _quality),
)

SANDBOX_STEPS: tuple[Step, ...] = (
    Step("sandbox-hu-publicada", "functional", "conversation", "published", _evolve_published),
    Step("sandbox-casos-publicados", "qa", "conversation", "published", _qa_published),
)


# --- Operaciones sobre la API ------------------------------------------------------------------


def _check_without_cases(ctx: _Context, key: str) -> None:
    """PA-450: nunca una segunda suite de una HU que ya tiene casos (falla cerrado)."""
    from api import service

    count = service.count_test_cases(ctx.ws("qa"), key)
    if count is None:
        raise DemoPrepareError(
            f"No se pudo comprobar si {key} tiene casos publicados en Jira; no se prepara su suite."
        )
    if count:
        raise DemoPrepareError(
            f"{key} ya tiene {count} casos publicados en Jira (PA-450): elige con --qa-story "
            "una HU sin casos."
        )


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
    """Solo en el sandbox `live`, con la confirmación expresa de la CLI."""
    from api import service

    if item.state != "in_review":
        return
    out = service.conversation_out(ctx.rt, ctx.ws(role), ctx.user(role), thread_id)
    if ctx.ws(role).container.publish_mode == "live":
        _check_sandbox_plan(ctx, out.review.plan)
        if role == "qa":  # PA-450 otra vez: la suite tarda minutos y Jira puede haber cambiado
            _check_without_cases(ctx, ctx.options.qa_story)
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
    """Estado, modelo y avisos de la conversación tras la última operación (ya terminada)."""
    from api import service

    out = service.conversation_out(ctx.rt, ctx.ws(role), ctx.user(role), item.id)
    item.state = out.state
    artifact = out.review.artifact if out.review else _artifact(ctx, role, item.id)
    item.model = getattr(artifact, "model_used", None) or item.model
    if out.error is not None:
        item.note = out.error.message[:200]
    elif out.review is not None and out.review.error:
        item.note = out.review.error[:200]
    elif out.review is not None and out.review.uncovered is not None:
        # PA-426 y PA-326: solo los IDs (nunca el texto de los CA ni de las RN).
        criteria, rules = out.review.uncovered.criteria, out.review.uncovered.rules
        if not criteria and not rules:
            item.note = "Cobertura completa"
        else:
            item.note = f"Sin caso: {len(criteria)} CA, {len(rules)} RN" + (
                f" ({', '.join(criteria)[:100]})" if criteria else ""
            )


def _artifact(ctx: _Context, role: str, thread_id: str | None) -> Any:
    config = {"configurable": {"thread_id": thread_id, "user": ctx.user(role).username}}
    return (ctx.ws(role).graph.get_state(config).values or {}).get("artifact")


def _still_exists(ctx: _Context, step: Step, item: Prepared) -> bool:
    """La pieza preparada sigue en el servidor (para no repetirla)."""
    if item.id is None or item.state in ("pending", "error", "failed", "skipped"):
        return False
    if step.kind == "quality":
        try:
            review = ctx.rt.quality.get(item.id)
        except (AgentError, ValueError):  # un id manipulado en el manifiesto no es un uuid
            return False
        if review is None or review.username != ctx.user(step.role).username:
            return False
        item.state = review.state
        return review.state == "done"
    try:
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
        started = time.perf_counter()
        try:
            step.run(ctx, item)
        except (AgentError, ApiError) as exc:  # `api.service` lanza `ApiError` (409, 503…)
            item.state, item.note = "failed", str(exc)[:200]
        except BaseException:
            # Lo inesperado se propaga, pero lo ya preparado (o publicado en el sandbox) queda
            # en el manifiesto para no repetirlo.
            item.state, item.note = "failed", "Error inesperado; revisa la salida."
            _save(out_dir, manifest, ctx, mode)
            raise
        item.seconds = round(time.perf_counter() - started, 1)
    _save(out_dir, manifest, ctx, mode)
    return list(ctx.items.values())


def _save(out_dir: Path, manifest: dict[str, Prepared], ctx: _Context, mode: Mode) -> None:
    # Las entradas del otro modo (simulación o sandbox) se conservan en el mismo manifiesto.
    merged = {**manifest, **ctx.items}
    _save_manifest(out_dir, merged)
    _write_text(out_dir / SUMMARY, render_summary(list(merged.values()), mode))


def _check_live_options(options: Options) -> None:
    """Defensa en profundidad: en `live`, sandbox confirmado y todas las claves de su proyecto.

    Que el proyecto sea `AFQP` lo exige `options_from` con `--real`; aquí no, para poder probar
    el flujo `live` con los fakes (proyecto `DEMO`).
    """
    keys = [options.story, options.qa_story, options.quality_story]
    outside = [k for k in keys if not k.startswith(f"{options.project}-")]
    if not options.sandbox_live or outside:
        raise DemoPrepareError(
            f"La preparación en `live` solo admite el sandbox confirmado y claves de "
            f"{options.project}."
        )


def _check_mode(ctx: _Context, mode: Mode) -> None:
    for role in ("functional", "qa"):
        container = ctx.ws(role).container
        if container.publish_mode != mode:
            raise DemoPrepareError(
                f"La composición está en modo «{container.publish_mode}» y esta preparación "
                f"exige «{mode}». Revisa JIRA_PUBLISH_MODE."
            )


def render_summary(items: list[Prepared], mode: Mode) -> str:
    """Tabla de `preparadas.md`: solo ids y metadatos (nada de contenido de las HU)."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Conversaciones preparadas para la demo",
        "",
        f"Generado por `eval/demo_prepare.py` el {now}, modo `{mode}`. Guion: `web/DEMO.md` "
        "(variante B) y `docs/demo/HU-AFQP.md`.",
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
    """Las entradas de la versión anterior (pasos que ya no existen) se descartan."""
    path = out_dir / MANIFEST
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = raw["items"] if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            raise TypeError("items")
        known = {s.name for s in SIMULATION_STEPS + SANDBOX_STEPS}
        items = {
            name: Prepared(**{k: v for k, v in data.items() if k != "handoff_id"})
            for name, data in entries.items()
            if name in known
        }
        if any(i.kind not in KINDS for i in items.values()):
            raise TypeError("kind")
        return items
    except (ValueError, TypeError, KeyError, AttributeError):
        raise DemoPrepareError(
            f"El manifiesto {MANIFEST} está dañado; bórralo para preparar de nuevo."
        ) from None


def _save_manifest(out_dir: Path, items: dict[str, Prepared]) -> None:
    data = {"version": 2, "items": {name: asdict(item) for name, item in items.items()}}
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
    target.add_argument("--real", action="store_true", help="composición real de la API (.env)")
    parser.add_argument("--out", type=Path, help="carpeta del manifiesto y el resumen")
    parser.add_argument("--project", default=None, help=f"proyecto ({DEFAULT_PROJECT})")
    parser.add_argument("--story", default=None, help=f"HU que se evoluciona ({DEFAULT_STORY})")
    parser.add_argument(
        "--qa-story",
        default=None,
        help=f"HU sin casos publicados para la suite ({DEFAULT_QA_STORY})",
    )
    parser.add_argument(
        "--quality-story", default=None, help="HU de la revisión de calidad (la de --story)"
    )
    parser.add_argument("--functional-user", default="af-demo")
    parser.add_argument("--qa-user", default="qa-demo")
    parser.add_argument("--only", action="append", default=[], metavar="NOMBRE")
    parser.add_argument("--rehacer", action="append", default=[], metavar="NOMBRE")
    parser.add_argument(
        "--sandbox-live",
        action="store_true",
        help=f"publica de verdad en el sandbox {SANDBOX_PROJECT} (desactivado por defecto)",
    )
    parser.add_argument(
        f"--confirmo-escritura-{SANDBOX_PROJECT}",
        dest="confirm_live",
        action="store_true",
        help="confirmación expresa para --sandbox-live",
    )
    return parser.parse_args(argv)


def options_from(args: argparse.Namespace) -> Options:
    fake = bool(args.fake)
    project = args.project or (FAKE_PROJECT if fake else DEFAULT_PROJECT)
    story = args.story or (FAKE_STORY if fake else DEFAULT_STORY)
    qa_story = args.qa_story or (FAKE_STORY if fake else DEFAULT_QA_STORY)
    if args.sandbox_live:
        if not args.confirm_live:
            raise DemoPrepareError(
                f"--sandbox-live escribe en Jira: añade --confirmo-escritura-{SANDBOX_PROJECT} "
                "solo con autorización expresa."
            )
        if args.real:
            # El proyecto de una evolución sale de la clave de la HU: todas tienen que ser del
            # sandbox, y las HU se indican siempre a mano (nunca las de por defecto de la demo).
            keys = [args.story, args.qa_story, args.quality_story]
            outside = [k for k in keys if k and not k.startswith(f"{SANDBOX_PROJECT}-")]
            if project != SANDBOX_PROJECT or not args.story or not args.qa_story or outside:
                raise DemoPrepareError(
                    f"--sandbox-live solo publica en el proyecto {SANDBOX_PROJECT}: indica "
                    f"--story y --qa-story {SANDBOX_PROJECT}-<n> y ninguna clave de otro proyecto."
                )
    return Options(
        project=project,
        story=story,
        qa_story=qa_story,
        quality_story=args.quality_story or story,
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
    except (AgentError, ApiError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(render_summary(items, mode))
    sys.stdout.write(f"\nManifiesto y resumen en {out_dir}\n")
    return 0 if all(i.state == i.expected for i in items) else 1


if __name__ == "__main__":
    raise SystemExit(main())
