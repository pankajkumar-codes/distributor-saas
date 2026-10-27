"""Roles, permissions and the `require` check (LLD-0 §3.3, docs/PERMISSIONS.md).

The cells live in `permissions_matrix.yaml`, which the Product Owner owns. This module
loads it and refuses to import if the YAML and the enums below disagree, so a role or
permission can't exist in one and not the other.

Every business route declares its permission:

    @router.post("", dependencies=[Depends(require(Permission.CATALOG_EDIT))])
    def create_product(uow: BusinessUoW, ...): ...

`require` reads the role that the unit of work resolved from the caller's active
membership. A role without the permission gets `Deny("role_denied")`, which renders as
the same 404 as an unknown business (ON-2). The UI hiding a button is never the control.
"""

import enum
from collections.abc import Callable
from functools import cache
from pathlib import Path

import yaml
from fastapi import Depends

from .errors import Deny, Invalid
from .uow import UnitOfWork, business_uow

MATRIX_FILE = Path(__file__).with_name("permissions_matrix.yaml")
MAX_REASON_LENGTH = 500


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    billing = "billing"
    ca = "ca"


class Permission(str, enum.Enum):
    SETTINGS_EDIT = "settings.edit"
    MEMBERS_MANAGE = "members.manage"
    CATALOG_VIEW = "catalog.view"
    CATALOG_EDIT = "catalog.edit"
    DOCUMENTS_CREATE = "documents.create"
    DOCUMENTS_MARK_PAID = "documents.mark_paid"
    UPLOADS_CREATE = "uploads.create"
    RETURNS_PREPARE = "returns.prepare"
    RETURNS_LOCK = "returns.lock"
    RETURNS_UNLOCK = "returns.unlock"
    AUDIT_VIEW = "audit.view"
    SUPPORT_GRANT = "support.grant"
    JOBS_VIEW = "jobs.view"


def validate(data: dict) -> dict:
    """Refuse a matrix whose roles or permissions differ from the enums."""
    if data["roles"] != [r.value for r in Role]:
        raise RuntimeError("permissions_matrix.yaml roles differ from Role")
    if list(data["permissions"]) != [p.value for p in Permission]:
        raise RuntimeError("permissions_matrix.yaml permissions differ from Permission (names or order)")
    for name, entry in data["permissions"].items():
        unknown = set(entry["roles"]) - set(data["roles"])
        if unknown:
            raise RuntimeError(f"{name}: unknown roles {sorted(unknown)}")
    return data


@cache
def matrix() -> dict:
    return validate(yaml.safe_load(MATRIX_FILE.read_text()))


PERMISSION_ROLES: dict[Permission, frozenset[Role]] = {
    Permission(name): frozenset(Role(r) for r in entry["roles"]) for name, entry in matrix()["permissions"].items()
}
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    role: frozenset(p for p, roles in PERMISSION_ROLES.items() if role in roles) for role in Role
}
REASON_REQUIRED: frozenset[str] = frozenset(matrix()["reason_required"])


def has_permission(role: Role | str | None, permission: Permission) -> bool:
    """False for an unknown role: a stored role string we don't recognise gets nothing."""
    try:
        role = Role(role)
    except ValueError:
        return False
    return role in PERMISSION_ROLES[permission]


def require(permission: Permission) -> Callable[[UnitOfWork], None]:
    """FastAPI dependency: refuse the request unless the caller's role has `permission`.

    A support user under a grant may only read, so anything but a `.view` permission is
    `support_no_grant`. The function carries `.permission` so the route-coverage check
    (LLD-0 §7) can find each route's permission.
    """
    permission = Permission(permission)

    def check(uow: UnitOfWork = Depends(business_uow, scope="function")) -> None:
        principal = uow.principal
        if principal.support_grant_id is not None and not permission.value.endswith(".view"):
            raise Deny("support_no_grant")
        if not has_permission(principal.role, permission):
            raise Deny("role_denied")

    check.permission = permission
    check.__name__ = f"require_{permission.name.lower()}"
    return check


def require_reason(action: str, reason: str | None) -> str:
    """The reason for an action in REASON_REQUIRED, stripped; Invalid if blank or too long."""
    if action not in REASON_REQUIRED:
        raise ValueError(f"{action!r} is not a reason-required action")
    text = (reason or "").strip()
    if not text:
        raise Invalid("reason_required", "a reason is required", field="reason")
    if len(text) > MAX_REASON_LENGTH:
        raise Invalid("reason_too_long", f"reason must be at most {MAX_REASON_LENGTH} characters", field="reason")
    return text
