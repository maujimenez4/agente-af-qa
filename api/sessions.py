"""Sesiones de la API en el servidor y límite de intentos de login (T-55, requisitos 1 y 4).

La cookie lleva solo un identificador aleatorio (256 bits); el usuario, el token anti-CSRF y el
espacio de trabajo viven aquí, en memoria del proceso (un solo proceso de uvicorn). Al reiniciar
la API hay que volver a iniciar sesión; las conversaciones siguen en el checkpointer.
"""

import hmac
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from adapters.base import User

Clock = Callable[[], float]
MAX_TRACKED_KEYS = 10_000


@dataclass
class ApiSession[W]:
    id: str
    csrf_token: str
    user: User
    workspace: W
    created_at: float
    last_seen: float
    streams: int = 0  # conexiones SSE abiertas


class SessionStore[W]:
    """Sesiones con caducidad por inactividad y absoluta; seguro entre hilos."""

    def __init__(self, idle_s: float, absolute_s: float, clock: Clock = time.monotonic) -> None:
        self._idle, self._absolute, self._clock = idle_s, absolute_s, clock
        self._sessions: dict[str, ApiSession[W]] = {}
        self._lock = threading.Lock()

    def create(self, user: User, workspace: W) -> ApiSession[W]:
        now = self._clock()
        session = ApiSession(
            id=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            user=user,
            workspace=workspace,
            created_at=now,
            last_seen=now,
        )
        with self._lock:
            self._purge(now)
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str | None, *, touch: bool = True) -> ApiSession[W] | None:
        if not session_id:
            return None
        now = self._clock()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._expired(session, now):
                del self._sessions[session_id]
                return None
            if touch:
                session.last_seen = now
            return session

    def alive(self, session: ApiSession[W]) -> bool:
        """La sesión sigue abierta (para cerrar los flujos SSE al caducar o al salir)."""
        with self._lock:
            current = self._sessions.get(session.id)
            return current is session and not self._expired(session, self._clock())

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def open_stream(self, session: ApiSession[W], limit: int) -> bool:
        """Reserva una conexión SSE; False si la persona ya tiene `limit` abiertas."""
        with self._lock:
            open_streams = sum(
                s.streams
                for s in self._sessions.values()
                if s.user.username == session.user.username
            )
            if open_streams >= limit:
                return False
            session.streams += 1
            return True

    def close_stream(self, session: ApiSession[W]) -> None:
        with self._lock:
            session.streams = max(0, session.streams - 1)

    def _expired(self, session: ApiSession[W], now: float) -> bool:
        return now - session.last_seen > self._idle or now - session.created_at > self._absolute

    def _purge(self, now: float) -> None:
        for sid in [sid for sid, s in self._sessions.items() if self._expired(s, now)]:
            del self._sessions[sid]


def csrf_matches[W](session: ApiSession[W], token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(session.csrf_token, str(token))


@dataclass
class _Attempts:
    failures: int = 0
    locked_until: float = 0.0


@dataclass
class LoginLimiter:
    """Tras `max_attempts` fallos seguidos por usuario o por IP, bloqueo de `lock_s` segundos.

    Cada bloqueo seguido dobla la espera (progresiva), hasta 8 veces `lock_s`.
    """

    max_attempts: int
    lock_s: float
    clock: Clock = time.monotonic
    _by_key: dict[str, _Attempts] = field(default_factory=dict)
    _strikes: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def retry_after(self, *keys: str) -> float | None:
        """Segundos de espera si alguna clave está bloqueada; None si se puede intentar."""
        now = self.clock()
        with self._lock:
            waits = [a.locked_until - now for k in keys if (a := self._by_key.get(k))]
        wait = max(waits, default=0.0)
        return round(wait, 1) if wait > 0 else None

    def failure(self, *keys: str) -> None:
        now = self.clock()
        with self._lock:
            if len(self._by_key) > MAX_TRACKED_KEYS:  # sin crecer sin tope con nombres al azar
                for old in [k for k, a in self._by_key.items() if a.locked_until <= now]:
                    del self._by_key[old]
                    self._strikes.pop(old, None)
            for key in keys:
                attempts = self._by_key.setdefault(key, _Attempts())
                attempts.failures += 1
                if attempts.failures >= self.max_attempts:
                    strikes = self._strikes.get(key, 0)
                    attempts.failures = 0
                    attempts.locked_until = now + self.lock_s * min(2**strikes, 8)
                    self._strikes[key] = strikes + 1

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._by_key.pop(key, None)
                self._strikes.pop(key, None)
