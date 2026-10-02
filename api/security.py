"""Sesión, CSRF, origen, tamaño del cuerpo y cabeceras (T-55, `docs/api/requisitos-parte-2.md`).

Las dependencias leen la cookie y las cabeceras de `Request` (no como parámetros de FastAPI) para
que el contrato OpenAPI siga declarando la seguridad con sus `securitySchemes`.
"""

import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.errors import ApiError
from api.runtime import Runtime, Workspace
from api.sessions import ApiSession, csrf_matches
from core.config import ConfigError
from core.logging import get_logger

log = get_logger("api.security")

COOKIE = "afqa_session"
COOKIE_PATH = "/api"
CSRF_HEADER = "x-csrf-token"
UNAUTHENTICATED = ApiError(401, "unauthenticated", "Inicia sesión para continuar.")
FORBIDDEN = ApiError(403, "forbidden", "No tienes permiso para realizar esta acción.")
BAD_ORIGIN = ApiError(403, "forbidden", "La petición no viene de un origen permitido.")
UNAVAILABLE = (
    "No se pudo arrancar el servicio: revisa la configuración y que PostgreSQL esté en marcha."
)
INVALID_CONFIG = "La configuración no es válida: revisa los valores del `.env`."
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

Session = ApiSession[Workspace]


# --- Composición perezosa -------------------------------------------------------------------


class RuntimeHolder:
    """Compone la API la primera vez que hace falta; un fallo no se guarda (se reintenta)."""

    def __init__(self, factory: Callable[[], Runtime], runtime: Runtime | None = None) -> None:
        self._factory, self._runtime = factory, runtime
        self._lock = threading.Lock()

    def get(self) -> Runtime:
        if self._runtime is not None:
            return self._runtime
        with self._lock:
            if self._runtime is None:
                try:
                    self._runtime = self._factory()
                except ConfigError as exc:
                    raise ApiError(503, "service_unavailable", str(exc)) from None
                except ValidationError:  # incluiría el valor recibido del `.env`
                    raise ApiError(503, "service_unavailable", INVALID_CONFIG) from None
                except Exception as exc:
                    log.warning("no se pudo componer la API", error_type=type(exc).__name__)
                    raise ApiError(503, "service_unavailable", UNAVAILABLE) from None
            return self._runtime

    @property
    def ready(self) -> Runtime | None:
        return self._runtime


def runtime(request: Request) -> Runtime:
    holder: RuntimeHolder = request.app.state.runtime
    return holder.get()


# --- Origen, sesión y CSRF ------------------------------------------------------------------


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def check_origin(request: Request, allowed: list[str]) -> None:
    """`Origin` (o `Referer`) del mismo origen o de la lista permitida; sin cabecera, se acepta.

    Los navegadores envían `Origin` en toda petición entre sitios que modifica algo; un cliente
    que no es navegador no lleva la cookie de otra persona, y el token CSRF sigue siendo
    obligatorio.
    """
    raw = request.headers.get("origin") or request.headers.get("referer")
    if not raw:
        return
    origin = _origin_of(raw)
    host = request.headers.get("host", "")
    same = f"{request.url.scheme}://{host}".lower()
    if origin is None or (origin != same and origin not in {o.lower() for o in allowed}):
        raise BAD_ORIGIN


def current_session(request: Request) -> Session:
    rt = runtime(request)
    session = rt.sessions.get(request.cookies.get(COOKIE))
    if session is None:
        raise UNAUTHENTICATED
    request.state.user = session.user.username
    return session


def session_for(request: Request) -> Session:
    """Sesión de la persona; en POST, PUT y DELETE además origen y token anti-CSRF."""
    session = current_session(request)
    if request.method in UNSAFE_METHODS:
        check_origin(request, runtime(request).settings.api_origins)
        if not csrf_matches(session, request.headers.get(CSRF_HEADER)):
            raise FORBIDDEN
    return session


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "desconocida"


# --- Middleware -----------------------------------------------------------------------------

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
_SECURITY_HEADERS_RAW = [(k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]


class BodyLimitMiddleware:
    """413 con la forma común si el cuerpo pasa de `max_bytes` (con o sin `Content-Length`)."""

    def __init__(self, app: ASGIApp, max_bytes: int, on_too_large: ASGIApp) -> None:
        self.app, self.max_bytes, self.on_too_large = app, max_bytes, on_too_large

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length")
        if length is not None and (not length.isdigit() or int(length) > self.max_bytes):
            await self.on_too_large(scope, receive, send)
            return
        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI convierte cualquier otra excepción al leer el cuerpo en un 400; una
                    # HTTPException la deja pasar y su manejador responde con la forma común.
                    raise HTTPException(413)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except StarletteHTTPException as exc:
            if exc.status_code != 413 or started:
                raise
            await self.on_too_large(scope, receive, send)


class CatchAllMiddleware:
    """500 genérico para lo que no maneja nadie, sin la traza ni `str(exc)` en el log.

    Sustituye al manejador de `Exception` de Starlette, que responde y además vuelve a lanzar la
    excepción (uvicorn registraría la traza, con el texto del error).
    """

    def __init__(self, app: ASGIApp, on_error: ASGIApp) -> None:
        self.app, self.on_error = app, on_error

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            log.error("error inesperado", action="request", error_type=type(exc).__name__)
            if not started:
                await self.on_error(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                existing = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in _SECURITY_HEADERS_RAW if k not in existing]
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, with_headers)


class RequestLogMiddleware:
    """Registro propio en lugar del access log: ruta de la plantilla, sin query ni cabeceras.

    ASGI puro (no `BaseHTTPMiddleware`, que agrupa las excepciones de la lectura del cuerpo y
    retiene las respuestas en streaming del SSE).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def tracking_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        finally:
            state = scope.get("state") or {}
            log.info(
                "petición",
                action=f"{scope.get('method')} {getattr(scope.get('route'), 'path', 'sin ruta')}",
                user=state.get("user"),
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
