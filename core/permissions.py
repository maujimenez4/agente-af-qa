"""Permisos por tipo de usuario (RF-46, RNF-05, D-01).

Cada rol completa su flujo de principio a fin; el administrador configura y carga conocimiento.
La UI (T-24) consulta `can` antes de mostrar cada función y `require` antes de ejecutarla.
"""

from enum import StrEnum

from adapters.base import User
from adapters.errors import AuthenticationError


class Permission(StrEnum):
    VIEW_CONTEXT = "view_context"
    GENERATE_STORY = "generate_story"
    PUBLISH_STORY = "publish_story"
    GENERATE_TESTS = "generate_tests"
    PUBLISH_TESTS = "publish_tests"
    VIEW_MEMORY = "view_memory"
    MANAGE_DOCUMENTS = "manage_documents"
    MANAGE_MODELS = "manage_models"
    MANAGE_CONNECTIONS = "manage_connections"
    MANAGE_USERS = "manage_users"


P = Permission
ROLE_PERMISSIONS: dict[str, frozenset[Permission]] = {
    "functional": frozenset({P.VIEW_CONTEXT, P.GENERATE_STORY, P.PUBLISH_STORY, P.VIEW_MEMORY}),
    "qa": frozenset({P.VIEW_CONTEXT, P.GENERATE_TESTS, P.PUBLISH_TESTS, P.VIEW_MEMORY}),
    "admin": frozenset(
        {
            P.VIEW_CONTEXT,
            P.VIEW_MEMORY,
            P.MANAGE_DOCUMENTS,
            P.MANAGE_MODELS,
            P.MANAGE_CONNECTIONS,
            P.MANAGE_USERS,
        }
    ),
}


def permissions_of(user: User | None) -> frozenset[Permission]:
    return ROLE_PERMISSIONS.get(user.role, frozenset()) if user else frozenset()


def can(user: User | None, permission: Permission) -> bool:
    return permission in permissions_of(user)


def require(user: User | None, permission: Permission) -> None:
    """Lanza `AuthenticationError` (mensaje para la UI) si el usuario no tiene el permiso."""
    if not can(user, permission):
        raise AuthenticationError("No tienes permiso para realizar esta acción.")
