"""PA-455: el límite de login no bloquea a todos detrás del proxy de confianza.

Con el proxy de Vite (o el de Docker) todas las peticiones llegan con la IP del proxy: contar esa
IP hacía que cinco fallos de cualquiera bloquearan a todos. Ahora, detrás de un proxy de confianza
cuenta solo el usuario (no se lee `X-Forwarded-For`: el proxy de Vite la reenvía tal como la manda
el navegador); al entrar bien, la IP solo pierde los fallos de esa cuenta (PA-470). Las IP son
de los rangos de documentación (RFC 5737 y 3849); los usuarios, ficticios.
"""

from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from api.__main__ import server_options
from api.app import API_PREFIX, create_app
from api.runtime import Runtime
from api.security import login_ip
from core.config import Settings
from tests.fakes import dataset
from tests.fakes.api import api_settings, fake_runtime
from tests.unit.test_api_sessions import Clock

AF = ("af-demo", dataset.DEMO_USERS["af-demo"][0])
QA = ("qa-demo", dataset.DEMO_USERS["qa-demo"][0])
WRONG = "contrasena-incorrecta-ficticia"
VITE = ("127.0.0.1", 50000)  # el proxy de Vite en la misma máquina
DIRECT = ("203.0.113.7", 50000)  # un cliente que llega sin proxy
REAL_A, REAL_B = "198.51.100.10", "198.51.100.20"


def _client(rt: Runtime, peer: tuple[str, int] = VITE) -> TestClient:
    return TestClient(create_app(runtime_instance=rt), base_url="https://testserver", client=peer)


def _login(client: TestClient, who: tuple[str, str], forwarded: str | None = None) -> Any:
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    return client.post(
        f"{API_PREFIX}/auth/login",
        json={"username": who[0], "password": who[1]},
        headers=headers,
    )


def _fail(client: TestClient, times: int, forwarded: str | None = None, prefix: str = "x") -> None:
    for n in range(times):
        response = _login(client, (f"persona-ficticia-{prefix}{n}", WRONG), forwarded)
        assert response.status_code == 401


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "client": (peer, 1), "headers": headers})


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    return fake_runtime(tmp_path)


# --- Detrás del proxy de Vite --------------------------------------------------------------


def test_failures_of_others_behind_the_proxy_do_not_block_everyone(rt: Runtime) -> None:
    """PA-455: detrás del proxy, los fallos de unas personas no bloquean el login de otra."""
    client = _client(rt)
    _fail(client, rt.settings.api_login_max_attempts * 2)

    assert _login(client, QA).status_code == 200


def test_user_lockout_still_applies_behind_the_proxy(rt: Runtime) -> None:
    """PA-455 (negativo): el límite por usuario sigue: sus fallos lo bloquean aunque no cuente
    la IP del proxy."""
    client = _client(rt)
    for _ in range(rt.settings.api_login_max_attempts):
        assert _login(client, ("af-demo", WRONG)).status_code == 401

    response = _login(client, AF)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


def test_forwarded_header_behind_the_proxy_is_not_trusted(rt: Runtime) -> None:
    """PA-455 (negativo): detrás del proxy de Vite, `X-Forwarded-For` la pone quien llama: no
    sirve para repartir fallos entre IP inventadas ni para bloquear la IP de otra persona."""
    client = _client(rt)
    for n in range(rt.settings.api_login_max_attempts):
        _fail(client, 1, forwarded=REAL_A, prefix=str(n))

    assert _login(client, QA, forwarded=REAL_A).status_code == 200  # REAL_A no se bloqueó
    direct = _client(rt, (REAL_A, 1))
    assert _login(direct, AF).status_code == 200


def test_forwarded_header_from_untrusted_client_is_ignored(rt: Runtime) -> None:
    """PA-455 (negativo): un cliente directo no puede escaparse del límite por IP inventando
    `X-Forwarded-For`: cuenta su IP de conexión."""
    client = _client(rt, DIRECT)
    for n in range(rt.settings.api_login_max_attempts):
        _fail(client, 1, forwarded=f"198.51.100.{n + 1}", prefix=str(n))

    response = _login(client, QA, forwarded="198.51.100.99")

    assert response.status_code == 429


