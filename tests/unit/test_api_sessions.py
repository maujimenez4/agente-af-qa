"""Sesiones en el servidor, límite de intentos de login y CSRF (T-55, requisitos 1, 2 y 4).

Reloj inyectado: las caducidades se prueban sin esperar. Usuarios 100 % ficticios.
"""

import pytest

from adapters.base import User
from api.sessions import ApiSession, LoginLimiter, SessionStore, csrf_matches

AF = User(username="af-demo", role="functional")
QA = User(username="qa-demo", role="qa")
IDLE_S, ABSOLUTE_S = 60.0, 600.0
FAKE_CSRF = "token-csrf-ficticio"  # valor sintético de prueba


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> SessionStore[str]:
    return SessionStore(idle_s=IDLE_S, absolute_s=ABSOLUTE_S, clock=clock)


# --- SessionStore ----------------------------------------------------------------------------


def test_create_returns_random_ids_of_at_least_128_bits(store: SessionStore[str]) -> None:
    """Req. 1: identificador aleatorio (>= 128 bits) y token CSRF distinto por sesión."""
    first, second = store.create(AF, "ws-1"), store.create(AF, "ws-2")
    assert first.id != second.id and first.csrf_token != second.csrf_token
    assert first.id != first.csrf_token
    # token_urlsafe(32): 32 bytes = 256 bits -> 43 caracteres base64url.
    assert len(first.id) >= 22 and len(first.csrf_token) >= 22
    assert store.get(first.id) is first and first.workspace == "ws-1"


def test_get_unknown_or_empty_id_returns_none(store: SessionStore[str]) -> None:
    """Req. 1: una cookie inventada o vacía no abre ninguna sesión."""
    assert store.get(None) is None
    assert store.get("") is None
    assert store.get("identificador-inventado") is None


def test_session_expires_after_idle_time(store: SessionStore[str], clock: Clock) -> None:
    """Req. 1: caduca por inactividad."""
    session = store.create(AF, "ws")
    clock.advance(IDLE_S + 1)
    assert store.get(session.id) is None
    assert store.get(session.id) is None  # ya borrada


def test_session_survives_exactly_at_idle_limit(store: SessionStore[str], clock: Clock) -> None:
    """Req. 1 (límite): justo en el umbral de inactividad sigue viva."""
    session = store.create(AF, "ws")
    clock.advance(IDLE_S)
    assert store.get(session.id) is session


def test_activity_extends_idle_but_not_absolute_limit(
    store: SessionStore[str], clock: Clock
) -> None:
    """Req. 1: la actividad renueva la inactividad, pero la caducidad absoluta se mantiene."""
    session = store.create(AF, "ws")
    elapsed = 0.0
    while elapsed + IDLE_S / 2 <= ABSOLUTE_S:
        clock.advance(IDLE_S / 2)
        elapsed += IDLE_S / 2
        assert store.get(session.id) is session
    clock.advance(IDLE_S / 2)
    assert store.get(session.id) is None


def test_get_without_touch_does_not_extend_idle(store: SessionStore[str], clock: Clock) -> None:
    """Req. 1: `touch=False` consulta sin renovar la actividad."""
    session = store.create(AF, "ws")
    clock.advance(IDLE_S - 1)
    assert store.get(session.id, touch=False) is session
    clock.advance(2)
    assert store.get(session.id) is None


def test_alive_false_after_drop_or_expiry(store: SessionStore[str], clock: Clock) -> None:
    """Req. 6: el flujo SSE se cierra si la sesión se cierra o caduca."""
    dropped, expiring = store.create(AF, "ws"), store.create(QA, "ws")
    assert store.alive(dropped) and store.alive(expiring)
    store.drop(dropped.id)
    assert not store.alive(dropped)
    clock.advance(IDLE_S + 1)
    assert not store.alive(expiring)


def test_drop_unknown_id_is_harmless(store: SessionStore[str]) -> None:
    """Req. 1: cerrar una sesión inexistente no falla."""
    store.drop("identificador-inventado")


def test_create_purges_expired_sessions(store: SessionStore[str], clock: Clock) -> None:
    """Req. 1: las sesiones caducadas no se acumulan en memoria."""
    old = store.create(AF, "ws")
    clock.advance(ABSOLUTE_S + 1)
    store.create(QA, "ws")
    assert old.id not in store._sessions


def test_open_stream_limit_counts_all_sessions_of_the_person(store: SessionStore[str]) -> None:
    """Req. 6: el límite de flujos SSE es por persona, sumando todas sus sesiones."""
    first, second, other = store.create(AF, "a"), store.create(AF, "b"), store.create(QA, "c")
    assert store.open_stream(first, 2)
    assert store.open_stream(second, 2)
    assert not store.open_stream(first, 2)
    assert not store.open_stream(second, 2)
    assert store.open_stream(other, 2)  # otra persona no comparte el cupo
    store.close_stream(first)
    assert store.open_stream(second, 2)


def test_close_stream_never_goes_negative(store: SessionStore[str]) -> None:
    """Req. 6: cerrar de más no deja el contador por debajo de cero."""
    session = store.create(AF, "ws")
    store.close_stream(session)
    assert session.streams == 0


# --- csrf_matches ----------------------------------------------------------------------------


def _session(token: str = FAKE_CSRF) -> ApiSession[str]:
    return ApiSession(
        id="sesion-ficticia",
        csrf_token=token,
        user=AF,
        workspace="ws",
        created_at=0.0,
        last_seen=0.0,
    )


def test_csrf_matches_only_the_session_token() -> None:
    """Req. 2: el token anti-CSRF está ligado a la sesión."""
    session = _session()
    assert csrf_matches(session, "token-csrf-ficticio")
    assert not csrf_matches(session, "token-csrf-ficticio-otro")
    assert not csrf_matches(session, "TOKEN-CSRF-FICTICIO")


