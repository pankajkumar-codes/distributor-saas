# Proposed Implementation Plan

Do not finalize technology or implement beyond approved gates.

## Stage 0 — Repository and requirement baseline
- Inspect current files and tooling.
- Identify existing stack and conventions without changing them.
- Summarize current project state.
- List blocking decisions and assumptions.
- Add acceptance criteria and sample import specifications.
- No dependency installation or destructive changes.

## Stage 1 — Architecture approval
- Present stack and cloud alternatives with cost/maintenance/security trade-offs.
- Present a proposed modular-monolith boundary and deployment diagram.
- Present a conceptual ER diagram and transaction boundaries.
- Obtain approval before finalizing.

## Stage 2 — Foundation
- Project structure and environments.
- Authentication and tenant membership.
- Server-side tenant authorization.
- Audit trail.
- Database migrations and test setup.
- Tenant-isolation tests.

## Stage 3 — Catalog and procurement
- Product/SKU mapping.
- Suppliers and purchase documents.
- Goods receipt and stock movement ledger.
- Opening stock and adjustments.
- Idempotent stock operations.

## Stage 4 — Wholesale workflow
- Customers.
- Draft and finalization lifecycle.
- Invoice numbering after approved rules.
- PDF output after template/tax requirements are approved.
- Payments, allocations, returns, and outstanding balances.

## Stage 5 — Marketplace import workflow
- Upload and staging.
- Preview, validation, mapping, deduplication, and row-level errors.
- Order/return/settlement import adapters.
- Idempotency and reconciliation.
- Do not issue invoices automatically until issuer/source-of-truth rules are approved.

## Stage 6 — Reports and exports
- Stock reconciliation.
- Sales and purchase registers.
- Marketplace settlement reconciliation.
- Receivables/payables.
- Profitability using approved costing policy.
- CSV/Excel exports.

## Stage 7 — Accounting/GST integration decisions
- Select accounting product/provider only after review.
- Confirm supported GST scenarios and eligibility.
- Build approved connector behind an adapter.
- Validate with sandbox/test data and a qualified professional.

## Stage 8 — Deployment and release
- Cloud selection and budget approval.
- CI/CD, secrets, monitoring, backups, restoration, rollback.
- Security and performance verification.
- Production readiness review.
