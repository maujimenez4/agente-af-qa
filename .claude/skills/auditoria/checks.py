"""Capa 1 de `/auditoria`: comprobaciones deterministas, sin IA, sobre el repositorio completo.

Uso:
    uv run python .claude/skills/auditoria/checks.py               # todo el repositorio
    uv run python .claude/skills/auditoria/checks.py core/rag web  # solo esas rutas
    uv run python .claude/skills/auditoria/checks.py --rule redos --json

Cada hallazgo sale como `GRAVEDAD  regla  archivo:línea  mensaje`, seguido de un recuento por
regla. Código de salida: 1 si hay algún hallazgo de gravedad alta; 0 en otro caso.

Cada regla declara su motivo (qué principio de CLAUDE.md o qué riesgo cubre) y sus excepciones
justificadas. Un caso concreto también se acepta con un comentario en la misma línea:
`# auditoria: ok <motivo>` (Python) o `// auditoria: ok <motivo>` (web); sin motivo no vale, y
nunca en las reglas de gravedad alta (esas excepciones solo van en las listas del script, que se
revisan en el diff).

Solo usa la biblioteca estándar: se puede ejecutar en la CI sin dependencias.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:  # Python 3.11+: el analizador de expresiones regulares de la biblioteca estándar
    import re._constants as sre_constants
    import re._parser as sre_parser
except ImportError:  # pragma: no cover - versiones antiguas
    import sre_constants  # type: ignore[no-redef]
    import sre_parse as sre_parser  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[3]

# Directorios que nunca se revisan: dependencias, artefactos y, sobre todo, `.claude/` (los
# worktrees de otras sesiones son copias completas del repositorio y duplicarían cada hallazgo).
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".claude",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "docs",
    }
)
WEB_SUFFIXES = (".ts", ".tsx", ".js", ".jsx")
OK_MARK = re.compile(r"(?:#|//)\s*auditoria:\s*ok\s+\S")

ALTA, MEDIA, BAJA = "alta", "media", "baja"
SEVERITY_ORDER = {ALTA: 0, MEDIA: 1, BAJA: 2}


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    reason: str
    exceptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    path: str
    line: int
    message: str


RULES: dict[str, Rule] = {
    r.id: r
    for r in (
        Rule(
            "jira-write",
            ALTA,
            "Principio 1 (aprobación humana): solo el nodo `publish` escribe en Jira.",
            (
                "adapters/**: es la implementación de la escritura.",
                "core/graph/nodes.py: `publish`, `_publish_approved` y `_publish_story` "
                "(auxiliar directo de `_publish_approved`).",
                "core/graph/execution.py: `publish` (nodo que registra la ejecución, T-47).",
                "tests/**: fakes y pruebas.",
            ),
        ),
        Rule(
            "core-concrete-import",
            ALTA,
            "Capas (CLAUDE.md, SPEC-00 §2): el núcleo solo depende de `adapters/base.py` y "
            "`adapters/errors.py`.",
            (
                "core/container.py y core/factories.py: puntos de composición.",
                "core/seed_users.py: CLI de composición citada en SPEC-00.",
            ),
        ),
        Rule(
            "inline-prompt",
            MEDIA,
            "Convención: los prompts viven en `prompts/<tarea>.md` con `version:`; nunca en el "
            "código.",
            (
                "Docstrings.",
                "tests/**, eval/** y prompts/**.",
            ),
        ),
        Rule(
            "log-sensitive-field",
            ALTA,
            "Principio 2 y convención de logs: nunca se registran prompts, mensajes, cabeceras "
            "`Authorization`, claves ni contraseñas.",
            (
                "Recuentos de consumo: `tokens`, `*_tokens`, `token_count`.",
                "tests/**: prueban precisamente que el enmascarado de los logs funciona.",
            ),
        ),
        Rule(
            "silent-except",
            MEDIA,
            "Errores silenciosos: un `except` genérico que no relanza ni registra esconde fallos.",
            (
                "Cuerpo con `raise` o con una llamada de log.",
                "Casos aceptados en EXCEPT_ALLOWED (archivo y función, con su motivo).",
                "tests/**.",
            ),
        ),
        Rule(
            "redos",
            MEDIA,
            "Retroceso exponencial (PA-230): cuantificadores anidados o alternancias solapadas "
            "bajo `*`/`+` en entradas de Jira o del modelo.",
            ("Cuantificadores acotados `{m,n}`.", "tests/**."),
        ),
        Rule(
            "env-read",
            ALTA,
            "Principio 2: la configuración se lee solo con `core/config.py` (pydantic-settings).",
            ("core/config.py.", "tests/**: fixtures con `monkeypatch`."),
        ),
        Rule(
            "web-dangerous-html",
            ALTA,
            "XSS: el frontend nunca inyecta HTML sin escapar.",
        ),
        Rule(
            "web-dynamic-url",
            MEDIA,
            "XSS con `javascript:`: toda URL dinámica en `href`/`src` pasa por `safeHref`.",
            (
                "Literales estáticos.",
                "Identificadores importados de un recurso (`import logo from './logo.svg'`).",
                "Pruebas (`*.test.*`).",
            ),
        ),
        Rule(
            "web-storage-secret",
            ALTA,
            "Robo de la sesión: tokens, CSRF o sesión nunca en `localStorage`/`sessionStorage`.",
            ("Pruebas (`*.test.*`).",),
        ),
        Rule(
            "web-eval",
            ALTA,
            "Inyección de código: ni `eval` ni `new Function`.",
            ("Pruebas (`*.test.*`).",),
        ),
    )
}

# --- Excepciones por archivo y función ----------------------------------------------------------

JIRA_WRITE_ALLOWED: dict[str, frozenset[str]] = {
    "core/graph/nodes.py": frozenset({"publish", "_publish_approved", "_publish_story"}),
    "core/graph/execution.py": frozenset({"publish"}),
}
CORE_COMPOSITION = frozenset({"core/container.py", "core/factories.py", "core/seed_users.py"})
# `except` genéricos aceptados: (archivo, función) → motivo.
EXCEPT_ALLOWED: dict[tuple[str, str], str] = {}

JIRA_WRITE_METHODS = frozenset(
    {"create_story", "update_story", "link", "publish_suite", "record_execution"}
)
LOG_METHODS = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "msg", "bind"}
)
SENSITIVE_FIELDS = (
    "prompt",
    "prompts",
    "messages",
    "authorization",
    "api_key",
    "apikey",
    "token",
    "password",
    "passwd",
    "secret",
    "cookie",
    "headers",
    "dsn",
    "database_url",
    "connection_string",
)
PROMPT_MARKERS = re.compile(
    r"^\s*(?:eres un|eres una|act[úu]a como|you are an?\b|act as\b)"
    r"|\bresponde (?:[úu]nicamente|solo|solamente) (?:con|en)\b"
    r"|\bdevuelve (?:[úu]nicamente|solo|solamente)\b"
    r"|\brespond only with\b|\breturn only\b",
    re.IGNORECASE,
)
MIN_PROMPT_CHARS = 60
ENV_KEY = re.compile(r"KEY|TOKEN|PASS|SECRET|DATABASE|POSTGRES|JIRA|_URL")
DOTENV_CALLS = frozenset({"load_dotenv", "dotenv_values", "find_dotenv"})


# --- Recorrido de archivos ----------------------------------------------------------------------


def iter_files(root: Path, targets: Iterable[str] = ()) -> Iterator[Path]:
    starts = [root / t for t in targets] or [root]
    for start in starts:
        if start.is_file():
            yield start
            continue
        for path in sorted(start.rglob("*")):
            rel = path.relative_to(root).parts
            if any(part in EXCLUDED_DIRS for part in rel[:-1]) or not path.is_file():
                continue
            if path.suffix == ".py" or path.suffix in WEB_SUFFIXES:
                yield path


def rel_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_test(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return (
        rel.startswith("tests/")
        or "/tests/" in rel
        or "/__tests__/" in rel
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


# --- Python -------------------------------------------------------------------------------------


@dataclass
class PyContext:
    rel: str
    lines: list[str]
    findings: list[Finding] = field(default_factory=list)

    def add(self, rule: str, node: ast.AST, message: str) -> None:
        line = getattr(node, "lineno", 1)
        text = self.lines[line - 1] if 0 < line <= len(self.lines) else ""
        if OK_MARK.search(text) and RULES[rule].severity != ALTA:
            return  # la marca no vale en las reglas altas: solo la lista revisada del script
        self.findings.append(Finding(rule, RULES[rule].severity, self.rel, line, message))


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _receiver(func: ast.expr) -> str:
    """Texto del objeto sobre el que se llama al método (`self.log` → `self.log`)."""
    if isinstance(func, ast.Attribute):
        try:
            return ast.unparse(func.value)
        except Exception:  # auditoria: ok ast.unparse no debería fallar; sin receptor
            return ""
    return ""


def _is_logger(func: ast.expr) -> bool:
    if not isinstance(func, ast.Attribute) or func.attr not in LOG_METHODS:
        return False
    receiver = _receiver(func).lower()
    tail = receiver.rsplit(".", 1)[-1]
    return "log" in tail or receiver in {"structlog", "logging"}


def _string_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant)]
    return []


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


class PyVisitor(ast.NodeVisitor):
    def __init__(self, ctx: PyContext, tree: ast.AST) -> None:
        self.ctx = ctx
        self.functions: list[str] = []
        self.docstrings = _docstring_nodes(tree)
        self.test = is_test(ctx.rel)

    # Función que contiene el nodo (la más interna).
    def _function(self) -> str:
        return self.functions[-1] if self.functions else "<módulo>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]  # noqa: N815

    # --- Importaciones (core-concrete-import) ---

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_core_import(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if node.level == 0 and module == "adapters":
            for alias in node.names:
                self._check_core_import(node, f"adapters.{alias.name}")
        elif node.level == 0:
            self._check_core_import(node, module)
        self.generic_visit(node)

    def _check_core_import(self, node: ast.AST, module: str) -> None:
        rel = self.ctx.rel
        if not rel.startswith("core/") or rel in CORE_COMPOSITION:
            return
        if not module.startswith("adapters."):
            return
        top = module.split(".")[1]
        if top in {"base", "errors"}:
            return
        self.ctx.add(
            "core-concrete-import",
            node,
            f"El núcleo importa la implementación concreta `{module}`.",
        )

    # --- Llamadas ---

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if not self.test:
            self._check_jira_write(node, name)
            self._check_env(node, name)
            self._check_redos(node, name)
        self._check_log(node)
        self._check_system_message(node)
        self.generic_visit(node)

    def _check_system_message(self, node: ast.Call) -> None:
        """`Message(role="system", content="…")` con el texto escrito en el código."""
        if self.test or self.ctx.rel.startswith(("eval/", "prompts/")):
            return
        kwargs = {k.arg: k.value for k in node.keywords if k.arg}
        role, content = kwargs.get("role"), kwargs.get("content")
        if (
            isinstance(role, ast.Constant)
            and role.value == "system"
            and content is not None
            and len("".join(_string_parts(content))) >= MIN_PROMPT_CHARS
        ):
            self.ctx.add("inline-prompt", node, "Mensaje `system` escrito en el código.")

    def _check_jira_write(self, node: ast.Call, name: str) -> None:
        rel = self.ctx.rel
        if rel.startswith("adapters/"):
            return
        allowed = JIRA_WRITE_ALLOWED.get(rel, frozenset())
        if self._function() in allowed:
            return
        if name in JIRA_WRITE_METHODS and isinstance(node.func, ast.Attribute):
            self.ctx.add(
                "jira-write",
                node,
                f"`{name}()` escribe en Jira fuera del nodo `publish` "
                f"(función `{self._function()}`).",
            )
            return
        method = name.lower()
        if method in {"post", "put", "patch", "delete", "request"}:
            args = [*node.args, *(k.value for k in node.keywords if k.arg in {"url", "path"})]
            if method == "request" and node.args:
                verb = _string_parts(node.args[0])
                if verb and verb[0].upper() in {"GET", "HEAD", "OPTIONS"}:
                    return  # lectura
            texts = [t for arg in args for t in _string_parts(arg)]
            if any("/rest/api/3/" in t for t in texts):
                self.ctx.add(
                    "jira-write",
                    node,
                    f"Petición `{name.upper()}` a la API de Jira fuera de los adaptadores.",
                )

    def _check_env(self, node: ast.Call, name: str) -> None:
        if self.ctx.rel == "core/config.py":
            return
        if name in DOTENV_CALLS:
            self.ctx.add("env-read", node, f"`{name}()` lee el `.env` fuera de `core/config.py`.")
            return
        if name == "open" or name == "Path":
            texts = [t for arg in node.args[:1] for t in _string_parts(arg)]
            if any(t.rstrip("/").endswith(".env") for t in texts):
                self.ctx.add("env-read", node, "Se abre el `.env` fuera de `core/config.py`.")
            return
        receiver = _receiver(node.func)
        is_getenv = name == "getenv" and receiver == "os"
        is_environ_get = name == "get" and receiver == "os.environ"
        if (is_getenv or is_environ_get) and node.args:
            texts = _string_parts(node.args[0])
            if texts and ENV_KEY.search(texts[0]):
                self.ctx.add(
                    "env-read",
                    node,
                    f"Lee `{texts[0]}` del entorno fuera de `core/config.py`.",
                )

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            not self.test
            and self.ctx.rel != "core/config.py"
            and isinstance(node.value, ast.Attribute)
            and _receiver(node.value) == "os"
            and node.value.attr == "environ"
        ):
            texts = _string_parts(node.slice)
            if texts and ENV_KEY.search(texts[0]):
                self.ctx.add(
                    "env-read",
                    node,
                    f"Lee `{texts[0]}` del entorno fuera de `core/config.py`.",
                )
        self.generic_visit(node)

    def _check_log(self, node: ast.Call) -> None:
        if self.test or not _is_logger(node.func):
            return
        for keyword in node.keywords:
            arg = (keyword.arg or "").lower()
            if not arg or arg == "tokens" or arg.endswith("_tokens") or arg == "token_count":
                continue
            for sensitive in SENSITIVE_FIELDS:
                if arg == sensitive or arg.endswith("_" + sensitive):
                    self.ctx.add(
                        "log-sensitive-field",
                        node,
                        f"El log registra el campo `{keyword.arg}`.",
                    )
                    break

    def _check_redos(self, node: ast.Call, name: str) -> None:
        receiver = _receiver(node.func)
        if receiver != "re" or name not in REGEX_FUNCS or not node.args:
            return
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            return
        problem = regex_risk(first.value)
        if problem:
            self.ctx.add("redos", node, problem)

    # --- Cadenas (inline-prompt) ---

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and id(node) not in self.docstrings:
            self._check_prompt(node, node.value)

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        text = "".join(_string_parts(node))
        self._check_prompt(node, text)
        # No se visitan las partes: la cadena ya se ha comprobado entera.

    def _check_prompt(self, node: ast.AST, text: str) -> None:
        rel = self.ctx.rel
        if self.test or rel.startswith(("eval/", "prompts/")):
            return
        if len(text) >= MIN_PROMPT_CHARS and PROMPT_MARKERS.search(text):
            self.ctx.add(
                "inline-prompt",
                node,
                "Texto con forma de instrucción al modelo escrito en el código.",
            )

    def visit_Dict(self, node: ast.Dict) -> None:
        keys = {
            k.value: v
            for k, v in zip(node.keys, node.values, strict=False)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        }
        role, content = keys.get("role"), keys.get("content")
        if (
            not self.test
            and isinstance(role, ast.Constant)
            and role.value == "system"
            and content is not None
            and len("".join(_string_parts(content))) >= MIN_PROMPT_CHARS
        ):
            self.ctx.add("inline-prompt", node, "Mensaje `system` escrito en el código.")
        self.generic_visit(node)

    # --- except (silent-except) ---

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if not self.test and _is_broad(node.type) and not _handles(node):
            key = (self.ctx.rel, self._function())
            if key not in EXCEPT_ALLOWED:
                kind = "except:" if node.type is None else f"except {ast.unparse(node.type)}"
                self.ctx.add(
                    "silent-except",
                    node,
                    f"`{kind}` no relanza ni registra (función `{self._function()}`).",
                )
        self.generic_visit(node)


def _is_broad(type_: ast.expr | None) -> bool:
    if type_ is None:
        return True
    names = type_.elts if isinstance(type_, ast.Tuple) else [type_]
    return any(isinstance(n, ast.Name) and n.id in {"Exception", "BaseException"} for n in names)


def _handles(handler: ast.ExceptHandler) -> bool:
    """Relanza, registra, avisa por stderr o usa la excepción capturada (la convierte en un
    resultado o un mensaje: `_fail(conv, exc)`). Solo así deja de ser silencioso."""
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
            if handler.name and isinstance(node, ast.Name) and node.id == handler.name:
                return True
            if isinstance(node, ast.Attribute) and node.attr == "stderr":
                return True
            if isinstance(node, ast.Call) and (
                _is_logger(node.func) or _call_name(node.func) in {"warn", "print_exc"}
            ):
                return True
    return False


def check_python(path: Path, rel: str) -> list[Finding]:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [Finding("parse-error", BAJA, rel, exc.lineno or 1, "No se pudo analizar.")]
    ctx = PyContext(rel, text.splitlines())
    PyVisitor(ctx, tree).visit(tree)
    return ctx.findings


# --- Expresiones regulares (redos) --------------------------------------------------------------

REGEX_FUNCS = frozenset(
    {"compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split"}
)
_REPEATS = (sre_constants.MAX_REPEAT, sre_constants.MIN_REPEAT)
_POSSESSIVE = getattr(sre_constants, "POSSESSIVE_REPEAT", None)
_ATOMIC = getattr(sre_constants, "ATOMIC_GROUP", None)
_UNBOUNDED = sre_constants.MAXREPEAT
_SAMPLE = [chr(c) for c in range(0, 256)] + ["á", "ñ", "€", "中", " "]


def regex_risk(pattern: str) -> str | None:
    """Motivo si el patrón tiene riesgo de retroceso exponencial; si no, `None`."""
    try:
        parsed = sre_parser.parse(pattern)
    except Exception:  # auditoria: ok patrón no válido: no es asunto de esta regla
        return None
    return _scan(list(parsed))


def _scan(items: list) -> str | None:
    for op, av in items:
        if op in _REPEATS:
            _low, high, sub = av
            sub_items = list(sub)
            if high == _UNBOUNDED or high > 1000:
                core = [it for it in sub_items if not _nullable(it)]
                if len(core) == 1 and _has_unbounded(core):
                    return "Cuantificadores anidados (p. ej. `(a+)+`): retroceso exponencial."
                if not core and _has_unbounded(sub_items):
                    return "Cuantificadores anidados sobre un grupo vacío posible (`(a*)*`)."
                branch = _single_branch(sub_items)
                if branch is not None and _branches_overlap(branch):
                    return "Alternancia con opciones solapadas bajo `*`/`+` (p. ej. `(a|a?)+`)."
            found = _scan(sub_items)
            if found:
                return found
        elif op == sre_constants.SUBPATTERN:
            found = _scan(list(av[-1]))
            if found:
                return found
        elif op == sre_constants.BRANCH:
            for alt in av[1]:
                found = _scan(list(alt))
                if found:
                    return found
        elif _ATOMIC is not None and op == _ATOMIC:
            continue  # grupo atómico: sin retroceso dentro
        elif _POSSESSIVE is not None and op == _POSSESSIVE:
            continue
    return None


def _has_unbounded(items: list) -> bool:
    for op, av in items:
        if op in _REPEATS and (av[1] == _UNBOUNDED or av[1] > 1000):
            return True
        if op == sre_constants.SUBPATTERN and _has_unbounded(list(av[-1])):
            return True
        if op == sre_constants.BRANCH and any(_has_unbounded(list(a)) for a in av[1]):
            return True
    return False


def _nullable(item: tuple) -> bool:
    op, av = item
    if op in _REPEATS:
        return av[0] == 0
    if op == sre_constants.SUBPATTERN:
        return all(_nullable(it) for it in av[-1])
    if op == sre_constants.BRANCH:
        return any(all(_nullable(it) for it in alt) for alt in av[1])
    return op in (sre_constants.AT,)


def _single_branch(items: list) -> list | None:
    """Las alternativas si el cuerpo del cuantificador es (solo) una alternancia."""
    core = items
    while len(core) == 1 and core[0][0] == sre_constants.SUBPATTERN:
        core = list(core[0][1][-1])
    if len(core) == 1 and core[0][0] == sre_constants.BRANCH:
        return [list(alt) for alt in core[0][1][1]]
    if len(core) == 1 and core[0][0] == sre_constants.IN:
        return None
    return None


def _branches_overlap(branches: list[list]) -> bool:
    firsts = [_first_chars(alt) for alt in branches]
    for i, a in enumerate(firsts):
        for b in firsts[i + 1 :]:
            if a & b:
                return True
    return False


def _first_chars(items: list) -> set[str]:
    chars: set[str] = set()
    for op, av in items:
        if op == sre_constants.LITERAL:
            chars.add(chr(av))
            return chars
        if op == sre_constants.NOT_LITERAL:
            chars |= {c for c in _SAMPLE if c != chr(av)}
            return chars
        if op == sre_constants.ANY:
            chars |= set(_SAMPLE)
            return chars
        if op == sre_constants.IN:
            chars |= {c for c in _SAMPLE if _in_matches(av, c)}
            return chars
        if op == sre_constants.SUBPATTERN:
            chars |= _first_chars(list(av[-1]))
            if not all(_nullable(it) for it in av[-1]):
                return chars
            continue
        if op == sre_constants.BRANCH:
            for alt in av[1]:
                chars |= _first_chars(list(alt))
            return chars
        if op in _REPEATS:
            chars |= _first_chars(list(av[2]))
            if av[0] > 0:
                return chars
            continue
        if op == sre_constants.AT:
            continue
        chars |= set(_SAMPLE)  # desconocido: se supone que puede solapar
        return chars
    return chars


def _in_matches(av: list, ch: str) -> bool:
    negate = False
    hit = False
    for op, val in av:
        if op == sre_constants.NEGATE:
            negate = True
        elif (
            (op == sre_constants.LITERAL and ch == chr(val))
            or (op == sre_constants.RANGE and val[0] <= ord(ch) <= val[1])
            or (op == sre_constants.CATEGORY and _category(val, ch))
        ):
            hit = True
    return hit != negate


def _category(cat: object, ch: str) -> bool:
    name = str(cat).upper()
    if "NOT_" in name:
        return not _category(name.replace("NOT_", ""), ch)
    if "DIGIT" in name:
        return ch.isdigit()
    if "SPACE" in name:
        return ch.isspace()
    if "WORD" in name:
        return ch.isalnum() or ch == "_"
    if "LINEBREAK" in name:
        return ch == "\n"
    return True


# --- Frontend (web/) ----------------------------------------------------------------------------

_DANGEROUS_HTML = re.compile(r"\bdangerouslySetInnerHTML\s*(?:=|:)")  # uso, no la mención
_URL_ATTR = re.compile(r"\b(href|src)=\{")
_STORAGE = re.compile(r"\b(localStorage|sessionStorage)\b")
_STORAGE_SECRET = re.compile(r"token|csrf|session(?!Storage)|auth|jwt|bearer", re.IGNORECASE)
_EVAL = re.compile(r"(?<![\w.$])eval\s*\(|\bnew\s+Function\s*\(")
_ASSET_IMPORT = re.compile(
    r"^\s*import\s+(\w+)\s+from\s+['\"][^'\"]+\.(?:svg|png|jpe?g|gif|webp|ico|avif)(?:\?\w+)?['\"]",
    re.MULTILINE,
)
_STATIC_EXPR = re.compile(r"""^\s*(?:'[^']*'|"[^"]*"|`[^`$]*`)\s*$""")


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _braced(text: str, start: int) -> str:
    """Expresión entre llaves que empieza en `start` (la posición de `{`)."""
    depth = 0
    for i in range(start, min(len(text), start + 2000)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return text[start + 1 : start + 2000]


def check_web(path: Path, rel: str) -> list[Finding]:
    if is_test(rel):
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    findings: list[Finding] = []

    def add(rule: str, index: int, message: str) -> None:
        line = _line_of(text, index)
        source = lines[line - 1] if line <= len(lines) else ""
        stripped = source.lstrip()
        marked = OK_MARK.search(source) and RULES[rule].severity != ALTA
        if marked or stripped.startswith(("//", "*", "/*")):
            return
        findings.append(Finding(rule, RULES[rule].severity, rel, line, message))

    for m in _DANGEROUS_HTML.finditer(text):
        add("web-dangerous-html", m.start(), "`dangerouslySetInnerHTML` inyecta HTML sin escapar.")
    assets = set(_ASSET_IMPORT.findall(text))
    for m in _URL_ATTR.finditer(text):
        expr = _braced(text, m.end() - 1).strip()
        if "safeHref(" in expr or _STATIC_EXPR.match(expr) or expr in assets:
            continue
        add("web-dynamic-url", m.start(), f"`{m.group(1)}` dinámico sin `safeHref`: `{expr[:60]}`.")
    for m in _STORAGE.finditer(text):
        line = _line_of(text, m.start())
        if _STORAGE_SECRET.search(lines[line - 1]):
            add("web-storage-secret", m.start(), f"`{m.group(1)}` con un token o la sesión.")
    for m in _EVAL.finditer(text):
        add("web-eval", m.start(), "`eval`/`new Function` ejecuta texto como código.")
    return findings


# --- Ejecución ----------------------------------------------------------------------------------


def run(root: Path = ROOT, targets: Iterable[str] = (), rules: Iterable[str] = ()) -> list[Finding]:
    selected = set(rules)
    findings: list[Finding] = []
    for path in iter_files(root, targets):
        rel = rel_path(path, root)
        checker: Callable[[Path, str], list[Finding]]
        if path.suffix == ".py":
            checker = check_python
        elif path.suffix in WEB_SUFFIXES and (rel.startswith("web/") or "/web/" in rel):
            checker = check_web
        else:
            continue
        findings.extend(checker(path, rel))
    if selected:
        findings = [f for f in findings if f.rule in selected]
    return sorted(
        findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.rule, f.path, f.line)
    )


