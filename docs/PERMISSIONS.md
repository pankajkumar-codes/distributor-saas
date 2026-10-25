# Role permissions matrix

Backlog story E0-4, task T-002. **The Product Owner decides the matrix** (team board,
`product/roles-matrix.md`, PO-1; a reversible product decision, not a `CLAUDE.md` approval gate).
This page is its engineering mapping: one named permission per matrix action.

Source of truth in code: `libs/platform_common/platform_common/permissions.py` (`PERMISSION_ROLES`).
`libs/platform_common/tests/test_permissions.py` checks every permission × role pair against a
hand-written copy of the PO matrix and fails if this page and the code disagree.

## Rules

- One role per membership; permissions are fixed per role. No per-tenant or per-user overrides in the MVP.
- Checks run on the server in every service. Hiding a button in the UI is never the control.
- Order of checks in an endpoint:
  1. Resolve the caller's **active** membership for the tenant. Not a member, disabled, or the
     tenant does not exist: **404**, so other tenants' ids reveal nothing (global AC 1).
  2. `require_permission(role, Permission.X, reason=...)`. A member without the permission: **403**.
  3. For ⚠ permissions (`REASON_REQUIRED`), a missing, blank or over-500-character `reason` is **422**, and the endpoint
     writes an audit event with the reason in the same transaction as the change.
- Cost data (purchase rates, weighted-average cost, stock valuation, margin, profit) is removed from
  API responses and CSV exports for roles without `cost.view` (sales, inventory, viewer) using
  `without_cost_fields`. The fields are dropped, not zeroed. One exception from the PO matrix:
  the purchase register shows purchase rates to inventory (`purchase_register.view`), without supplier balances.
- An unknown role string gets no permissions.
- Conditions on the *target* stay in the endpoint: an admin may deactivate members but not owners
  (needs `members.manage_owners`), the last active owner can never be deactivated (T-003), and
  above-threshold adjustments need `stock.adjust_above_threshold` in addition to `stock.adjust`.
- CSV export of a list uses that list's view permission, with cost columns stripped as above.

## Matrix

✅ allowed · ⚠ allowed with reason + audit · ❌ 403

| Permission | Matrix action | owner | admin | sales | inventory | finance | viewer |
|---|---|---|---|---|---|---|---|
| `profile.view` | View business profile | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `profile.edit` | Edit business profile (non-GSTIN fields) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `profile.change_gstin_after_finalized` | Change GSTIN / state after any finalized invoice | ⚠ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `members.invite` | Invite member (non-owner role) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `members.manage_owners` | Invite / promote to owner; deactivate an owner | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `members.deactivate` | Deactivate member (admin: not owners, needs `members.manage_owners`) | ⚠ | ⚠ | ❌ | ❌ | ❌ | ❌ |
| `audit.view` | View audit log | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `tenant_settings.edit` | Change tenant settings (negative-stock policy, adjustment threshold, numbering prefix) | ⚠ | ❌ | ❌ | ❌ | ❌ | ❌ |
| `catalog.view` | View products (no cost) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `catalog.edit` | Create / edit / archive products | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `catalog.import_confirm` | Bulk product CSV import (confirm) | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `sku_mapping.edit` | Marketplace SKU mapping | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `suppliers.edit` | Suppliers create / edit | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| `purchase.draft` | Purchase bill draft / edit draft | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| `purchase.post` | Post purchase bill | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| `stock.receive` | Receive stock against purchase | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `stock.over_receive` | Over-receipt | ⚠ | ⚠ | ❌ | ⚠ | ❌ | ❌ |
| `supplier_payment.record` | Supplier payments | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `stock.view` | View on-hand / movement history (quantities); stock quantities report | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `opening_stock.post` | Opening stock (once per product) | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `stock.adjust` | Adjustment within threshold | ⚠ | ⚠ | ❌ | ⚠ | ❌ | ❌ |
| `stock.adjust_above_threshold` | Adjustment above threshold | ⚠ | ⚠ | ❌ | ❌ | ❌ | ❌ |
| `returns.inspect` | Restock / write-off returned goods | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `stock.post_negative` | Manual movement that makes stock negative (only if tenant allows, D-012) | ⚠ | ⚠ | ❌ | ❌ | ❌ | ❌ |
| `import.orders_upload` | Upload + preview order / return report | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| `import.orders_confirm` | Confirm order / return import (posts stock) | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `import.settlement` | Upload + confirm settlement report | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `import.exceptions_fix` | Fix exception queue / re-run held rows (orders, returns) | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |
| `import.settlement_exceptions_fix` | Fix exception queue / re-run held rows (settlement rows) | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `import.raw_download` | Download raw uploaded file | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| `customers.edit` | Customers create / edit | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `invoice.draft` | Draft invoice | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `invoice.finalize` | Finalize invoice (allocates number, deducts stock) | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `credit_debit_note.issue` | Credit / debit note | ⚠ | ⚠ | ❌ | ❌ | ⚠ | ❌ |
| `invoice.pdf_download` | Download invoice PDF | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `payment.record` | Record customer payment | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `payment.allocate` | Allocate a customer payment | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `payment.reallocate` | Reallocate or reverse a payment | ⚠ | ⚠ | ❌ | ❌ | ⚠ | ❌ |
| `settlement.manual_match` | Manual settlement match | ⚠ | ⚠ | ❌ | ❌ | ⚠ | ❌ |
| `expense.record` | Expenses | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `cost.view` | See cost data: stock valuation, profitability, margin, purchase rates | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `sales_report.view` | Sales report (amounts, no cost) | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| `purchase_register.view` | Purchase register (with purchase rates) | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |
| `supplier_balances.view` | Supplier balances | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `receivables.view` | Receivables ageing / customer statements | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| `gst_summary.view` | GST summaries | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
| `accountant.export` | Accountant export pack | ✅ | ✅ | ❌ | ❌ | ✅ | ❌ |
