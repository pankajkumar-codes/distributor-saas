"""E0-4: a test per role per sensitive action, plus the doc staying in sync with the code.

EXPECTED is written out by hand on purpose: changing what a role may do must change this
table too, so the change is visible in review.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from platform_common.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    require_permission,
    roles_with,
    without_cost_fields,
)

P = Permission
O, A, S, I, F, V = Role.owner, Role.admin, Role.sales, Role.inventory, Role.finance, Role.viewer

# Sensitive actions named in E0-4 and E3-3, and who may do them.
EXPECTED = {
    P.INVOICE_FINALIZE: {O, A, S},
    P.STOCK_ADJUST: {O, A, I},
    P.STOCK_ADJUST_ABOVE_THRESHOLD: {O, A},
    P.IMPORT_CONFIRM: {O, A, I},
    P.COST_VIEW: {O, A, F},
    P.MEMBERS_MANAGE: {O, A},
    P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED: {O},
    P.PURCHASE_POST: {O, A, F},
    P.OPENING_STOCK_POST: {O, A},
    P.PAYMENT_RECORD: {O, A, F},
}


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
@pytest.mark.parametrize("permission", list(EXPECTED), ids=lambda p: p.value)
def test_sensitive_action_per_role(permission, role):
    allowed = role in EXPECTED[permission]
    assert has_permission(role, permission) is allowed
    if allowed:
        require_permission(role, permission)
    else:
        with pytest.raises(HTTPException) as exc:
            require_permission(role, permission)
        assert exc.value.status_code == 403


def test_owner_has_everything_and_admin_all_but_gstin_change():
    assert ROLE_PERMISSIONS[O] == frozenset(Permission)
    assert frozenset(Permission) - ROLE_PERMISSIONS[A] == {P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED}


def test_viewer_can_only_view_reports():
    assert ROLE_PERMISSIONS[V] == {P.REPORTS_VIEW}


def test_every_role_has_an_entry():
    assert set(ROLE_PERMISSIONS) == set(Role)


@pytest.mark.parametrize("role", ["owner", "viewer"])
def test_role_given_as_stored_string(role):
    assert has_permission(role, P.REPORTS_VIEW)


@pytest.mark.parametrize("role", ["superuser", "", "OWNER", None])
def test_unknown_role_gets_nothing(role):
    assert not any(has_permission(role, p) for p in Permission)
    with pytest.raises(HTTPException) as exc:
        require_permission(role, P.REPORTS_VIEW)
    assert exc.value.status_code == 403


def test_roles_with():
    assert roles_with(P.MEMBERS_MANAGE) == {O, A}


COST_FIELDS = frozenset({"unit_cost", "stock_value", "margin"})


@pytest.mark.parametrize("role", list(Role), ids=lambda r: r.value)
def test_cost_fields_removed_without_cost_view(role):
    row = {"sku": "SKU-1", "on_hand": 4, "unit_cost": "12.50", "stock_value": "50.00", "margin": "3.10"}
    out = without_cost_fields(role, row, COST_FIELDS)
    if role in EXPECTED[P.COST_VIEW]:
        assert out == row
    else:
        assert out == {"sku": "SKU-1", "on_hand": 4}


def _doc_matrix() -> dict[str, dict[str, bool]]:
    doc = Path(__file__).resolve().parents[3] / "docs" / "PERMISSIONS.md"
    lines = doc.read_text(encoding="utf-8").splitlines()
    header = next(line for line in lines if line.startswith("| Permission |"))
    roles = [c.strip() for c in header.strip("|").split("|")[2:]]
    matrix = {}
    for line in lines:
        m = re.match(r"\| `([a-z_.]+)` \|", line)
        if m:
            marks = [c.strip() for c in line.strip("|").split("|")[2:]]
            assert set(marks) <= {"✓", "—"}, line
            matrix[m.group(1)] = dict(zip(roles, (mark == "✓" for mark in marks), strict=True))
    return matrix


def test_docs_matrix_matches_code():
    code = {p.value: {r.value: p in ROLE_PERMISSIONS[r] for r in Role} for p in Permission}
    assert _doc_matrix() == code
