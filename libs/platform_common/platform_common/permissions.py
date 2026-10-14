"""Roles and what each one may do (backlog E0-4, docs/PERMISSIONS.md).

Every service checks permissions on the server with these helpers; the UI hiding a
button is never the control. The matrix is fixed per role (no per-tenant overrides).

Order of checks in an endpoint:
1. Resolve the caller's *active* membership for the tenant. Not a member, or the
   tenant does not exist: 404 (platform_common.tenancy.not_found), so other tenants'
   ids reveal nothing.
2. `require_permission(membership.role, Permission.X)`. A member without the right:
   403. They already know the tenant exists, so 403 leaks nothing.
"""

import enum

from fastapi import HTTPException, status


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    sales = "sales"
    inventory = "inventory"
    finance = "finance"
    viewer = "viewer"


class Permission(str, enum.Enum):
    # Tenant administration (identity)
    MEMBERS_MANAGE = "members.manage"
    AUDIT_VIEW = "audit.view"
    PROFILE_EDIT = "profile.edit"
    PROFILE_CHANGE_GSTIN_AFTER_FINALIZED = "profile.change_gstin_after_finalized"

    # Master data (commerce)
    CATALOG_EDIT = "catalog.edit"
    SUPPLIERS_EDIT = "suppliers.edit"
    CUSTOMERS_EDIT = "customers.edit"

    # Stock and purchases (commerce)
    OPENING_STOCK_POST = "opening_stock.post"
    PURCHASE_POST = "purchase.post"
    STOCK_RECEIVE = "stock.receive"
    STOCK_ADJUST = "stock.adjust"
    STOCK_ADJUST_ABOVE_THRESHOLD = "stock.adjust_above_threshold"
    RETURNS_INSPECT = "returns.inspect"

    # Marketplace imports (imports)
    IMPORT_UPLOAD = "import.upload"
    IMPORT_CONFIRM = "import.confirm"
    SKU_MAPPING_EDIT = "sku_mapping.edit"

    # Wholesale sales and money (commerce)
    INVOICE_DRAFT = "invoice.draft"
    INVOICE_FINALIZE = "invoice.finalize"
    PAYMENT_RECORD = "payment.record"
    EXPENSE_RECORD = "expense.record"
    SETTLEMENT_RECONCILE = "settlement.reconcile"

    # Reading (reports)
    REPORTS_VIEW = "reports.view"
    COST_VIEW = "cost.view"
    ACCOUNTANT_EXPORT = "accountant.export"


P = Permission
_ALL = frozenset(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.owner: _ALL,
    Role.admin: _ALL - {P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED},
    Role.sales: frozenset(
        {
            P.CUSTOMERS_EDIT,
            P.IMPORT_UPLOAD,
            P.INVOICE_DRAFT,
            P.INVOICE_FINALIZE,
            P.REPORTS_VIEW,
        }
    ),
    Role.inventory: frozenset(
        {
            P.CATALOG_EDIT,
            P.SUPPLIERS_EDIT,
            P.STOCK_RECEIVE,
            P.STOCK_ADJUST,
            P.RETURNS_INSPECT,
            P.IMPORT_UPLOAD,
            P.IMPORT_CONFIRM,
            P.SKU_MAPPING_EDIT,
            P.REPORTS_VIEW,
        }
    ),
    Role.finance: frozenset(
        {
            P.SUPPLIERS_EDIT,
            P.CUSTOMERS_EDIT,
            P.PURCHASE_POST,
            P.PAYMENT_RECORD,
            P.EXPENSE_RECORD,
            P.SETTLEMENT_RECONCILE,
            P.REPORTS_VIEW,
            P.COST_VIEW,
            P.ACCOUNTANT_EXPORT,
        }
    ),
    Role.viewer: frozenset({P.REPORTS_VIEW}),
}


def has_permission(role: Role | str, permission: Permission) -> bool:
    """False for unknown roles: a role string from storage that we don't recognise gets nothing."""
    try:
        role = Role(role)
    except ValueError:
        return False
    return permission in ROLE_PERMISSIONS[role]


def require_permission(role: Role | str, permission: Permission) -> None:
    """Call after the caller's active membership is resolved; raises 403 if the role lacks it."""
    if not has_permission(role, permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed")


def roles_with(permission: Permission) -> frozenset[Role]:
    return frozenset(r for r, perms in ROLE_PERMISSIONS.items() if permission in perms)


def without_cost_fields(role: Role | str, row: dict, cost_fields: frozenset[str] | set[str]) -> dict:
    """Drop purchase-cost, valuation and profit fields for roles without COST_VIEW.

    The fields are removed, not blanked, so a client can't tell a hidden cost from a zero one.
    """
    if has_permission(role, Permission.COST_VIEW):
        return row
    return {k: v for k, v in row.items() if k not in cost_fields}