def summary(findings: list[Finding], rules: Iterable[str] = ()) -> dict[str, int]:
    counts = Counter(f.rule for f in findings)
    ids = list(rules) or list(RULES)
    return {rule: counts.get(rule, 0) for rule in ids}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capa 1 de /auditoria (sin IA).")
    parser.add_argument("targets", nargs="*", help="Rutas relativas a la raíz (todo si se omite).")
    parser.add_argument("--rule", action="append", default=[], choices=sorted(RULES))
    parser.add_argument("--json", action="store_true", help="Salida en JSON.")
    parser.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    parser.add_argument("--rules", action="store_true", help="Lista las reglas con su motivo.")
    args = parser.parse_args(argv)

    if args.rules:
        for rule in RULES.values():
            print(f"{rule.id} ({rule.severity}): {rule.reason}")
            for exc in rule.exceptions:
                print(f"    excepción: {exc}")
        return 0

    findings = run(args.root.resolve(), args.targets, args.rule)
    counts = summary(findings, args.rule)
    if args.json:
        print(
            json.dumps(
                {"findings": [asdict(f) for f in findings], "summary": counts},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for f in findings:
            print(f"{f.severity.upper():5}  {f.rule:22}  {f.path}:{f.line}  {f.message}")
        print("\nRecuento por regla:")
        for rule, n in counts.items():
            print(f"  {rule:22} {n}")
        by_severity = Counter(f.severity for f in findings)
        print(
            f"Total: {len(findings)} (alta {by_severity[ALTA]}, media {by_severity[MEDIA]}, "
            f"baja {by_severity[BAJA]})"
        )
    return 1 if any(f.severity == ALTA for f in findings) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(main())
