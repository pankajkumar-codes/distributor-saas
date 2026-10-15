"""Roles and what each one may do (backlog E0-4, docs/PERMISSIONS.md).

The matrix is the Product Owner's decision (team roles matrix, PO-1); this module is its
one table in code. Every service checks it on the server; the UI hiding a button is never
the control. Permissions are fixed per role (no per-tenant overrides).

Order of checks in an endpoint:
1. Resolve the caller's *active* membership for the tenant. Not a member, or the
   tenant does not exist: 404 (platform_common.tenancy.not_found), so other tenants'
   ids reveal nothing.
2. `require_permission(membership.role, Permission.X, reason=...)`. A member without the
   right: 403. For permissions in REASON_REQUIRED a blank reason is 422, and the endpoint
   must write an audit event carrying the reason in the same transaction as the change.
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
    # Tenant and setup
    PROFILE_VIEW = "profile.view"
    PROFILE_EDIT = "profile.edit"
    PROFILE_CHANGE_GSTIN_AFTER_FINALIZED = "profile.change_gstin_after_finalized"
    MEMBERS_INVITE = "members.invite"
    MEMBERS_MANAGE_OWNERS = "members.manage_owners"
    MEMBERS_DEACTIVATE = "members.deactivate"
    AUDIT_VIEW = "audit.view"
    TENANT_SETTINGS_EDIT = "tenant_settings.edit"

    # Catalog, suppliers, purchases
    CATALOG_VIEW = "catalog.view"
    CATALOG_EDIT = "catalog.edit"
    CATALOG_IMPORT_CONFIRM = "catalog.import_confirm"
    SKU_MAPPING_EDIT = "sku_mapping.edit"
    SUPPLIERS_EDIT = "suppliers.edit"
    PURCHASE_DRAFT = "purchase.draft"
    PURCHASE_POST = "purchase.post"
    STOCK_RECEIVE = "stock.receive"
    STOCK_OVER_RECEIVE = "stock.over_receive"
    SUPPLIER_PAYMENT_RECORD = "supplier_payment.record"

    # Stock
    STOCK_VIEW = "stock.view"
    OPENING_STOCK_POST = "opening_stock.post"
    STOCK_ADJUST = "stock.adjust"
    STOCK_ADJUST_ABOVE_THRESHOLD = "stock.adjust_above_threshold"
    RETURNS_INSPECT = "returns.inspect"
    STOCK_POST_NEGATIVE = "stock.post_negative"

    # Imports
    IMPORT_ORDERS_UPLOAD = "import.orders_upload"
    IMPORT_ORDERS_CONFIRM = "import.orders_confirm"
    IMPORT_SETTLEMENT = "import.settlement"
    IMPORT_EXCEPTIONS_FIX = "import.exceptions_fix"
    IMPORT_SETTLEMENT_EXCEPTIONS_FIX = "import.settlement_exceptions_fix"
    IMPORT_RAW_DOWNLOAD = "import.raw_download"

    # Wholesale sales and money
    CUSTOMERS_EDIT = "customers.edit"
    INVOICE_DRAFT = "invoice.draft"
    INVOICE_FINALIZE = "invoice.finalize"
    CREDIT_DEBIT_NOTE = "credit_debit_note.issue"
    INVOICE_PDF_DOWNLOAD = "invoice.pdf_download"
    PAYMENT_RECORD = "payment.record"
    PAYMENT_ALLOCATE = "payment.allocate"
    PAYMENT_REALLOCATE = "payment.reallocate"
    SETTLEMENT_MANUAL_MATCH = "settlement.manual_match"
    EXPENSE_RECORD = "expense.record"

    # Reports and exports
    COST_VIEW = "cost.view"
    SALES_REPORT_VIEW = "sales_report.view"
    PURCHASE_REGISTER_VIEW = "purchase_register.view"
    SUPPLIER_BALANCES_VIEW = "supplier_balances.view"
    RECEIVABLES_VIEW = "receivables.view"
    GST_SUMMARY_VIEW = "gst_summary.view"
    ACCOUNTANT_EXPORT = "accountant.export"


P = Permission
_ALL = frozenset(Role)
_OA = frozenset({Role.owner, Role.admin})


def _r(*roles: Role) -> frozenset[Role]:
    return _OA | frozenset(roles)


# The one table: permission -> roles allowed. Owner and admin are included by _r().
PERMISSION_ROLES: dict[Permission, frozenset[Role]] = {
    P.PROFILE_VIEW: _ALL,
    P.PROFILE_EDIT: _r(),
    P.PROFILE_CHANGE_GSTIN_AFTER_FINALIZED: frozenset({Role.owner}),
    P.MEMBERS_INVITE: _r(),
    P.MEMBERS_MANAGE_OWNERS: frozenset({Role.owner}),
    P.MEMBERS_DEACTIVATE: _r(),
    P.AUDIT_VIEW: _r(),
    P.TENANT_SETTINGS_EDIT: frozenset({Role.owner}),
    P.CATALOG_VIEW: _ALL,
    P.CATALOG_EDIT: _r(Role.inventory),
    P.CATALOG_IMPORT_CONFIRM: _r(Role.inventory),
    P.SKU_MAPPING_EDIT: _r(Role.inventory),
    P.SUPPLIERS_EDIT: _r(Role.inventory, Role.finance),
    P.PURCHASE_DRAFT: _r(Role.inventory, Role.finance),
    P.PURCHASE_POST: _r(Role.inventory, Role.finance),
    P.STOCK_RECEIVE: _r(Role.inventory),
    P.STOCK_OVER_RECEIVE: _r(Role.inventory),
    P.SUPPLIER_PAYMENT_RECORD: _r(Role.finance),
    P.STOCK_VIEW: _ALL,
    P.OPENING_STOCK_POST: _r(Role.inventory),
    P.STOCK_ADJUST: _r(Role.inventory),
    P.STOCK_ADJUST_ABOVE_THRESHOLD: _r(),
    P.RETURNS_INSPECT: _r(Role.inventory),
    P.STOCK_POST_NEGATIVE: _r(),
    P.IMPORT_ORDERS_UPLOAD: _r(Role.sales, Role.inventory),
    P.IMPORT_ORDERS_CONFIRM: _r(Role.inventory),
    P.IMPORT_SETTLEMENT: _r(Role.finance),
    P.IMPORT_EXCEPTIONS_FIX: _r(Role.inventory),
    P.IMPORT_SETTLEMENT_EXCEPTIONS_FIX: _r(Role.finance),
    P.IMPORT_RAW_DOWNLOAD: _r(),
    P.CUSTOMERS_EDIT: _r(Role.sales, Role.finance),
    P.INVOICE_DRAFT: _r(Role.sales, Role.finance),
    P.INVOICE_FINALIZE: _r(Role.sales, Role.finance),
    P.CREDIT_DEBIT_NOTE: _r(Role.finance),
    P.INVOICE_PDF_DOWNLOAD: _r(Role.sales, Role.finance, Role.viewer),
    P.PAYMENT_RECORD: _r(Role.sales, Role.finance),
    P.PAYMENT_ALLOCATE: _r(Role.finance),
    P.PAYMENT_REALLOCATE: _r(Role.finance),
    P.SETTLEMENT_MANUAL_MATCH: _r(Role.finance),
    P.EXPENSE_RECORD: _r(Role.finance),
    P.COST_VIEW: _r(Role.finance),
    P.SALES_REPORT_VIEW: _r(Role.sales, Role.finance, Role.viewer),
    P.PURCHASE_REGISTER_VIEW: _r(Role.inventory, Role.finance),
    P.SUPPLIER_BALANCES_VIEW: _r(Role.finance),
    P.RECEIVABLES_VIEW: _r(Role.sales, Role.finance),
    P.GST_SUMMARY_VIEW: _r(Role.finance),
    P.ACCOUNTANT_EXPORT: _r(Role.finance),
}

# Reasons land in audit event details; same bound as other free-text audit fields.
MAX_REASON_LENGTH = 500

# The matrix's ⚠ actions: allowed only with a non-blank reason, recorded in an audit event.
REASON_REQUIRED: frozenset[Permission] = frozenset(
    {
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
)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    role: frozenset(p for p, roles in PERMISSION_ROLES.items() if role in roles) for role in Role
}


def has_permission(role: Role | str | None, permission: Permission) -> bool:
    """False for unknown roles: a role string from storage that we don't recognise gets nothing."""
    try:
        role = Role(role)
    except ValueError:
        return False
    return role in PERMISSION_ROLES[permission]


