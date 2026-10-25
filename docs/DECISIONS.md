# Decision Register

Status values: Proposed, Approved, Rejected, Deferred, Blocking.

| ID | Decision | Current status | Current direction | Approval needed |
|---|---|---|---|---|
| D-001 | Product scope | Approved (BRD v1.1, CEO 2026-10-24) | Small GST-registered businesses: invoicing (Business Hub) and GST filing from their own invoices; marketplace uploads as the R1b add-on. Replaces the earlier "marketplace sellers and distributors" direction | No |
| D-002 | First tenant | Approved direction | Vashi Essentials | No |
| D-003 | Marketplace ingestion | Approved direction | CSV/Excel imports first | Confirm sample reports |
| D-004 | Inventory foundation | Approved direction | Shared, transaction-based ledger | Approve lifecycle details |
| D-005 | GST scope | Approved direction | Calculations, reports, reconciliation first | Validate exact legal cases |
| D-006 | Accounting product | Blocking | Undecided; exports first as proposal | Yes |
| D-007 | Stack | Approved 2026-10-12; detailed by D-027 | Python 3.12 + FastAPI on AWS Lambda (Mangum), RDS PostgreSQL 16, SQLAlchemy 2 + psycopg 3, Terraform | No |
| D-008 | Cloud provider/budget | Approved: provider 2026-10-12; budget by the CEO 2026-10-24 (TD-21, TD-22) | AWS Mumbai (ap-south-1). About USD 49/month per environment; staging only until the pilot, prod at pilot launch. Budget alerts USD 50 staging / USD 60 prod. Single-AZ RDS in the pilot, backups kept 35 days | Multi-AZ at public launch needs a new budget decision |
| D-009 | Marketplace invoice issuer and source of truth | Blocking | Unknown per channel/workflow | Yes |
| D-010 | Invoice-numbering scope and lifecycle | Blocking | Must be professionally validated | Yes |
| D-011 | Inventory reservation/deduction events | Blocking | Define per channel | Yes |
| D-012 | Negative stock policy | Blocking | Undecided | Yes |
| D-013 | Costing method | Proposed | Weighted average | Yes |
| D-014 | Batch/expiry tracking | Blocking for relevant goods | Determine whether needed for the first tenants' products | Yes |
| D-015 | Accounting ledger scope | Proposed | Do not build full ledger initially | Yes |
| D-016 | Direct marketplace APIs | Deferred | Consider after import workflow is validated | Yes |
| D-017 | GST e-invoice/e-way bill/filing integrations | Deferred | Separate future capabilities subject to eligibility and provider validation | Yes |
| D-018 | SaaS subscription billing | Deferred | Not required for first operational MVP | Yes |
| D-019 | Microservices (CLAUDE.md rule 13) | **Superseded 2026-10-24 by D-027** (Pankaj approved TD-1) | Was: five services split on transaction boundaries | No |
| D-020 | Infrastructure as code | Approved 2026-10-12 | Terraform, state in S3 with native locking | No |
| D-023 | Web frontend | Approved by the CEO 2026-10-24 (TD-2) | React + TypeScript single-page app (Vite), served from S3 + CloudFront on the same origin as `/api/*`; it uses only the versioned JSON API that the mobile apps will reuse | No |
| D-026 | Commerce data model (tables, lifecycle, stock ledger, idempotency) | Proposed 2026-10-14; overtaken by the approved LLDs | Kept for history. The current design is LLD-3 (catalog) and LLD-4 (sales, documents); stock is R2 | No |
| D-027 | Deployables | **Approved by Pankaj 2026-10-24 (TD-1)** | One modular-monolith app: API Lambda + worker Lambda + mailer Lambda (outside the VPC, SES only) + migrator. One schema per module, an `interface` package per module, boundaries enforced by import-linter. One app login role (`app_rw`) plus RLS (TD-1b). See docs/ARCHITECTURE.md | No |
| D-028 | Sign-up, codes and sessions | Approved by the CEO 2026-10-24 (TD-4, TD-4a, TD-4b, HLD H-3) | Our API fronts Cognito (Essentials) and issues its own 10-minute, 5-try email codes, stored as HMACs. No Cognito user exists until the code is verified (H-3). TOTP is Cognito's, driven through our API. 5-minute access tokens plus a per-request session check; the refresh token is in an `HttpOnly; Secure; SameSite=Strict` cookie scoped to `/api/v1/auth` | No |
| D-029 | Egress from the VPC | Approved by the CEO 2026-10-24 (TD-5) | No NAT. One Cognito interface endpoint per environment (about USD 9.5/month); email goes through the mailer Lambda outside the VPC. If the endpoint can't serve a needed Cognito call (unverified until S0b), the NAT fallback comes back to the CEO as a cost decision | Only for the fallback |
| D-030 | Invoice numbering mechanism | Approved by the CEO 2026-10-24 (TD-7); numbering **scope** is still D-010 | A counter row per series, locked `FOR UPDATE` inside the finalize transaction, so a rollback never leaves a gap. Sequences are not used | Scope: yes (CA-1) |
| D-031 | Deploy pipeline | Approved in principle (TD-20); nothing deployed | GitHub Actions with OIDC into AWS: staging on merge to `main`, prod on a manual approval. Pankaj creates the OIDC role | Yes, before the first deploy |
| D-032 | Migration names | Approved 2026-10-24 (TD-14, LLD-0 §5) | New migrations use fixed-width `YYYYMMDDHHMM_` prefixes. Existing `NNNN_` files keep their names and run first. A file is never renamed once it has been applied anywhere. CI refuses duplicate prefixes and destructive statements without an approved header | No |
| D-033 | Roles | Approved 2026-10-24 (TD-15, BRD role table) | Four roles: owner, admin, billing, CA. One permission per row of the BRD role table, checked by `require(permission)` on every route. A refusal returns 404 with a logged reason code | No |
| D-034 | Document dated in a locked return (HLD H-2) | **Interim**, CEO default 2026-10-24, until the CA answers CA-1 [GATE: tax treatment] | An invoice, or a marketplace upload with a row, whose covering return is filed and locked is refused (409 `PeriodLocked`; nothing is saved and no number is used). Credit notes roll forward to the current open return (GF-8). An unlocked return counts as locked for new documents. The rule is one dated platform refdata row, not a tenant setting | Yes: CA-1 |
| D-035 | Return assignment and locks (HLD §5.4, TD-8, TD-13) | Approved by the CEO 2026-10-24 | The lock belongs to a return instance (GSTIN, form, period), not a calendar month. Each document stores the return instance it was assigned at finalize, and never changes it. Finalize takes `FOR SHARE` on that instance; mark-filed and unlock take `FOR UPDATE`. Export and lock write insert-only snapshots | No |
| D-036 | Upload path (HLD H-4) | Approved 2026-10-24; to be proved in S0b staging | Presigned POST with an exact key, a size range, a 5-minute expiry and bucket-default SSE-KMS. Raw files are deleted 90 days after upload (TD-18) | No |

Source documents for D-027 to D-036 (project files, not in this repo): tech plan DOC-3 v0.2 (`team/docs/tech-plan.md`), HLD DOC-4 v0.2 (`team/docs/hld.md`) and LLD-0 v0.3 (`team/docs/lld-0.md`). D-021, D-022 and D-024 are proposals in docs/adr/0001-commerce-data-model.md, not decisions.
