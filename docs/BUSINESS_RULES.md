# Business Rules and Financial Invariants

Status legend: **Proposed** = suggested but not approved; **Blocking** = must be resolved before live transactions.

## 1. Tenant isolation
- Every read/write, search, export, download, background job, and report must enforce tenant scope.
- Never trust a tenant ID supplied by a client without validating membership and authorization.
- Cross-tenant IDs must not reveal whether another tenant's record exists.
- SaaS operator access to tenant data must be limited, justified, and audited.
- Deactivating a member (owner/admin only; only an owner can deactivate an owner) requires a reason, is audited, and takes effect on the member's next request. A tenant always keeps at least one active owner. Deactivated members stay in the member list with status `disabled` and are not deleted. Reactivation follows the same role rules, also requires a reason, is audited, and restores the original role.

## 2. Marketplace import integrity
- **Proposed:** imports start as a preview/staging operation; no financial or stock effects until validation and user confirmation.
- Store import run metadata and row-level errors.
- Deduplicate using stable external IDs and documented source-specific keys; do not deduplicate on approximate name/date/amount alone without review.
- Reimporting the same source data must not duplicate orders, invoices, fees, refunds, or stock movements.
- Preserve source status and timestamps; imports may arrive late or out of order.
- Store raw files only under approved access/retention controls.
- Conflicting or ambiguous rows require review rather than silent guessing.

## 3. Marketplace documents
- **Blocking:** determine who legally issues each type of customer invoice for each marketplace/workflow.
- An imported order does not automatically mean the application should issue an invoice.
- Store external invoice references and issuer details when the document is generated elsewhere.
- Distinguish order, shipment/fulfilment, invoice, refund, settlement, and bank payout.

## 4. Inventory
- **Proposed:** use an immutable stock-movement ledger; balances are derived.
- Purchase receipt creates stock movement only once.
- Sales reservation, deduction, cancellation release, and return restocking are distinct events.
- **Blocking:** define the event that reserves/deducts inventory for each marketplace and wholesale workflow.
- **Blocking:** define whether negative stock is forbidden, allowed with warning, or allowed only by role.
- Returns do not automatically become sellable stock; inspection/restock condition may be required.
- Stock adjustment requires a reason and audit record.
- Concurrent orders must not oversell available stock unless an approved policy permits it.

## 5. Invoice numbering and lifecycle
- **Blocking:** approve uniqueness scope: legal entity, GST registration, document type, financial year, and any other legally relevant dimension.
- Sequence allocation must be atomic and database-enforced.
- Drafts and finalized documents have different lifecycle rules.
- Failed finalization must not create a partially posted invoice or stock movement.
- Finalized invoices must not be silently renumbered, overwritten, or deleted.
- Corrections use approved cancellation/void/credit/debit-note processes appropriate to the case.
- Number reuse policy must be reviewed against applicable law and professional advice.

## 6. Money and tax calculations
- Use decimal-safe arithmetic for monetary values.
- Explicitly define precision, rounding sequence, tax-inclusive/exclusive price behavior, discount allocation, and line-vs-document rounding.
- Preserve historical prices, tax classifications, and calculation inputs on finalized documents.
- Tax treatment must be configurable and validated against current official requirements.
- Do not infer tax rates or eligibility from product name alone.
- Do not call a report legally compliant until reviewed.

## 7. Marketplace settlements
- Gross sales, tax, refunds, marketplace fees, reserves, deductions, and payout are distinct components.
- Bank payout is not gross sales or profit.
- Settlement reconciliation should identify matched, unmatched, and discrepant lines.
- Fees/expenses must not be counted twice if already recorded from another source.

## 8. Profitability
- **Proposed:** weighted-average inventory costing; approval required before authoritative reporting.
- Revenue recognition/report definitions must distinguish order date, invoice date, shipment date, and settlement date where relevant.
- Cost of goods sold must reflect inventory costing and returns, not simply all purchases in a period.
- Marketplace fees, shipping, discounts, refunds, and operating expenses should be visible separately.
- Label net profit as an estimate until expense completeness and accounting treatment are established.
- Do not count GST collected as revenue where it is a liability under the applicable treatment.

## 9. Accounting integration
- Accounting software is undecided.
- Initial exports should include stable identifiers, dates, tax fields, document references, and reconciliation totals.
- Do not silently retry a posting that may already have succeeded externally; check idempotency/status or require reconciliation.
- Account mappings and sync direction require explicit approval.

## 10. Data correction and audit
- Posted records use compensating transactions rather than destructive edits.
- Record who performed sensitive changes, when, and why.
- Audit logs must avoid storing passwords, tokens, or unnecessary sensitive payloads.
