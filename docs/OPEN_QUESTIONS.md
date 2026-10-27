# Open Questions

Resolve these before the affected functionality is used for live financial transactions. Do not block architecture-neutral groundwork unnecessarily.

## P0 — Must resolve before live invoice and stock workflows
1. For Amazon, Flipkart, and Meesho, who generates the customer invoice today? Does it differ by marketplace, order type, or fulfillment model?
2. What sample CSV/Excel reports are available for orders, invoices, returns/refunds, settlement, and fees? Remove personal/customer data before sharing.
3. At what event should inventory be reserved and physically deducted for each sales channel?
4. What should happen when an imported order arrives after it has shipped or after stock has already changed?
5. Should negative stock be forbidden, allowed with warning, or allowed only to privileged users?
6. What is the required invoice-numbering scope: legal entity, GST registration, document type, financial year, and other applicable rules?
7. Are batches/expiry dates required for the first tenants' products?
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

## Tax questions for the CA (open; they gate go-live, not the build)
The full text, interim answers and owners are in `team/product/ca-questions.md` in the project files. The interim answer is what the app does until the CA replies. Each one is a dated refdata row, so a different answer is a reviewed refdata change, not a code change.

| ID | Question | Interim answer | Gates |
|---|---|---|---|
| CA-1 | A new invoice, own credit note or marketplace row dated in a return that is filed and locked (or unlocked to fix the ARN): refuse, report it in the next open return, or amend? Also covers numbering scope and cancellation policy | Invoices and marketplace uploads are refused; own credit notes roll forward to the current open return (D-034) | S4/S6 go-live |
| CA-2 | When the offline tool's per-row tax differs from the invoice's per-line tax by a paisa, which figure goes in GSTR-1? | The invoice's figure; the app warns and the CA pack lists both | go-live |
| CA-3 | Is rounding summed HSN quantity half-up to 2 decimals in the export acceptable? | Yes, in the export only; stored quantities keep 3 decimals | go-live |
| CA-4 | Marketplace B2B sale: place of supply from Bill To or Ship To? | Ship To | R1b go-live |

## Facts not verified yet (each has a written fallback)
Listed in `team/docs/build-readiness.md` §2 and §3 in the project files, with owners. The ones that change the design or the budget:
- A Cognito interface endpoint exists in ap-south-1, and the `Admin*` and access-token Cognito calls work through it. Fallback: a NAT gateway (about USD 31/month more per environment), which is a CEO cost decision (D-029).
- Cognito access tokens carry `origin_jti`, and it stays the same after a refresh. Fallback: `event_id`, then a custom claim.
- The RDS master can be granted `app_owner`, and `btree_gist` and `pg_trgm` are allowed. All three were proved on local PostgreSQL 16 (build-readiness 2.1–2.3); the RDS re-check is in S0b. Fallbacks are in LLD-0 §4.1 and §6.2.
- The presigned POST policy and bucket-default KMS (D-036) behave as designed on staging.
- WeasyPrint runs on Lambda within the cold-start and render-time targets (TD-9). Fallback: ReportLab.

## Values hard-coded until code reads refdata
The rows now exist in `refdata/` (S0b, LLD-0 §6); each place below still holds the
number and moves to `value_on` in its owner's next PR.
| Value | Where | Refdata row |
|---|---|---|
| 24 h session idle limit | `identity.auth_resolve` (S0a c2) | `auth.idle_hours` |
| 30-day session lifetime | `identity/service/signup.py` | `auth.session_max_days` |
| Code TTL, tries and request/check limits | `identity/service/signup.py` | `auth.code_*` (LLD-1 L1-10) |

POST /b already reads `identity.max_owned_businesses` (5, provisional; **Pankaj / PO** to confirm) and the GSTIN and address state codes through `value_on` and `state_name`.

## Business profile (S1-d) items waiting on the GST expert or PO
| Item | What the code does until then | Source needed |
|---|---|---|
| Enrolment number pattern (LLD-1 §15) | Accepts any non-blank value, stored trimmed | A cited pattern for the Notification 34/2023 enrolment number |
| What an enrolment-number business may do in R1 | Stored; `ready_for_documents` will report `gstin` missing (S1-d2) | PO and GST expert |
| Rule 61A window rows `qrmp.option_window.*`, `einvoice.aato_threshold` | The related warnings report "unknown" instead of guessing (S1-d2) | GST expert, with citation |
| Address state different from GSTIN state | A warning, `address_state_mismatch` (L1-12, BRD ON-3); `gstin.md` §4 says refuse | GST expert confirms |
| 14th GSTIN character not `Z` on the business's own GSTIN | A warning, `gstin_not_z` (`gstin.md` §1, §4 item 5) | none |

## Refdata rows to confirm (S0b)
Every row in `refdata/` is `provisional`. Before go-live:
- **PO:** the `auth.*` and `identity.max_owned_businesses` rows (`kind: product`). The
  BRD gives the ON-1 numbers; the sign-in, refresh, step-up and business-limit numbers
  are LLD-1's.
- **GST expert or CA:** `invoice.number.max_length` (CGST Rule 46(b) via GSTZen; the
  rule's own start date); `invoice.number.charset`, which allows lower-case letters
  because the rule says "alphabets" while team/gst/document-fields.md row 3 writes A-Z
  (the expert to confirm which, and whether uniqueness is case-insensitive); `gstr1.offline_tool.max_lines` (10,000 used, the tool's help says
  about 19,000), `filing.locked_return_treatment` (interim `refuse`, CA-1), and the
  state codes. Every code is dated from 2017-07-01; **26** (merged UT, 2020) and **38**
  (Ladakh) began later and their start dates are not verified; 25 and 28 are not loaded.
- The sandbox could not reach gstzen.in or docs.cleartax.in, so those rows'
  `last_checked` is the date the GST expert read them (2026-10-14), not a fresh check.
- Confirming a row means changing its `status` and adding `confirmed_by` (who, and the
  question or message it answers) and `confirmed_on` in the same PR (D-038).

## Job runner follow-ups (S0b, D-039)
- `retention.purge_operational()` (done/failed jobs and sent outbox rows after 14 days, idempotency keys, rate windows; LLD-0 §4.4) is not built yet. It needs a decision on its run record: `platform.audit_log` requires a business or a user, and a retention run has neither.
- A job whose last SQS message is lost while `failed_retryable` stays there; the outbox sweep only resends unsent rows. The DLQ alarm covers exhausted messages, not this. A "stuck jobs" sweep can come with the alarms (TD-24).
- The real-S3 policy checks (limit + 1 byte, other key, after 5 minutes, other KMS key) are QA's staging checks (HLD §6.5); the local store only mirrors them.

## Decision handling
For each answer, update `docs/DECISIONS.md` with the decision, rationale, trade-offs, and approval status. Do not silently turn assumptions into requirements.
