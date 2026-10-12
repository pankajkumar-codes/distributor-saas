# Architecture Options and Decision Framework

No stack is approved by this document. Claude must present a current, evidence-based comparison and request approval before final selection.

## Product shape
Recommended direction: a modular monolith with clear domain boundaries, unless repository inspection or measured requirements justify another approach. This is a proposal, not an approval.

Candidate modules:
1. Identity, tenant, membership, permissions
2. Organization and tax configuration
3. Catalog and external SKU mappings
4. Procurement and supplier management
5. Inventory ledger and reservations
6. Wholesale orders and invoices
7. Marketplace import and reconciliation
8. Payments and settlements
9. Reporting and exports
10. Accounting integration boundary
11. Audit and operations

## Stack decision criteria
Compare at least two viable options for each major decision:
- Language and frontend framework
- Backend framework/runtime
- Relational database
- ORM/query layer and migrations
- Authentication/session approach
- PDF generation and file storage
- Background job/import processing
- Testing tools
- Hosting and managed database
- Monitoring/logging/error reporting
- CI/CD and secrets management

For each option include:
- Developer speed and fit with Claude Code
- Security and ecosystem maturity
- Financial transaction support
- Migration and backup quality
- Operational burden
- Vendor lock-in and portability
- Indicative recurring cost at small scale
- Upgrade path
- Relevant risks and mitigations

## Constraints
- Start with a conventional relational database suitable for transactional consistency.
- Prefer a modular monolith for the first release unless a clear need argues otherwise.
- Avoid microservices and Kubernetes by default.
- Do not choose services based only on popularity or generated recommendations.
- Do not provision paid resources before approval.
- Use environment-based configuration and a secrets manager/host environment secret facility.
- Keep marketplace/accounting provider adapters behind interfaces.
- Background jobs must be retry-safe and observable.
- Financial operations require database transactions and uniqueness constraints.

## Cloud comparison
Compare suitable managed deployment options using current prices and regional availability where possible. State assumptions about region, compute, database, storage, backups, egress, monitoring, and expected use. Distinguish free trial credits from recurring production costs.

## Decision record format
For each significant decision record:
- ID and date
- Context/problem
- Options considered
- Recommendation
- Trade-offs and costs
- Security/operational implications
- Approval status and approver
- Revisit trigger