def require_permission(role: Role | str | None, permission: Permission, reason: str | None = None) -> None:
    """Call after the caller's active membership is resolved.

    403 if the role lacks the permission; 422 if the permission needs a reason and none was given,
    or it is longer than MAX_REASON_LENGTH. 422 is a literal because Starlette renamed its constant.
    """
    if not has_permission(role, permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed")
    if permission in REASON_REQUIRED:
        if not (reason and reason.strip()):
            raise HTTPException(422, "a reason is required")
        if len(reason) > MAX_REASON_LENGTH:
            raise HTTPException(422, f"reason must be at most {MAX_REASON_LENGTH} characters")


def roles_with(permission: Permission) -> frozenset[Role]:
    return PERMISSION_ROLES[permission]


def without_cost_fields(role: Role | str | None, row: dict, cost_fields: frozenset[str] | set[str]) -> dict:
    """Drop purchase-rate, cost, valuation, margin and profit fields for roles without COST_VIEW.

    The fields are removed, not blanked, so a client can't tell a hidden cost from a zero one.
    Exception per the matrix: the purchase register shows purchase rates to PURCHASE_REGISTER_VIEW,
    so that endpoint does not call this for its rate columns.
    """
    if has_permission(role, Permission.COST_VIEW):
        return row
    return {k: v for k, v in row.items() if k not in cost_fields}