def test_direct_client_ip_lockout_is_kept(rt: Runtime) -> None:
    """Req. 4 · PA-455: sin proxy, el límite por IP se mantiene (cambiar de usuario no sirve)."""
    client = _client(rt, DIRECT)
    _fail(client, rt.settings.api_login_max_attempts)

    assert _login(client, QA).status_code == 429


def test_own_mistakes_are_forgiven_on_the_ip_after_signing_in(rt: Runtime) -> None:
    """PA-455 · PA-470: quien se equivoca con su contraseña y luego acierta no deja cargada la IP
    (antes solo se limpiaba el usuario y esos fallos seguían sumando para la IP)."""
    client = _client(rt, DIRECT)
    attempts = rt.settings.api_login_max_attempts
    for _ in range(attempts - 1):
        assert _login(client, ("af-demo", WRONG)).status_code == 401
    assert _login(client, AF).status_code == 200

    _fail(client, attempts - 1)  # sin perdonar los suyos, aquí ya serían más del máximo

    assert _login(client, QA).status_code == 200


def test_interleaved_good_logins_do_not_cancel_the_ip_limit(rt: Runtime) -> None:
    """PA-470 (negativo): entrar con una cuenta propia entre fallos contra otras cuentas no anula
    el límite por IP: los fallos contra otras cuentas siguen sumando."""
    client = _client(rt, DIRECT)
    attempts = rt.settings.api_login_max_attempts
    _fail(client, attempts - 1, prefix="a")
    assert _login(client, AF).status_code == 200

    assert _login(client, ("persona-ficticia-b0", WRONG)).status_code == 401  # el 5.º: bloquea

    assert _login(client, QA).status_code == 429


def test_interleaved_good_logins_keep_the_progressive_wait(tmp_path: Path) -> None:
    """PA-470: tras un bloqueo, una entrada buena no borra la espera progresiva de la IP: el
    siguiente bloqueo dura el doble."""
    clock = Clock()
    rt = fake_runtime(tmp_path)
    rt.limiter.clock = clock
    client = _client(rt, DIRECT)
    attempts, lock_s = rt.settings.api_login_max_attempts, rt.settings.api_login_lock_seconds
    _fail(client, attempts, prefix="a")
    assert _login(client, QA).json()["error"]["retry_after"] == lock_s
    clock.now += lock_s

    assert _login(client, AF).status_code == 200
    _fail(client, attempts, prefix="b")

    assert _login(client, QA).json()["error"]["retry_after"] == lock_s * 2


# --- PA-469: uvicorn no reescribe la IP del cliente ---------------------------------------------


def _limiter_keys(rt: Runtime) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []
    original = rt.limiter.failure

    def record(*keys: str) -> None:
        seen.append(keys)
        original(*keys)

    rt.limiter.failure = record  # type: ignore[method-assign]
    return seen


