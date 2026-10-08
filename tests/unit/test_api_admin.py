"""API de Administración (T-29 mínima; RF-01, RF-40, RF-41): `api/admin.py`.

Patrón de `tests/unit/test_api_app.py`: la app real sobre los fakes, login con los usuarios demo
y cabecera `X-CSRF-Token`. `api.admin.build_tester` se sustituye por un `ConnectionTester` con
fakes: no se llama a Jira, PostgreSQL ni a ningún proveedor. Datos 100 % ficticios.
"""

from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.admin as admin
from adapters.base import TaskType, User
from adapters.llm.router import ModelChoice
from api.admin import TEST_INTERVAL_S, ConnectionTestLimiter
from api.runtime import Runtime, Workspace
from core.config import AppConfig, Settings, load_models_config
from core.health import ConnectionTester
from tests.fakes import dataset
from tests.fakes.api import fake_runtime
from tests.fakes.auth import FakeAuthProvider
from tests.fakes.container import fake_container
from tests.fakes.issue_tracker import FakeIssueTracker
from tests.fixtures import MODELS_FIXTURE
from tests.unit.test_api_app import ADMIN, AF, QA, Api

DEMO_USER = "usuario_demo"
DEMO_PASS = "clave_demo"
OLLAMA_URL = f"http://{DEMO_USER}:{DEMO_PASS}@ollama.example.invalid:11434/v1"
SECOND_ADMIN = ("admin-dos-demo", "clave-demo-admin-dos")
TEST_PATH = "/admin/connections/test"
MODELS_PATH = "/admin/models"


