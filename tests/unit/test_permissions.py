"""Pruebas de `core/permissions.py` (T-22 · RF-46, RNF-05, D-01)."""

import pytest

from adapters.base import User
from adapters.errors import AuthenticationError
from core.permissions import ROLE_PERMISSIONS, Permission, can, permissions_of, require

P = Permission
EXPECTED: dict[str, set[Permission]] = {
    "functional": {P.VIEW_CONTEXT, P.GENERATE_STORY, P.PUBLISH_STORY, P.VIEW_MEMORY},
    "qa": {P.VIEW_CONTEXT, P.GENERATE_TESTS, P.PUBLISH_TESTS, P.VIEW_MEMORY},
    "admin": {
        P.VIEW_CONTEXT,
        P.VIEW_MEMORY,
        P.MANAGE_DOCUMENTS,
        P.MANAGE_MODELS,
        P.MANAGE_CONNECTIONS,
        P.MANAGE_USERS,
    },
}
MATRIX = [(role, permission) for role in EXPECTED for permission in Permission]


def _user(role: str) -> User:
    return User(username=f"{role}-ficticio", role=role)  # type: ignore[arg-type]


@pytest.mark.parametrize(("role", "permission"), MATRIX)
def test_can_matches_role_permission_matrix(role: str, permission: Permission) -> None:
    """RF-46: matriz completa rol × permiso."""
    assert can(_user(role), permission) is (permission in EXPECTED[role])


def test_role_permissions_covers_exactly_the_three_roles() -> None:
    """RF-46: solo existen los roles functional, qa y admin."""
    assert set(ROLE_PERMISSIONS) == set(EXPECTED)
    assert {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()} == EXPECTED


def test_functional_only_handles_stories() -> None:
    """RF-46: el analista funcional genera/publica HU y no QA."""
    user = _user("functional")
    assert can(user, P.GENERATE_STORY) and can(user, P.PUBLISH_STORY)
    assert not can(user, P.GENERATE_TESTS) and not can(user, P.PUBLISH_TESTS)


def test_qa_only_handles_tests() -> None:
    """RF-46: QA genera/publica pruebas y no HU."""
    user = _user("qa")
    assert can(user, P.GENERATE_TESTS) and can(user, P.PUBLISH_TESTS)
    assert not can(user, P.GENERATE_STORY) and not can(user, P.PUBLISH_STORY)


def test_admin_configures_but_does_not_publish() -> None:
    """RF-46 / D-01: el admin configura y carga conocimiento, pero no genera ni publica."""
    user = _user("admin")
    for permission in (P.MANAGE_DOCUMENTS, P.MANAGE_MODELS, P.MANAGE_CONNECTIONS, P.MANAGE_USERS):
        assert can(user, permission)
    for permission in (P.GENERATE_STORY, P.PUBLISH_STORY, P.GENERATE_TESTS, P.PUBLISH_TESTS):
        assert not can(user, permission)


@pytest.mark.parametrize("role", list(EXPECTED))
def test_every_role_views_context_and_memory(role: str) -> None:
    """RF-46: todos los roles ven el contexto y la memoria."""
    assert can(_user(role), P.VIEW_CONTEXT)
    assert can(_user(role), P.VIEW_MEMORY)


@pytest.mark.parametrize(
    "permission", [P.MANAGE_USERS, P.MANAGE_CONNECTIONS, P.MANAGE_MODELS, P.MANAGE_DOCUMENTS]
)
@pytest.mark.parametrize("role", ["functional", "qa"])
def test_non_admin_cannot_manage_configuration(role: str, permission: Permission) -> None:
    """RF-46 (negativo): solo el admin gestiona usuarios, conexiones, modelos y documentos."""
    assert not can(_user(role), permission)


@pytest.mark.parametrize("permission", list(Permission))
def test_can_returns_false_when_no_user(permission: Permission) -> None:
    """RNF-05: sin sesión no hay ningún permiso."""
    assert can(None, permission) is False


def test_permissions_of_returns_empty_when_no_user() -> None:
    """RNF-05: permissions_of(None) → conjunto vacío."""
    assert permissions_of(None) == frozenset()


def test_unknown_role_has_no_permissions() -> None:
    """RF-46 (negativo): un rol desconocido (saltándose la validación) no tiene permisos."""
    user = User.model_construct(username="rol-desconocido", role="superuser")
    assert permissions_of(user) == frozenset()
    assert not any(can(user, permission) for permission in Permission)


def test_require_raises_spanish_error_when_permission_missing() -> None:
    """RF-46 (negativo): require sin permiso → AuthenticationError con mensaje en español."""
    with pytest.raises(AuthenticationError, match="No tienes permiso"):
        require(_user("admin"), P.PUBLISH_STORY)


def test_require_raises_when_no_user() -> None:
    """RNF-05: require sin usuario → AuthenticationError."""
    with pytest.raises(AuthenticationError):
        require(None, P.VIEW_CONTEXT)


@pytest.mark.parametrize(("role", "permission"), [(r, p) for r in EXPECTED for p in EXPECTED[r]])
def test_require_passes_when_permission_granted(role: str, permission: Permission) -> None:
    """RF-46: require no lanza si el rol tiene el permiso."""
    assert require(_user(role), permission) is None