def _through_uvicorn(rt: Runtime, proxy_headers: bool) -> list[tuple[str, ...]]:
    """Un login fallido desde 127.0.0.1 (el proxy de Vite) con `X-Forwarded-For` inventada,
    pasando por la aplicación tal como la carga uvicorn con esas opciones."""
    options = dict(server_options("127.0.0.1", 8000))
    options["proxy_headers"] = proxy_headers
    config = uvicorn.Config(create_app(runtime_instance=rt), **options)  # type: ignore[arg-type]
    config.load()
    seen = _limiter_keys(rt)

    async def call() -> int:
        transport = httpx.ASGITransport(config.loaded_app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
            response = await http.post(
                f"{API_PREFIX}/auth/login",
                json={"username": "persona-ficticia", "password": WRONG},
                headers={"X-Forwarded-For": REAL_A},
            )
            return response.status_code

    assert anyio.run(call) == 401
    return seen


def test_uvicorn_options_disable_proxy_headers() -> None:
    """PA-469: la API arranca uvicorn sin `proxy_headers` (también el contenedor, que usa
    `python -m api`)."""
    assert server_options("127.0.0.1", 8000)["proxy_headers"] is False


def test_forwarded_header_from_vite_does_not_change_the_limiter_ip(rt: Runtime) -> None:
    """PA-469: una petición con `X-Forwarded-For` desde 127.0.0.1 no cambia la IP que ve el
    limitador: con las opciones de la API, la IP inventada no aparece (solo cuenta el usuario)."""
    api_option = server_options("127.0.0.1", 8000)["proxy_headers"]
    seen = _through_uvicorn(rt, proxy_headers=bool(api_option))

    assert seen == [("user:persona-ficticia",)]


def test_with_uvicorn_proxy_headers_the_ip_would_be_spoofed(rt: Runtime) -> None:
    """PA-469 (control): con `proxy_headers` de uvicorn, la IP inventada llegaría al limitador;
    es lo que evita la opción de `api/__main__.py`."""
    seen = _through_uvicorn(rt, proxy_headers=True)

    assert seen == [("user:persona-ficticia", f"ip:{REAL_A}")]


def test_proxies_come_from_settings(tmp_path: Path) -> None:
    """PA-455: la lista se configura; sin el proxy en ella, su IP vuelve a contar."""
    rt = fake_runtime(tmp_path, settings=api_settings(api_trusted_proxies="192.0.2.1"))
    client = _client(rt)  # 127.0.0.1 ya no es de confianza
    _fail(client, rt.settings.api_login_max_attempts)

    assert _login(client, QA).status_code == 429


# --- login_ip y la configuración ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.7", None, "203.0.113.7"),  # cliente directo
        ("203.0.113.7", REAL_A, "203.0.113.7"),  # cabecera de quien no es proxy: se ignora
        ("127.0.0.1", None, None),  # proxy de Vite: solo cuenta el usuario
        ("127.0.0.1", REAL_A, None),  # su cabecera no se cree (la pone quien llama)
        ("::1", "2001:db8::5", None),
        ("testclient", None, "testclient"),  # no es una IP: no es un proxy de confianza
    ],
)
def test_login_ip(peer: str, forwarded: str | None, expected: str | None) -> None:
    """PA-455: qué IP cuenta en el límite de login según quién conecta; la cabecera, nunca."""
    proxies = api_settings().api_proxies

    assert login_ip(_request(peer, forwarded), proxies) == expected


def test_trusted_proxies_default_and_networks() -> None:
    """PA-455: por defecto, el proxy de Vite (127.0.0.1 y ::1); admite redes (Docker)."""
    assert [str(n) for n in api_settings().api_proxies] == ["127.0.0.1/32", "::1/128"]
    custom = api_settings(api_trusted_proxies="172.18.0.0/16, 127.0.0.1")
    assert [str(n) for n in custom.api_proxies] == ["172.18.0.0/16", "127.0.0.1/32"]
    assert login_ip(_request("172.18.0.5", REAL_B), custom.api_proxies) is None
    assert login_ip(_request("172.19.0.5"), custom.api_proxies) == "172.19.0.5"


@pytest.mark.parametrize("value", ["*", "cualquiera", "127.0.0.1,proxy-ficticio", "10.0.0.0/99"])
def test_invalid_trusted_proxies_are_rejected(value: str) -> None:
    """PA-455 (negativo): un valor mal escrito no arranca (no debe confiar en cualquiera)."""
    with pytest.raises(ValidationError, match="API_TRUSTED_PROXIES"):
        Settings(_env_file=None, api_trusted_proxies=value)  # type: ignore[call-arg]


def test_trusted_proxies_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """PA-455: se lee de `API_TRUSTED_PROXIES`."""
    monkeypatch.setenv("API_TRUSTED_PROXIES", "192.0.2.10")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert [str(n) for n in settings.api_proxies] == ["192.0.2.10/32"]