@dataclass
class FakeCatalog:
    models: dict[str, set[str]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    closed: int = 0

    def list_models(self, provider: str) -> set[str]:
        self.calls.append(provider)
        return set(self.models.get(provider, set()))

    def close(self) -> None:
        self.closed += 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def config(clean_env: pytest.MonkeyPatch) -> AppConfig:
    settings = Settings(
        _env_file=None,
        ollama_base_url=OLLAMA_URL,
        jira_base_url="https://sitio-ficticio.example.invalid",
    )
    return AppConfig(settings, load_models_config(MODELS_FIXTURE))


@pytest.fixture
def rt(tmp_path: Path, config: AppConfig) -> Runtime:
    users = dict(dataset.DEMO_USERS)
    users[SECOND_ADMIN[0]] = (SECOND_ADMIN[1], User(username=SECOND_ADMIN[0], role="admin"))
    base = fake_container(
        tmp_path, require_actor=True, publish_mode="simulation", auth=FakeAuthProvider(users)
    )
    return fake_runtime(tmp_path, container=replace(base, config=config))


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog(models={"local": {"bge-m3:latest"}})


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Reloj del limitador controlado por la prueba (sin tocar `time.monotonic` global)."""
    fake = Clock()
    monkeypatch.setattr(admin, "time", SimpleNamespace(monotonic=fake.monotonic))
    return fake


@pytest.fixture
def stub_tester(monkeypatch: pytest.MonkeyPatch, catalog: FakeCatalog) -> list[Workspace]:
    """Sustituye `build_tester` por un ConnectionTester con fakes; anota los workspaces."""
    built: list[Workspace] = []

    def build(ws: Workspace) -> tuple[ConnectionTester, FakeCatalog]:
        built.append(ws)
        config = ws.container.config
        assert config is not None
        tester = ConnectionTester(
            config,
            catalog,
            issue_tracker=FakeIssueTracker(),
            database_check=lambda: "Conexión correcta con db-ficticia:5432.",
            timeout_s=2.0,
        )
        return tester, catalog

    monkeypatch.setattr(admin, "build_tester", build)
    return built


def _login(rt: Runtime, who: tuple[str, str]) -> Api:
    a = Api(rt)
    assert a.login(who).status_code == 200
    return a


# --- Sesión, CSRF y permisos --------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [("post", TEST_PATH), ("get", MODELS_PATH)])
def test_admin_endpoints_return_401_when_no_session(rt: Runtime, method: str, path: str) -> None:
    """CA T-29 (solo admin): sin sesión → 401 unauthenticated."""
    a = Api(rt)
    response = a.post(path, csrf=False) if method == "post" else a.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


@pytest.mark.parametrize("who", [AF, QA], ids=["functional", "qa"])
@pytest.mark.parametrize(("method", "path"), [("post", TEST_PATH), ("get", MODELS_PATH)])
def test_admin_endpoints_return_403_when_role_is_not_admin(
    rt: Runtime, stub_tester: list[Workspace], who: tuple[str, str], method: str, path: str
) -> None:
    """CA T-29 (solo admin): functional y qa reciben 403 forbidden y no se prueba nada."""
    a = _login(rt, who)
    response = a.post(path) if method == "post" else a.get(path)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    assert stub_tester == []


def test_connection_test_returns_403_when_csrf_missing(
    rt: Runtime, stub_tester: list[Workspace]
) -> None:
    """CA T-29 (seguridad): POST sin X-CSRF-Token → 403 y no se ejecuta la prueba."""
    a = _login(rt, ADMIN)
    response = a.post(TEST_PATH, csrf=False)
    assert response.status_code == 403
    assert stub_tester == []


def test_connection_test_returns_403_when_csrf_wrong(
    rt: Runtime, stub_tester: list[Workspace]
) -> None:
    """CA T-29 (seguridad): un X-CSRF-Token incorrecto → 403."""
    a = _login(rt, ADMIN)
    a.csrf = "csrf-ficticio-incorrecto"
    assert a.post(TEST_PATH).status_code == 403
    assert stub_tester == []


# --- POST /admin/connections/test ---------------------------------------------------------------


def test_connection_test_returns_checks_when_admin(
    rt: Runtime, stub_tester: list[Workspace], catalog: FakeCatalog, clock: Clock
) -> None:
    """CA T-29 (RF-01, RF-40, RF-41): admin recibe un resultado por servicio; catálogo cerrado."""
    a = _login(rt, ADMIN)
    response = a.post(TEST_PATH)
    assert response.status_code == 200, response.text
    checks = {c["service"]: c for c in response.json()["checks"]}
    assert set(checks) == {
        "Jira",
        "PostgreSQL",
        "Modelos · groq",
        "Modelos · openrouter",
        "Modelos · local",
        "Embeddings",
    }
    assert checks["Jira"]["ok"] is True
    assert checks["PostgreSQL"]["ok"] is True
    assert checks["Modelos · groq"]["ok"] is False
    assert checks["Modelos · groq"]["detail"] == "Sin configurar."  # sin clave: no se llama
    assert checks["Embeddings"]["ok"] is True
    assert set(catalog.calls) == {"local"}
    assert catalog.closed == 1
    assert len(stub_tester) == 1
    assert all(set(c) == {"service", "ok", "detail", "duration_ms"} for c in checks.values())


def test_connection_test_writes_nothing_in_jira_when_admin_runs_it(
    rt: Runtime, stub_tester: list[Workspace], clock: Clock
) -> None:
    """CA T-29 (solo lectura): probar conexiones no escribe en Jira."""
    a = _login(rt, ADMIN)
    assert a.post(TEST_PATH).status_code == 200
    tracker = rt.workspace_factory().container.issue_tracker
    assert isinstance(tracker, FakeIssueTracker)
    assert tracker.writes == []


def test_connection_test_returns_429_when_repeated_within_interval(
    rt: Runtime, stub_tester: list[Workspace], clock: Clock
) -> None:
    """CA T-29: una segunda prueba antes de 10 s → 429 rate_limited con retry_after y cabecera."""
    a = _login(rt, ADMIN)
    assert a.post(TEST_PATH).status_code == 200
    clock.now += 3.2
    response = a.post(TEST_PATH)
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["retry_after"] == 7.0  # ceil(10 - 3.2)
    assert response.headers["Retry-After"] == "7"
    assert len(stub_tester) == 1  # la segunda no se ejecuta


def test_connection_test_allows_again_when_interval_elapsed(
    rt: Runtime, stub_tester: list[Workspace], clock: Clock
) -> None:
    """CA T-29 (límite): pasados 10 s se puede volver a probar."""
    a = _login(rt, ADMIN)
    assert a.post(TEST_PATH).status_code == 200
    clock.now += TEST_INTERVAL_S
    assert a.post(TEST_PATH).status_code == 200
    assert len(stub_tester) == 2


def test_connection_test_limits_per_person_when_two_admins(
    rt: Runtime, stub_tester: list[Workspace], clock: Clock
) -> None:
    """CA T-29: el límite es por persona; otra persona admin no se ve afectada."""
    first = _login(rt, ADMIN)
    second = _login(rt, SECOND_ADMIN)
    assert first.post(TEST_PATH).status_code == 200
    assert second.post(TEST_PATH).status_code == 200
    assert first.post(TEST_PATH).status_code == 429
    assert second.post(TEST_PATH).status_code == 429


def test_connection_test_returns_503_when_config_missing(tmp_path: Path, clock: Clock) -> None:
    """CA T-29: sin configuración (container.config es None) → 503, también al repetir."""
    rt = fake_runtime(tmp_path)  # el contenedor de fakes no tiene AppConfig
    a = _login(rt, ADMIN)
    response = a.post(TEST_PATH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    again = a.post(TEST_PATH)  # el 503 no gasta el turno del límite: sigue sin dar 429
    assert again.status_code == 503


# --- ConnectionTestLimiter ----------------------------------------------------------------------


def test_limiter_returns_wait_when_same_person_repeats(clock: Clock) -> None:
    """CA T-29: el limitador devuelve los segundos que faltan para la misma persona."""
    limiter = ConnectionTestLimiter()
    assert limiter.acquire("persona-a") is None
    clock.now += 4.0
    assert limiter.acquire("persona-a") == pytest.approx(6.0)
    assert limiter.acquire("persona-b") is None


def test_limiter_allows_again_when_interval_elapsed(clock: Clock) -> None:
    """CA T-29 (límite): justo a los 10 s vuelve a permitir y reinicia la cuenta."""
    limiter = ConnectionTestLimiter()
    assert limiter.acquire("persona-a") is None
    clock.now += TEST_INTERVAL_S - 0.001
    assert limiter.acquire("persona-a") is not None
    clock.now += 0.001
    assert limiter.acquire("persona-a") is None
    clock.now += 1.0
    assert limiter.acquire("persona-a") == pytest.approx(TEST_INTERVAL_S - 1.0)


def test_limiter_does_not_record_when_blocked(clock: Clock) -> None:
    """CA T-29: un intento bloqueado no alarga la espera."""
    limiter = ConnectionTestLimiter(interval_s=10.0)
    limiter.acquire("persona-a")
    clock.now += 5.0
    assert limiter.acquire("persona-a") == pytest.approx(5.0)
    clock.now += 5.0
    assert limiter.acquire("persona-a") is None


# --- GET /admin/models --------------------------------------------------------------------------


def test_models_returns_chains_with_host_only_when_admin(rt: Runtime, config: AppConfig) -> None:
    """CA T-29 (RF-40): cadenas por tarea y embeddings; de cada proveedor, solo el host."""
    a = _login(rt, ADMIN)
    response = a.get(MODELS_PATH)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {t["task"] for t in body["tasks"]} == {task.value for task in TaskType}
    story = next(t for t in body["tasks"] if t["task"] == "generate_story")
    assert story["chain"] == [
        {"provider": "groq", "model": "openai/gpt-oss-120b", "host": "api.groq.com"},
        {"provider": "openrouter", "model": "POR_DEFINIR:free", "host": "openrouter.ai"},
    ]
    assert story["override"] is None
    assert body["embeddings"] == {
        "provider": "local",
        "model": "bge-m3",
        "host": "ollama.example.invalid:11434",
    }
    text = response.text
    for leaked in (DEMO_USER, DEMO_PASS, "http://", "https://", "/v1", "/openai", "@"):
        assert leaked not in text


def test_models_includes_session_override_when_present(rt: Runtime) -> None:
    """CA T-29: si la sesión eligió otro modelo para una tarea, aparece como override."""
    a = _login(rt, ADMIN)
    a.session.workspace.overrides[TaskType.GENERATE_STORY] = ModelChoice(
        "ollama", "modelo-ficticio-b"
    )
    body = a.get(MODELS_PATH).json()
    story = next(t for t in body["tasks"] if t["task"] == "generate_story")
    assert story["override"] == {"provider": "ollama", "model": "modelo-ficticio-b"}
    others = [t for t in body["tasks"] if t["task"] != "generate_story"]
    assert all(t["override"] is None for t in others)


def test_models_override_is_per_session_when_other_admin_reads(rt: Runtime) -> None:
    """CA T-29: el override es de la sesión de quien consulta, no de otras."""
    first = _login(rt, ADMIN)
    first.session.workspace.overrides[TaskType.GENERATE_STORY] = ModelChoice(
        "ollama", "modelo-ficticio-b"
    )
    body = _login(rt, SECOND_ADMIN).get(MODELS_PATH).json()
    assert all(t["override"] is None for t in body["tasks"])


def test_models_returns_503_when_config_missing(tmp_path: Path) -> None:
    """CA T-29: sin configuración (container.config es None) → 503."""
    a = _login(fake_runtime(tmp_path), ADMIN)
    response = a.get(MODELS_PATH)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"


def test_host_returns_placeholder_when_provider_unknown(config: AppConfig) -> None:
    """CA T-29 (límite): un proveedor no declarado se muestra como «?»."""
    assert admin._host(config, "inexistente") == "?"
    assert admin._host(config, "local") == "ollama.example.invalid:11434"


def test_build_tester_composes_catalog_without_network_when_called(
    rt: Runtime, config: AppConfig
) -> None:
    """CA T-29: build_tester compone tester y catálogo con los proveedores usados (sin red)."""
    ws = rt.workspace_factory()
    tester, catalog = admin.build_tester(ws)
    try:
        assert isinstance(tester, ConnectionTester)
        assert set(catalog._base_urls) == {"groq", "openrouter", "local"}
        assert catalog._api_keys["groq"] is None  # sin clave en el entorno limpio
    finally:
        catalog.close()
