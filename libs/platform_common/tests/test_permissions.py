"""The role table, one test per cell, and the `require` dependency.

EXPECTED is copied by hand from the BRD role table (team/lead/hld-inputs-brd-mocks.md
section B), not read from the YAML, so an edit to the YAML that the Product Owner
didn't make fails here.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from platform_common.errors import Deny, Invalid
from platform_common.permissions import (
    MAX_REASON_LENGTH,
    PERMISSION_ROLES,
    REASON_REQUIRED,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    matrix,
    require,
    require_reason,
    validate,
)
from platform_common.uow import Principal, UnitOfWork

ROLES = [Role.owner, Role.admin, Role.billing, Role.ca]
P = Permission
#                                owner admin billing ca
EXPECTED: dict[Permission, str] = {
    P.SETTINGS_EDIT:        "xx..",
    P.MEMBERS_MANAGE:       "xx..",
    P.CATALOG_VIEW:         "xxxx",
    P.CATALOG_EDIT:         "xxx.",
    P.DOCUMENTS_CREATE:     "xxx.",
    P.DOCUMENTS_MARK_PAID:  "xxx.",
    P.UPLOADS_CREATE:       "xx.x",
    P.RETURNS_PREPARE:      "xx.x",
    P.RETURNS_LOCK:         "xx.x",
    P.RETURNS_UNLOCK:       "x...",
    P.AUDIT_VIEW:           "xx..",
    P.SUPPORT_GRANT:        "x...",
    P.JOBS_VIEW:            "xxxx",
}  # fmt: skip
REPO = Path(__file__).resolve().parents[3]


def test_every_permission_has_an_expected_row():
    assert set(EXPECTED) == set(Permission) == set(PERMISSION_ROLES)


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", ROLES)
def test_cell(permission, role):
    allowed = EXPECTED[permission][ROLES.index(role)] == "x"
    assert has_permission(role, permission) is allowed
    assert has_permission(role.value, permission) is allowed
    assert (permission in ROLE_PERMISSIONS[role]) is allowed


@pytest.mark.parametrize("role", [None, "", "Owner", "sales", "viewer", "superuser"])
def test_unknown_role_gets_nothing(role):
    assert not any(has_permission(role, p) for p in Permission)


def _uow(role, grant=None) -> UnitOfWork:
    principal = Principal(user_sub="u", request_id="r", role=role, support_grant_id=grant)
    return UnitOfWork(tx=None, principal=principal, read_only=False)


@pytest.mark.parametrize("permission", list(Permission))
@pytest.mark.parametrize("role", ROLES)
def test_require_refuses_with_role_denied(permission, role):
    check = require(permission)
    assert check.permission is permission
    if EXPECTED[permission][ROLES.index(role)] == "x":
        assert check(_uow(role.value)) is None
    else:
        with pytest.raises(Deny) as exc:
            check(_uow(role.value))
        assert exc.value.reason == "role_denied"


@pytest.mark.parametrize("permission", list(Permission))
def test_support_principal_may_only_view(permission):
    check = require(permission)
    if permission.value.endswith(".view"):
        assert check(_uow("owner", grant="g")) is None
    else:
        with pytest.raises(Deny) as exc:
            check(_uow("owner", grant="g"))
        assert exc.value.reason == "support_no_grant"


def test_reason_required_actions():
    assert "returns.unlock" in REASON_REQUIRED
    assert require_reason("returns.unlock", "  wrong ARN ") == "wrong ARN"


@pytest.mark.parametrize("reason", [None, "", "   ", "\n\t"])
def test_blank_reason_is_invalid(reason):
    with pytest.raises(Invalid) as exc:
        require_reason("members.deactivate", reason)
    assert exc.value.code == "reason_required" and exc.value.status == 422


def test_long_reason_is_invalid():
    require_reason("returns.unlock", "x" * MAX_REASON_LENGTH)
    with pytest.raises(Invalid):
        require_reason("returns.unlock", "x" * (MAX_REASON_LENGTH + 1))


def test_unknown_reason_action_is_a_programming_error():
    with pytest.raises(ValueError):
        require_reason("catalog.edit", "why")


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["roles"].append("viewer"),
        lambda d: d["permissions"].pop("support.grant"),
        lambda d: d["permissions"]["catalog.edit"]["roles"].append("sales"),
    ],
)
def test_matrix_that_disagrees_with_the_enums_is_refused(edit):
    import copy

    data = copy.deepcopy(matrix())
    edit(data)
    with pytest.raises(RuntimeError):
        validate(data)


def test_permissions_doc_is_generated_from_the_matrix():
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_permissions_doc.py"), "--check"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout
