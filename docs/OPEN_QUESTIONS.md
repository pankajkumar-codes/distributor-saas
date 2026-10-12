# Open Questions

Resolve these before the affected functionality is used for live financial transactions. Do not block architecture-neutral groundwork unnecessarily.

## P0 — Must resolve before live invoice and stock workflows
1. For Amazon, Flipkart, and Meesho, who generates the customer invoice today? Does it differ by marketplace, order type, or fulfillment model?
2. What sample CSV/Excel reports are available for orders, invoices, returns/refunds, settlement, and fees? Remove personal/customer data before sharing.
3. At what event should inventory be reserved and physically deducted for each sales channel?
4. What should happen when an imported order arrives after it has shipped or after stock has already changed?
5. Should negative stock be forbidden, allowed with warning, or allowed only to privileged users?
6. What is the required invoice-numbering scope: legal entity, GST registration, document type, financial year, and other applicable rules?
7. Are batches/expiry dates required for the initial products, especially salon/beauty items?
8. Which GST scenarios are in scope for the first live tenant? Obtain qualified professional validation.

## P1 — Resolve before finalizing stack/integrations
9. Which accounting systems do Vashi Essentials and target customers use most often?
10. Is Tally installed locally, hosted remotely, or used through another arrangement if it is selected?
11. Is CSV/Excel export sufficient for the first release, or is a specific connector commercially necessary?
12. Expected number of tenants in year one and likely import/report volume?
13. Monthly cloud budget range, including database, storage, backups, monitoring, and support?
14. Preferred hosting region and any data residency or customer-contract requirements?
15. Who will operate production, handle incidents, and manage backups?

## P2 — Product expansion
16. Should a tenant support multiple legal entities/GST registrations later?
17. Multiple warehouses or stock locations?
18. Customer-specific price lists, schemes, discounts, credit limits, and sales-representative commissions?
19. Subscription plans and usage limits?
20. Direct marketplace APIs, GST e-invoicing, e-way bills, or filing integrations and their priority?

## Decision handling
For each answer, update `docs/DECISIONS.md` with the decision, rationale, trade-offs, and approval status. Do not silently turn assumptions into requirements.
