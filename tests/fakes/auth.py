"""Fake de AuthProvider con los usuarios sintéticos de demo."""

import hmac
from dataclasses import dataclass, field

from adapters.base import User
from tests.fakes import dataset


@dataclass
class FakeAuthProvider:
    users: dict[str, tuple[str, User]] = field(default_factory=lambda: dict(dataset.DEMO_USERS))

    def authenticate(self, username: str, password: str) -> User | None:
        entry = self.users.get(username)
        if entry is None or not hmac.compare_digest(entry[0], password):
            return None
        return entry[1].model_copy()
