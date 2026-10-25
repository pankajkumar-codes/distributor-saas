# Decision Register

Status values: Proposed, Approved, Rejected, Deferred, Blocking.

| ID | Decision | Current status | Current direction | Approval needed |
|---|---|---|---|---|
| D-001 | Product serves marketplace sellers and distributors | Approved direction | Shared platform, separate workflows | Confirm detailed scope |
| D-002 | First tenant | Approved direction | Vashi Essentials | No |
| D-003 | Marketplace ingestion | Approved direction | CSV/Excel imports first | Confirm sample reports |
| D-004 | Inventory foundation | Approved direction | Shared, transaction-based ledger | Approve lifecycle details |
| D-005 | GST scope | Approved direction | Calculations, reports, reconciliation first | Validate exact legal cases |
| D-006 | Accounting product | Blocking | Undecided; exports first as proposal | Yes |
| D-007 | Stack | Approved 2026-10-12 | Python 3.12 + FastAPI on AWS Lambda, PostgreSQL, Terraform | No |
| D-008 | Cloud provider/budget | Approved 2026-10-12 (provider); budget pending | AWS Mumbai (ap-south-1); budget alerts $30 staging / $60 prod | Confirm budget |
| D-009 | Marketplace invoice issuer and source of truth | Blocking | Unknown per channel/workflow | Yes |
| D-010 | Invoice-numbering scope and lifecycle | Blocking | Must be professionally validated | Yes |
| D-011 | Inventory reservation/deduction events | Blocking | Define per channel | Yes |
| D-012 | Negative stock policy | Blocking | Undecided | Yes |
| D-013 | Costing method | Proposed | Weighted average | Yes |
| D-014 | Batch/expiry tracking | Blocking for relevant goods | Determine whether needed for initial salon products | Yes |
| D-015 | Accounting ledger scope | Proposed | Do not build full ledger initially | Yes |
| D-016 | Direct marketplace APIs | Deferred | Consider after import workflow is validated | Yes |
| D-017 | GST e-invoice/e-way bill/filing integrations | Deferred | Separate future capabilities subject to eligibility and provider validation | Yes |
| D-018 | SaaS subscription billing | Deferred | Not required for first operational MVP | Yes |
| D-019 | Microservices (CLAUDE.md rule 13) | Approved 2026-10-12 by owner | Five services split on transaction boundaries; see docs/ARCHITECTURE.md | No |
| D-020 | Infrastructure as code | Approved 2026-10-12 | Terraform, state in S3 with native locking | No |
| D-026 | Commerce data model (tables, lifecycle, stock ledger, idempotency) | Proposed 2026-10-14 | See docs/adr/0001-commerce-data-model.md; blocking decisions become per-tenant settings | Yes |
