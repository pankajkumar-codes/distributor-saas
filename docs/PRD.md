# Product Requirements Document (PRD)

## 1. Product summary

Build a cloud-deployable, multi-tenant SaaS for Indian product sellers and distributors. The initial tenant is Vashi Essentials, which sells through Amazon, Flipkart, Meesho and may also sell directly to wholesale customers. The platform must also serve independent distributors purchasing from suppliers/manufacturers and reselling to shops, salons, and retailers.

The product has one shared business core with configurable workflows. It is not a marketplace itself and must not assume every tenant uses every channel.

## 2. Goals

- Support separate, securely isolated tenant workspaces.
- Manage products, suppliers, customers, purchases, stock, sales, payments, returns, and reports.
- Import marketplace reports using CSV/Excel as the first marketplace integration method.
- Support direct B2B sales and configurable GST invoice workflows.
- Reconcile marketplace orders, refunds, fees, settlement records, and payouts without conflating them.
- Provide meaningful inventory and profitability reports.
- Keep accounting integration extensible while the first accounting product remains undecided.
- Deploy to a cloud platform after cost, security, and operational options are reviewed and approved.

## 3. Non-goals for the first release unless explicitly approved

- Direct API integrations with every marketplace.
- Automatically filing GST returns.
- Assuming e-invoicing/e-way bills are required for every tenant.
- Replacing a complete accounting package with a full general ledger.
- Complex multi-company consolidation.
- Advanced warehouse optimization, demand forecasting, or route planning.
- Subscription billing and sophisticated SaaS plan management.
- Native mobile apps.

## 4. Personas

- Tenant owner/administrator: configures the business and users.
- Sales user: manages wholesale customers, orders, invoices, and collections.
- Inventory user: records receipts, movements, returns, and adjustments.
- Finance/accounting user: reviews tax summaries, payments, reconciliations, exports.
- Read-only reviewer: views permitted reports.
- SaaS operator: manages platform operations without unrestricted default access to tenant business data.

## 5. Onboarding

- Create account and tenant workspace.
- Capture legal name, trade name, contact information, business address, applicable GST details, financial year, and invoice branding.
- Select business workflows: marketplace seller, wholesale distributor, or both.
- Configure sales channels and import formats.
- Set up products and SKU mappings.
- Record opening stock using an auditable opening-stock operation.
- Configure tax behavior after validation.
- Select accounting export/integration preference when known.
- Show a setup checklist and clearly label incomplete configuration.

## 6. Functional modules

### Tenant and users
- Tenant isolation, memberships, roles, invitations, deactivation, and audit trails.
- Role-based permissions enforced server-side.

### Products
- Product name, internal SKU, description, brand/category, unit of measure, optional barcode, HSN/tax classification fields, and status.
- Channel-specific external SKU/listing mappings.
- Effective-dated purchase/selling price records where appropriate.
- Batch/expiry/serial tracking only if the business confirms the requirement.

### Suppliers and purchases
- Supplier records and supplier invoice references.
- Purchase documents, line items, taxes, discounts, freight/landed cost inputs.
- Receipt of stock linked to source transactions.
- Supplier payments, outstanding amounts, purchase returns and credit notes.
- Import support can be added when sample formats are available.

### Customers and wholesale sales
- Customer records and applicable GST details.
- Draft invoice, review, finalize, PDF/print, payment allocation, outstanding balance, returns, and credit/debit note workflows.
- Finalized documents cannot be silently edited or deleted.
- Invoice issuance rules must be approved before live use.

### Marketplace imports
- CSV/Excel upload, preview, validation, column mapping, duplicate detection, error report, and import summary.
- Track source marketplace, report type, file checksum, import run, row number, external IDs, and timestamps as appropriate.
- Support retrying failed rows safely.
- Preserve raw source values and normalized values where needed for audit/reconciliation.
- Begin with file imports; direct marketplace APIs are future scope subject to approval.

### Inventory
- Shared inventory foundation across sales channels.
- Transaction-based stock ledger with source document, location, quantity, and timestamps.
- Purchase receipt, sale/fulfilment deduction, reservation/release, returns, adjustments, and transfers if enabled.
- Avoid duplicate stock movements on retries.
- Show on-hand, reserved, and available quantities distinctly.
- Negative-stock behavior must be explicitly configured and approved.

### Payments and settlements
- Wholesale receipts, allocations, advances, refunds, and outstanding balances.
- Marketplace settlement statements and payout reconciliation as separate records.
- Marketplace fees, refunds, reserves, deductions, and payout amounts must not be misclassified as gross sales or profit.

### GST and tax reports
- Configurable tax calculation inputs and effective dates where appropriate.
- Relevant intra-state/inter-state treatment and other applicable cases only after requirements are validated.
- Sales/purchase registers, tax summaries, credit/debit note reports, HSN summaries, and reconciliation exports as applicable.
- The system must not claim statutory compliance without professional and current official validation.
- GST portal integrations, e-invoicing, e-way bills, and filing are separate capabilities requiring approved scope and provider/eligibility validation.

### Reporting
- Sales by date/channel/customer/product.
- Purchases and supplier balances.
- Inventory quantities and valuation.
- Returns, discounts, marketplace fees, settlements, and refunds.
- Receivables/payables ageing.
- Gross profit and contribution margin, with clear definitions.
- Net profit only when costs and expenses are sufficiently represented; otherwise label as estimate.
- CSV/Excel exports where appropriate.

### Accounting integration
- Accounting product is undecided.
- Initial architecture must preserve export/integration boundaries.
- Do not build a full general ledger by assumption.
- First release may use documented CSV/Excel exports and reconciliation.
- Any specific connector, account mapping, synchronization direction, conflict handling, or posting rules require approval.

## 7. Non-functional requirements

- Secure tenant isolation.
- Correctness and auditability of financial and inventory operations.
- Responsive, accessible, understandable UI.
- Reliable imports and retry behavior.
- Database integrity and safe migrations.
- Automated tests and reproducible setup.
- Backups, restore procedures, observability, and operational documentation.
- Cost-conscious initial architecture suitable for a small initial user base (about 1–20 users per tenant).
- Avoid premature distributed-system complexity.

## 8. Success criteria

- A tenant can onboard without accessing another tenant's data.
- A purchase receipt changes inventory once, even if the request/import is retried.
- Marketplace file import produces a preview and row-level errors before committing.
- Re-importing a file or external order does not duplicate transactions.
- A wholesale invoice follows an approved numbering and finalization policy.
- Reports distinguish orders, invoices, payments, settlements, fees, taxes, and profit metrics.
- Financial totals are deterministic and covered by tests.
- Backup restoration and deployment are documented and tested before production launch.