@pytest.mark.parametrize("token", [None, ""])
def test_csrf_rejects_missing_token(token: str | None) -> None:
    """Req. 2: sin token, rechazado."""
    assert not csrf_matches(_session(), token)


def test_csrf_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Req. 2: la comparación usa `hmac.compare_digest`."""
    calls: list[tuple[str, str]] = []

    def spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return a == b

    monkeypatch.setattr("api.sessions.hmac.compare_digest", spy)
    assert csrf_matches(_session(), "token-csrf-ficticio")
    assert calls == [("token-csrf-ficticio", "token-csrf-ficticio")]


# --- LoginLimiter ----------------------------------------------------------------------------


def _limiter(clock: Clock, attempts: int = 3, lock_s: float = 10.0) -> LoginLimiter:
    return LoginLimiter(max_attempts=attempts, lock_s=lock_s, clock=clock)


def test_limiter_allows_until_max_attempts(clock: Clock) -> None:
    """Req. 4: por debajo del máximo no hay bloqueo."""
    limiter = _limiter(clock)
    for _ in range(2):
        limiter.failure("user:af-demo")
    assert limiter.retry_after("user:af-demo") is None


def test_limiter_locks_at_max_attempts_and_releases_after_lock(clock: Clock) -> None:
    """Req. 4: al llegar al máximo, bloqueo durante `lock_s`; después se libera."""
    limiter = _limiter(clock)
    for _ in range(3):
        limiter.failure("user:af-demo")
    assert limiter.retry_after("user:af-demo") == 10.0
    clock.advance(4)
    assert limiter.retry_after("user:af-demo") == 6.0
    clock.advance(6)
    assert limiter.retry_after("user:af-demo") is None


def test_limiter_any_locked_key_blocks(clock: Clock) -> None:
    """Req. 4: el bloqueo por IP se aplica aunque cambie el usuario."""
    limiter = _limiter(clock)
    for n in range(3):
        limiter.failure(f"user:ficticio-{n}", "ip:192.0.2.10")
    assert limiter.retry_after("user:ficticio-0") is None
    assert limiter.retry_after("user:otro-ficticio", "ip:192.0.2.10") == 10.0
    assert limiter.retry_after("user:otro-ficticio", "ip:192.0.2.99") is None


def test_limiter_wait_is_progressive_and_capped(clock: Clock) -> None:
    """Req. 4: cada bloqueo seguido dobla la espera, hasta 8 veces `lock_s`."""
    limiter = _limiter(clock, attempts=1, lock_s=10.0)
    waits = []
    for _ in range(6):
        limiter.failure("ip:192.0.2.10")
        wait = limiter.retry_after("ip:192.0.2.10")
        assert wait is not None
        waits.append(wait)
        clock.advance(wait)
    assert waits == [10.0, 20.0, 40.0, 80.0, 80.0, 80.0]


def test_limiter_success_resets_failures_and_strikes(clock: Clock) -> None:
    """Req. 4: un login correcto reinicia el contador y la espera progresiva."""
    limiter = _limiter(clock, attempts=2, lock_s=10.0)
    for _ in range(2):
        limiter.failure("user:af-demo")
    clock.advance(10)
    limiter.success("user:af-demo")
    limiter.failure("user:af-demo")
    assert limiter.retry_after("user:af-demo") is None
    limiter.failure("user:af-demo")
    assert limiter.retry_after("user:af-demo") == 10.0  # no 20: los strikes se borraron


def test_limiter_unknown_keys_are_not_blocked(clock: Clock) -> None:
    """Req. 4: sin intentos previos no hay espera."""
    assert _limiter(clock).retry_after("user:nadie", "ip:192.0.2.1") is None
    assert _limiter(clock).retry_after() is None


def test_limiter_purges_unlocked_keys_and_keeps_locked_ones(
    clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Req. 4: con muchas claves, la purga quita las no bloqueadas y conserva las bloqueadas."""
    monkeypatch.setattr("api.sessions.MAX_TRACKED_KEYS", 3)
    limiter = _limiter(clock, attempts=2, lock_s=10.0)
    for _ in range(2):
        limiter.failure("ip:192.0.2.10")  # bloqueada
    for n in range(3):
        limiter.failure(f"user:ficticio-{n}")  # un fallo, sin bloqueo
    assert len(limiter._by_key) == 4
    limiter.failure("user:nuevo-ficticio")  # más de 3 claves -> purga antes de anotar
    assert set(limiter._by_key) == {"ip:192.0.2.10", "user:nuevo-ficticio"}
    assert limiter.retry_after("ip:192.0.2.10") == 10.0


def test_limiter_purge_drops_expired_locks(clock: Clock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Req. 4: un bloqueo ya vencido también se purga (no crece sin tope)."""
    monkeypatch.setattr("api.sessions.MAX_TRACKED_KEYS", 1)
    limiter = _limiter(clock, attempts=1, lock_s=10.0)
    limiter.failure("ip:192.0.2.10")
    limiter.failure("ip:192.0.2.11")
    clock.advance(11)
    limiter.failure("ip:192.0.2.12")
    assert set(limiter._by_key) == {"ip:192.0.2.12"}
    assert limiter.retry_after("ip:192.0.2.12") == 10.0


def test_limiter_does_not_purge_below_threshold(clock: Clock) -> None:
    """Req. 4 (límite): por debajo del tope no se borra ningún contador."""
    limiter = _limiter(clock, attempts=3)
    for n in range(5):
        limiter.failure(f"user:ficticio-{n}")
    assert len(limiter._by_key) == 5
