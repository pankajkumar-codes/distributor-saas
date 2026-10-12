# Domain Model (Technology-Neutral)

This is a conceptual model, not a finalized database schema. Confirm cardinalities, legal scope, and retention rules before migration design.

## Core entities

### Tenant and access
- Tenant: customer workspace.
- User: login identity.
- Membership: association between user and tenant, including role and status.
- Role/Permission: capabilities granted within a tenant.
- AuditEvent: actor, tenant, action, entity reference, timestamp, and safe change metadata.

### Legal and configuration
- LegalEntity: legal business identity within a tenant; initial UX may start with one.
- GSTRegistration: GST registration and state-specific details where applicable.
- BusinessLocation: warehouse/office/location.
- FinancialYear: configurable accounting/invoice period.
- NumberingSeries: document type, approved scope, sequence configuration, and period.
- TaxRule/TaxClassification: configurable tax data with source, validity dates, and review status.

### Catalog and procurement
- Product: internal catalog item.
- ExternalProductMapping: marketplace/channel listing SKU mapped to an internal product.
- Supplier: supplier identity and tax details.
- PurchaseDocument: supplier invoice/reference and purchase state.
- PurchaseLine: product, quantity, unit price, discount, tax inputs, and captured historical values.
- GoodsReceipt: accepted stock receipt linked to a purchase or adjustment.
- LandedCostAllocation: approved freight/other attributable cost allocation if implemented.

### Sales and channels
- Customer: wholesale buyer.
- SalesOrder: internal order intent where used.
- SalesDocument: internal invoice/document with draft/finalized/voided state.
- SalesLine: product, quantity, price, discount, tax inputs, and historical snapshots.
- Channel: marketplace or direct wholesale channel.
- ExternalOrder: source platform, external order ID, source status, dates, raw/imported references.
- ExternalInvoiceReference: invoice issuer, external invoice ID/number, date, and source where known.
- Return/Refund: source-linked reversal/adjustment records.
- CreditNote/DebitNote: legally reviewed adjustment documents where applicable.

### Inventory
- InventoryLocation: warehouse/store location.
- StockMovement: immutable quantity movement with source type/id, product, location, quantity, and event time.
- StockReservation: reservation/release history where enabled.
- StockBalance: optional derived/cache view, never the only source of truth.
- Batch/Serial: optional traceability entities if approved.

### Money, settlement, accounting
- Payment: money received/paid/refunded, method, date, external reference, and status.
- PaymentAllocation: links payment to invoices/documents.
- MarketplaceSettlement: source statement and period.
- SettlementLine: gross transaction, fees, refund, reserve, adjustment, or payout components.
- BankPayout: amount and bank reference, kept distinct from sales revenue.
- Expense: business expense with category, date, amount, tax treatment fields, and evidence reference as appropriate.
- AccountingExportBatch: export scope, status, file/reference, and reconciliation result.
- ExternalAccountingMapping: external account/tax/contact/item mappings.
- ImportRun/ImportRow: source file, checksum, row number, validation state, normalized record reference, and error details.

## Relationships and invariants

- Every tenant-owned business record is associated with exactly one tenant or with a tenant-owned parent whose ownership is enforced.
- Cross-tenant references are rejected.
- Marketplace SKU mappings are tenant-scoped and channel-scoped.
- A source external order identifier is unique within its defined tenant/channel/source scope.
- A finalized financial document references historical line values and tax inputs; later product changes do not rewrite history.
- Posted stock movements are append-only; corrections use compensating movements.
- A retry must not create duplicate financial or stock effects.
- Payment allocation must not exceed permitted allocatable balances unless an explicit overpayment/advance workflow handles it.
- Derived balances and reports must be reproducible from authoritative transactions.

## Open modeling choices

- Invoice-numbering uniqueness scope.
- Whether tenant may later contain multiple legal entities/GST registrations.
- Inventory reservation and deduction event for each channel.
- Costing method and treatment of freight/landed cost.
- Whether full accounting ledger is in scope.
- Retention of raw marketplace source files and sensitive fields.
