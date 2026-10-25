"""E0-4 / T-002: every permission x role pair, reasons for ⚠ actions, cost stripping, doc sync.

EXPECTED is transcribed by hand from the Product Owner's roles matrix (PO-1), one row per
matrix action, so changing what a role may do must change this table too and shows up in review.
Columns: owner admin sales inventory finance viewer; "x" allowed, "." denied.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from platform_common.permissions import (
    MAX_REASON_LENGTH,
    PERMISSION_ROLES,
    REASON_REQUIRED,
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    require_permission,
    roles_with,
    without_cost_fields,
)

P = Permission
ORDER = [Role.owner, Role.admin, Role.sales, Role.inventory, Role.finance, Role.viewer]

EXPECTED = {
    # Tenant and setup
    P.PROFILE_VIEW: "xxxxxx",
    P.PROFILE_EDIT: "xx....",
    P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED: "x.....",
    P.MEMBERS_INVITE: "xx....",
    P.MEMBERS_MANAGE_OWNERS: "x.....",
    P.MEMBERS_DEACTIVATE: "xx....",
    P.AUDIT_VIEW: "xx....",
    P.TENANT_SETTINGS_EDIT: "x.....",
    # Catalog, suppliers, purchases
    P.CATALOG_VIEW: "xxxxxx",
    P.CATALOG_EDIT: "xx.x..",
    P.CATALOG_IMPORT_CONFIRM: "xx.x..",
    P.SKU_MAPPING_EDIT: "xx.x..",
    P.SUPPLIERS_EDIT: "xx.xx.",
    P.PURCHASE_DRAFT: "xx.xx.",
    P.PURCHASE_POST: "xx.xx.",
    P.STOCK_RECEIVE: "xx.x..",
    P.STOCK_OVER_RECEIVE: "xx.x..",
    P.SUPPLIER_PAYMENT_RECORD: "xx..x.",
    # Stock
    P.STOCK_VIEW: "xxxxxx",
    P.OPENING_STOCK_POST: "xx.x..",
    P.STOCK_ADJUST: "xx.x..",
    P.STOCK_ADJUST_ABOVE_THRESHOLD: "xx....",
    P.RETURNS_INSPECT: "xx.x..",
    P.STOCK_POST_NEGATIVE: "xx....",
    # Imports
    P.IMPORT_ORDERS_UPLOAD: "xxxx..",
    P.IMPORT_ORDERS_CONFIRM: "xx.x..",
    P.IMPORT_SETTLEMENT: "xx..x.",
    P.IMPORT_EXCEPTIONS_FIX: "xx.x..",
    P.IMPORT_SETTLEMENT_EXCEPTIONS_FIX: "xx..x.",
    P.IMPORT_RAW_DOWNLOAD: "xx....",
    # Wholesale sales and money
    P.CUSTOMERS_EDIT: "xxx.x.",
    P.INVOICE_DRAFT: "xxx.x.",
    P.INVOICE_FINALIZE: "xxx.x.",
    P.CREDIT_DEBIT_NOTE: "xx..x.",
    P.INVOICE_PDF_DOWNLOAD: "xxx.xx",
    P.PAYMENT_RECORD: "xxx.x.",
    P.PAYMENT_ALLOCATE: "xx..x.",
    P.PAYMENT_REALLOCATE: "xx..x.",
    P.SETTLEMENT_MANUAL_MATCH: "xx..x.",
    P.EXPENSE_RECORD: "xx..x.",
    # Reports and exports
    P.COST_VIEW: "xx..x.",
    P.SALES_REPORT_VIEW: "xxx.xx",
    P.PURCHASE_REGISTER_VIEW: "xx.xx.",
    P.SUPPLIER_BALANCES_VIEW: "xx..x.",
    P.RECEIVABLES_VIEW: "xxx.x.",
    P.GST_SUMMARY_VIEW: "xx..x.",
    P.ACCOUNTANT_EXPORT: "xx..x.",
}

# The matrix's ⚠ rows.
EXPECTED_REASON = {
    P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED,
    P.MEMBERS_DEACTIVATE,
    P.TENANT_SETTINGS_EDIT,
    P.STOCK_OVER_RECEIVE,
    P.STOCK_ADJUST,
    P.STOCK_ADJUST_ABOVE_THRESHOLD,
    P.STOCK_POST_NEGATIVE,
    P.CREDIT_DEBIT_NOTE,
    P.PAYMENT_REALLOCATE,
    P.SETTLEMENT_MANUAL_MATCH,
}


def _allowed(permission: Permission, role: Role) -> bool:
    return EXPECTED[permission][ORDER.index(role)] == "x"


def test_every_permission_is_in_the_expected_table():
    assert set(EXPECTED) == set(Permission) == set(PERMISSION_ROLES)


@pytest.mark.parametrize("role", ORDER, ids=lambda r: r.value)
@pytest.mark.parametrize("permission", list(Permission), ids=lambda p: p.value)
def test_permission_per_role(permission, role):
    allowed = _allowed(permission, role)
    assert has_permission(role, permission) is allowed
    reason = "counted twice" if permission in EXPECTED_REASON else None
    if allowed:
        require_permission(role, permission, reason=reason)
    else:
        with pytest.raises(HTTPException) as exc:
            require_permission(role, permission, reason=reason)
        assert exc.value.status_code == 403


def test_reason_required_set_matches_matrix():
    assert REASON_REQUIRED == EXPECTED_REASON


@pytest.mark.parametrize("permission", sorted(EXPECTED_REASON), ids=lambda p: p.value)
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reason_required_actions_reject_blank_reason(permission, reason):
    with pytest.raises(HTTPException) as exc:
        require_permission(Role.owner, permission, reason=reason)
    assert exc.value.status_code == 422


def test_reason_longer_than_limit_is_rejected():
    require_permission(Role.owner, P.STOCK_ADJUST, reason="x" * MAX_REASON_LENGTH)
    with pytest.raises(HTTPException) as exc:
        require_permission(Role.owner, P.STOCK_ADJUST, reason="x" * (MAX_REASON_LENGTH + 1))
    assert exc.value.status_code == 422


def test_denied_role_gets_403_before_reason_is_checked():
    with pytest.raises(HTTPException) as exc:
        require_permission(Role.viewer, P.STOCK_ADJUST, reason=None)
    assert exc.value.status_code == 403


def test_owner_has_everything():
    assert ROLE_PERMISSIONS[Role.owner] == frozenset(Permission)


def test_admin_lacks_only_owner_powers():
    assert frozenset(Permission) - ROLE_PERMISSIONS[Role.admin] == {
        P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED,
        P.MEMBERS_MANAGE_OWNERS,
        P.TENANT_SETTINGS_EDIT,
    }


@pytest.mark.parametrize("role", ["owner", "viewer"])
def test_role_given_as_stored_string(role):
    assert has_permission(role, P.STOCK_VIEW)


@pytest.mark.parametrize("role", ["superuser", "", "OWNER", None])
def test_unknown_role_gets_nothing(role):
    assert not any(has_permission(role, p) for p in Permission)
    with pytest.raises(HTTPException) as exc:
        require_permission(role, P.STOCK_VIEW)
    assert exc.value.status_code == 403


def test_roles_with():
    assert roles_with(P.MEMBERS_INVITE) == {Role.owner, Role.admin}


COST_FIELDS = frozenset({"unit_cost", "stock_value", "margin"})


@pytest.mark.parametrize("role", ORDER, ids=lambda r: r.value)
def test_cost_fields_removed_for_sales_inventory_viewer(role):
    row = {"sku": "SKU-1", "on_hand": 4, "unit_cost": "12.50", "stock_value": "50.00", "margin": "3.10"}
    out = without_cost_fields(role, row, COST_FIELDS)
    if role in (Role.owner, Role.admin, Role.finance):
        assert out == row
    else:
        assert out == {"sku": "SKU-1", "on_hand": 4}


def _doc_matrix() -> tuple[dict[str, str], set[str]]:
    doc = Path(__file__).resolve().parents[3] / "docs" / "PERMISSIONS.md"
    lines = doc.read_text(encoding="utf-8").splitlines()
    header = next(line for line in lines if line.startswith("| Permission |"))
    roles = [c.strip() for c in header.strip("|").split("|")[2:]]
    assert roles == [r.value for r in ORDER]
    matrix, reasons = {}, set()
    for line in lines:
        m = re.match(r"\| `([a-z_.]+)` \|", line)
        if m:
            marks = [c.strip() for c in line.strip("|").split("|")[2:]]
            assert set(marks) <= {"✅", "⚠", "❌"}, line
            matrix[m.group(1)] = "".join("." if mark == "❌" else "x" for mark in marks)
            if "⚠" in marks:
                reasons.add(m.group(1))
    return matrix, reasons


def test_docs_matrix_matches_code():
    matrix, reasons = _doc_matrix()
    assert matrix == {p.value: EXPECTED[p] for p in Permission}
    assert reasons == {p.value for p in REASON_REQUIRED}
