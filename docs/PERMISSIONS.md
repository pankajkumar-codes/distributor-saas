# Role permissions matrix

Backlog story E0-4. Source of truth in code: `libs/platform_common/platform_common/permissions.py`.
A test (`libs/platform_common/tests/test_permissions.py`) fails if this table and the code disagree.

Status: **proposed default** by Staff Engineer 2 (2026-10-14), for Product Owner review. Not an
approval-gated decision under `CLAUDE.md`, but the PO owns what each role is for.

## Rules

- Permissions are fixed per role. There are no per-tenant or per-user overrides in the MVP.
- Checks run on the server in every service (identity, commerce, imports, reports, documents).
  Hiding a button in the UI is never the control.
- Order of checks in an endpoint:
  1. Resolve the caller's **active** membership for the tenant. Not a member, disabled, or the
     tenant does not exist: **404**, so other tenants' ids reveal nothing (Global AC 1).
  2. `require_permission(role, Permission.X)`. A member without the permission: **403**.
- Roles without `cost.view` never receive purchase cost, stock valuation, margin or profit fields.
  The fields are removed from the response (`without_cost_fields`), not set to zero or null.
- An unknown role string (e.g. a role added later and read by an older service) gets no permissions.
- Only an owner can make someone an owner, and the last active owner cannot be removed or
  demoted (enforced in identity, T-003).

## Matrix

✓ = allowed, — = 403.

| Permission | What it allows | owner | admin | sales | inventory | finance | viewer |
|---|---|---|---|---|---|---|---|
| `members.manage` | Invite, change role of, and deactivate members | ✓ | ✓ | — | — | — | — |
| `audit.view` | Read the tenant audit log | ✓ | ✓ | — | — | — | — |
| `profile.edit` | Edit business profile, workflows, invoice logo | ✓ | ✓ | — | — | — | — |
| `profile.change_gstin_after_finalized` | Change GSTIN once any invoice is finalized (E0-3) | ✓ | — | — | — | — | — |
| `catalog.edit` | Create, edit, archive products | ✓ | ✓ | — | ✓ | — | — |
| `suppliers.edit` | Create and edit suppliers | ✓ | ✓ | — | ✓ | ✓ | — |
| `customers.edit` | Create and edit customers, credit days | ✓ | ✓ | ✓ | — | ✓ | — |
| `opening_stock.post` | Enter opening stock with unit cost (once per product) | ✓ | ✓ | — | — | — | — |
| `purchase.post` | Draft and post purchase bills (carries cost) | ✓ | ✓ | — | — | ✓ | — |
| `stock.receive` | Receive goods against a posted purchase | ✓ | ✓ | — | ✓ | — | — |
| `stock.adjust` | Post a stock adjustment up to the tenant threshold | ✓ | ✓ | — | ✓ | — | — |
| `stock.adjust_above_threshold` | Post an adjustment above the tenant threshold (E3-3) | ✓ | ✓ | — | — | — | — |
| `returns.inspect` | Restock or write off pending-inspection returns | ✓ | ✓ | — | ✓ | — | — |
| `import.upload` | Upload a marketplace file and see its preview | ✓ | ✓ | ✓ | ✓ | — | — |
| `import.confirm` | Confirm an import so it moves stock | ✓ | ✓ | — | ✓ | — | — |
| `sku_mapping.edit` | Map marketplace SKUs to products, resolve exceptions | ✓ | ✓ | — | ✓ | — | — |
| `invoice.draft` | Create and edit draft wholesale invoices | ✓ | ✓ | ✓ | — | — | — |
| `invoice.finalize` | Finalize an invoice (number, stock deduction) | ✓ | ✓ | ✓ | — | — | — |
| `payment.record` | Record customer payments and allocations | ✓ | ✓ | — | — | ✓ | — |
| `expense.record` | Record expenses | ✓ | ✓ | — | — | ✓ | — |
| `settlement.reconcile` | Match marketplace settlements to payouts | ✓ | ✓ | — | — | ✓ | — |
| `reports.view` | View reports (quantities, sales, receivables) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `cost.view` | See purchase cost, valuation, margin, profit | ✓ | ✓ | — | — | ✓ | — |
| `accountant.export` | Download the accountant export pack | ✓ | ✓ | — | — | ✓ | — |

## Why these defaults

- **inventory** runs the warehouse: products, receiving, adjustments, returns, imports. It does
  not see cost, so it receives against a purchase bill that finance posted.
- **sales** bills salons and may upload marketplace files to preview them, but cannot confirm an
  import that moves stock.
- **finance** owns money: purchase bills (with cost), payments, expenses, settlements, exports.
- **viewer** sees reports without any cost or profit fields (E0-4 acceptance criterion).

## Open points for the Product Owner

1. Should `sales` be able to finalize invoices, or only draft them for owner/admin/finance to finalize?
2. Should `inventory` see purchase cost (e.g. when checking a supplier bill on receipt)?
