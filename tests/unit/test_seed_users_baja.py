"""PA-279 (RGPD): baja de los usuarios de demo con `core.seed_users.deactivate` y
`python -m core.seed_users --baja USUARIO`.

Sin BD ni `.env`: dobles que registran las llamadas. La contraseña aleatoria nunca aparece en
la salida. Datos 100 % ficticios.
"""

from types import SimpleNamespace
from typing import Any

import pytest

import core.config
import core.factories
import core.quality
from adapters.auth.seed import DEMO_USERS
from core import seed_users
from core.seed_users import deactivate


class SpyAuth:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, str, bool]] = []

    def save_user(self, username: str, password: str, role: str, active: bool = True) -> Any:
        self.saved.append((username, password, role, active))


class SpyReviews:
    def __init__(self, deleted: int = 0) -> None:
        self.deleted = deleted
        self.calls: list[str] = []

    def delete_for(self, username: str) -> int:
        self.calls.append(username)
        return self.deleted


@pytest.mark.parametrize(("username", "role"), list(DEMO_USERS))
def test_deactivate_demo_user_saves_inactive_with_random_password_and_deletes_reviews(
    username: str, role: str
) -> None:
    """Criterio 5: usuario de demo → save_user(usuario, <aleatoria>, rol, active=False) y se
    borran sus revisiones; devuelve cuántas."""
    auth, reviews = SpyAuth(), SpyReviews(deleted=4)

    deleted = deactivate(username, auth.save_user, reviews.delete_for)

    assert deleted == 4
    [(saved_user, generated, saved_role, active)] = auth.saved
    assert (saved_user, saved_role, active) == (username, role, False)
    assert len(generated) >= 16 and generated.isalnum()
    assert reviews.calls == [username]


def test_deactivate_generates_a_different_password_each_time() -> None:
    """Criterio 5: la contraseña de la baja es aleatoria (dos bajas, dos distintas)."""
    auth = SpyAuth()

    deactivate("af-demo", auth.save_user, SpyReviews().delete_for)
    deactivate("af-demo", auth.save_user, SpyReviews().delete_for)

    assert auth.saved[0][1] != auth.saved[1][1]


@pytest.mark.parametrize("username", ["ana-ficticia", "", "AF-DEMO", "af-demo "])
def test_deactivate_non_demo_user_raises_and_calls_nothing(username: str) -> None:
    """Criterio 5 (negativa): usuario que no es de demo → ValueError y no llama a nada."""
    auth, reviews = SpyAuth(), SpyReviews()

    with pytest.raises(ValueError, match="usuarios de demo"):
        deactivate(username, auth.save_user, reviews.delete_for)

    assert auth.saved == [] and reviews.calls == []


def _patch_cli(monkeypatch: pytest.MonkeyPatch, auth: SpyAuth, reviews: SpyReviews) -> None:
    settings = SimpleNamespace(sqlalchemy_url=lambda: "postgresql+psycopg://ficticia/bd")
    monkeypatch.setattr(core.config, "build_config", lambda: SimpleNamespace(settings=settings))
    monkeypatch.setattr(core.factories, "build_auth", lambda _config: auth)
    monkeypatch.setattr(
        core.quality.SqlQualityReviewStore, "from_url", classmethod(lambda _cls, _u: reviews)
    )


def test_main_baja_returns_zero_and_prints_message_without_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 5: `--baja af-demo` → 0, mensaje con el número de revisiones y sin contraseña."""
    auth, reviews = SpyAuth(), SpyReviews(deleted=3)
    _patch_cli(monkeypatch, auth, reviews)

    assert seed_users.main(["--baja", "af-demo"]) == 0

    captured = capsys.readouterr()
    [(_user, generated, _role, active)] = auth.saved
    assert active is False
    assert "af-demo" in captured.out and "dado de baja" in captured.out
    assert "3" in captured.out
    assert generated not in captured.out and generated not in captured.err
    assert "contraseña" not in captured.out.lower()
    assert reviews.calls == ["af-demo"]


def test_main_baja_unknown_user_returns_2_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 5 (negativa): usuario desconocido → 2, aviso en stderr y nada guardado."""
    auth, reviews = SpyAuth(), SpyReviews()
    _patch_cli(monkeypatch, auth, reviews)

    assert seed_users.main(["--baja", "persona-ficticia"]) == 2

    captured = capsys.readouterr()
    assert "usuarios de demo" in captured.err
    assert captured.out == ""
    assert auth.saved == [] and reviews.calls == []


def test_main_without_arguments_still_seeds_demo_users(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterio 5 (no regresión): sin argumentos sigue creando los 3 usuarios de demo."""
    auth, reviews = SpyAuth(), SpyReviews()
    _patch_cli(monkeypatch, auth, reviews)

    assert seed_users.main([]) == 0

    assert [(u, r, a) for u, _p, r, a in auth.saved] == [(u, r, True) for u, r in DEMO_USERS]
    assert reviews.calls == []
    assert "no se volverán a mostrar" in capsys.readouterr().out
