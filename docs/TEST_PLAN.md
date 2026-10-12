# Test Plan

## Test layers
- Unit tests for domain rules, tax arithmetic, cost calculations, state transitions, import normalization.
- Integration tests for database constraints, transactions, sequence allocation, tenant filtering, and file processing.
- End-to-end tests for onboarding, purchase-to-stock, wholesale invoice-to-payment, marketplace import-to-reconciliation, and reports.
- Security tests for cross-tenant access, authorization, unsafe uploads, and secret leakage.
- Operational tests for migrations, backup restoration, and deployment health checks.

## Required critical scenarios

### Tenant isolation
- Tenant A cannot read, update, delete, export, or infer Tenant B records.
- A user in multiple tenants can only access the active tenant's authorized data.
- Background jobs preserve tenant context.
- Object storage downloads enforce tenant authorization.

### Import idempotency
- Upload the same file twice.
- Upload a renamed copy with identical content.
- Retry a failed import.
- Re-upload a report containing some already-imported and some new rows.
- Import rows arrive out of order.
- Conflicting duplicate external IDs are flagged.
- One invalid row does not silently corrupt unrelated rows.

### Inventory
- Purchase receipt adds stock exactly once.
- Concurrent sales cannot oversell under the approved policy.
- Cancellation releases reservation exactly once.
- Returns and restocking are auditable.
- Adjustments require reason and permission.
- Inventory balance reconciles to stock movements.

### Invoice lifecycle
- Concurrent invoice finalization cannot allocate duplicate numbers.
- Failed finalization leaves no partial financial/stock effects.
- Finalized invoice values do not change when catalog values change.
- Retries do not issue duplicate invoices.
- Void/cancellation/credit-note behavior follows approved rules.
- Tax and rounding test vectors match approved examples.

### Settlements and profitability
- Gross sales are not confused with payout.
- Fees, refunds, reserves, and adjustments reconcile.
- Expenses and purchase costs are not double counted.
- Cost of goods sold follows the approved costing policy.
- Returns reverse the appropriate sales and inventory effects.

### Deployment
- Fresh install and migration work from documented instructions.
- Health checks and error logging work.
- No secrets are required in source code.
- Backup restoration is tested.
- Rollback procedure is documented and rehearsed in a non-production environment.

## Release gate
No release is production-ready while a critical tenant-isolation, financial-integrity, data-loss, or authorization test is failing.
