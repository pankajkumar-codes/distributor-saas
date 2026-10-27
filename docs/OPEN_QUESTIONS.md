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
| 30-day refresh cookie `Max-Age` | `identity/api_auth.py` (the session row's own expiry reads `auth.session_max_days`) | `auth.session_max_days` |

Since S1-c3 the session lifetime, the code TTL and tries, and every sign-up, sign-in, TOTP and refresh rate limit are read through `value_on` (`identity/service/limits.py`).

POST /b already reads `identity.max_owned_businesses` (5, provisional; **Pankaj / PO** to confirm) and the GSTIN and address state codes through `value_on` and `state_name`.

## Auth follow-ups (owner: Senior)
- **Mail timing on sign-up and reset (Staff and Staff 2, #48).** `send_after_commit` sends inside the request. So that both branches take the same time, every branch of sign-up and reset now sends exactly one mail: reset mails an unknown email a `reset_no_account` notice, as sign-up mails `already_registered` (EM decision, #48). Long term, when SES lands, send auth mail off the request path (outbox or worker), so a slow send can't show in the reply at all.
- **`reset_no_account` wording (provisional; PO or Designer to confirm).** "Someone asked to reset the password for this address, but there's no account with it. If that was you, you can sign up here; otherwise, ignore this email." It carries no code and no link other than sign-up.

## Business profile (S1-d) items waiting on the GST expert or PO
| Item | What the code does until then | Source needed |
|---|---|---|
| Enrolment number pattern (LLD-1 §15) | Accepts any non-blank value, stored trimmed | A cited pattern for the Notification 34/2023 enrolment number |
| What an enrolment-number business may do in R1 | Stored; `ready_for_documents` will report `gstin` missing (S1-d2) | PO and GST expert |
| Rule 61A window rows `qrmp.option_window.open_offset_months` (-2) and `close_offset_months` (1) | Loaded as provisional tax rows from the GST expert (`team/gst/refdata-lld4.md` §5, CGST rule 61A(1)); `outside_window` is now raised. If the rows are missing the window is unknown (`window_unknown`), never guessed | GST expert re-reads the CBIC page (their open item 6) and confirms; `einvoice.aato_threshold` is in that file's §2 |
| How far ahead a frequency may start, `business.frequency_max_quarters_ahead` (4) | A provisional product row; later starts get 422 `effective_from_too_far` | PO confirms |
| When `portal_stricter_reading` applies (LLD-1 §8.4) | Never raised: LLD-1 names the warning but not its condition | GST expert or CA states the condition |
| L1-13 first frequency row back to the FY start | Allowed for a business's first row only; later rows need the current quarter or later | PO and GST expert confirm |
| Address state different from GSTIN state | A warning, `address_state_mismatch` (L1-12, BRD ON-3); `gstin.md` §4 says refuse | GST expert confirms |
| 14th GSTIN character not `Z` on the business's own GSTIN | A warning, `gstin_not_z` (`gstin.md` §1, §4 item 5) | none |
| Home checklist links for screens not built yet (`/settings/filing`, `/products`, `/customers`, `/settings/team`) | Home returns these paths under `/b/{id}` | Junior and Designer confirm the SPA routes |
| Onboarding labels that would name an amount: the turnover band and the e-invoicing history question (mock v11 and `refdata-lld4.md` say "₹5 crore") | The web names no amount: "Up to the limit for quarterly filing (QRMP)" / "Above that limit", and "…been above the e-invoicing limit in any financial year since 2017-18?". No threshold is in refdata yet | GST expert loads the thresholds with citations; PO and Designer confirm the words, or a refdata route serves the label |
| Onboarding warning words (`window_unknown`, `outside_window`, `last_return_unfiled`, `aato_above_threshold`, `address_state_mismatch`, `pan_shape`, `gstin_not_z`) | Provisional text in `web/src/screens/onboarding/warnings.ts`; each says "check with your CA" and names no date or amount | PO and GST expert confirm |
| Frequency `effective_from` from onboarding | The current quarter's start, in India's time zone; the web never offers the FY start that L1-13 allows a first row | PO confirms, with L1-13 |

## Catalog (S3) items waiting on the GST expert, CA or PO
| Item | What the code does until then | Source needed |
|---|---|---|
| **HSN 8-digit cap** (`hsn.pattern`) | Accepts 4, 6 or 8 digits from the provisional refdata row; the lower bound 4 is cited, the cap and the even lengths are not | GST expert, `team/gst/refdata-rates-uqc.md` open item 6: primary texts of Notification 78/2020-CT and 12/2017-CT and the e-invoice schema's HSN length |
| `gst.rate_values` sets, especially 6% after 22-09-2025 and the end of 28% on 01-02-2026 | Refuses any rate not on the provisional list for its date | CA via the GST expert (open items 1 and 2) |
| HSN minimum digits by turnover (`hsn_min_digits`) | No warning in catalog yet; LLD-4 blocks at finalize once built | business refdata, `refdata-rates-uqc.md` §5(b) |
| Product limits (`catalog.product_code.max_length` 40, `catalog.rate_valid_from_max_days_ahead` 366) | LLD-3's proposals, provisional | PO |
| Rate-change warning window (`catalog.rate_change_warning_days` 30, inclusive) | Warns when the rate in force began at most 30 days before the date | CA (tax-computation §5 [CA]) |
| **A live rate that has left `gst.rate_values` by the invoice date** (for example a rate entered while it was on the list, read for a date after the list dropped it) | Catalog checks a rate against the list for its own `valid_from` only; `product_for_line` returns it with no flag (#52 review) | **LLD-4** decides: a `rate_not_on_list_on_date` flag from catalog read against refdata for the line's date (never a hard-coded date), and whether finalize warns or blocks; the CA says which |

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

## Staging infrastructure follow-ups (S0b, D-040)
- **Raw uploads deleted after 90 days (TD-18) has no lifecycle rule yet.** Keys are `b/<business>/<area>/...`, so no S3 prefix filter selects every upload. Options: (a) put the area first, `<area>/b/<business>/...`, while no data exists yet (one change in `storage.key_for` and `check_key`); (b) tag uploads in the presigned POST and filter on the tag; (c) a worker job that deletes them. Staff 2 recommends (a). Owner: Staff 2, for the EM to agree.
- **App code that this Terraform expects but that isn't built yet:** `app.mailer.handler` and `SqsMailer` (Staff 2's next PR), and the app reading `CODE_HMAC_KEY_PARAM` and `RATE_HMAC_KEY_PARAM` from Parameter Store at start-up (today it reads `CODE_HMAC_KEY` and `RATE_HMAC_KEY` directly). The worker has no `purge_operational` or `retention` task yet, so those schedules stay off.
- **Staging checks only a real AWS account can answer** (QA and Staff 2, at the first staging deploy): whether CloudFront passes `Authorization` and cookies through to the JWT authorizer with the managed AllViewerExceptHostHeader policy; whether the Cognito endpoint exists in ap-south-1 and the admin calls work through it (tech plan §4.5); the exact Cognito admin actions CognitoAuthProvider uses (S1-c4), so the IAM list can be trimmed; `SHOW max_connections`; and the account's Lambda concurrency quota.
- **Pankaj:** the staging decision (no AWS resource exists or is created until he decides), the domain (CloudFront aliases, the ACM certificate, and the SES identity, `mail_domain`), and creating the OIDC deploy role and repository variables listed in `.github/workflows/deploy-staging.yml`.
- **Prod endpoints sit in one AZ**, like staging's. If that AZ fails, the Lambdas lose SQS, Parameter Store and Cognito until it recovers. A second AZ doubles the endpoint line (about USD 28.5 a month more). Decide with Multi-AZ RDS at public launch (TD-22).
- The HTTP API's own `execute-api` URL also answers. It applies the same authorizer and app checks, but it bypasses CloudFront's response headers. Restricting it to CloudFront needs a shared-secret header or a WAF, and is not done.

## Decision handling
For each answer, update `docs/DECISIONS.md` with the decision, rationale, trade-offs, and approval status. Do not silently turn assumptions into requirements.
