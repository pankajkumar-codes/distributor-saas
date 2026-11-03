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
| CA-5 | Tax-inclusive (MRP-style) prices: may an invoice back-calculate taxable value from a tax-inclusive price, and by which method (`team/gst/tax-computation.md` §6, G14, G15)? | Not offered: R1 computes tax-exclusive only, and G14/G15 are out of the golden tests (EM, 2026-11-03; LLD-4 §15) | a tenant asking for inclusive pricing |

## Facts not verified yet (each has a written fallback)
Listed in `team/docs/build-readiness.md` §2 and §3 in the project files, with owners. The ones that change the design or the budget:
- A Cognito interface endpoint exists in ap-south-1, and the `Admin*` and access-token Cognito calls work through it. Fallback: a NAT gateway (about USD 31/month more per environment), which is a CEO cost decision (D-029).
- Cognito access tokens carry `origin_jti`, and it stays the same after a refresh. Fallback: `event_id`, then a custom claim.
- The RDS master can be granted `app_owner`, and `btree_gist` and `pg_trgm` are allowed. All three were proved on local PostgreSQL 16 (build-readiness 2.1–2.3); the RDS re-check is in S0b. Fallbacks are in LLD-0 §4.1 and §6.2.
- The presigned POST policy and bucket-default KMS (D-036) behave as designed on staging.
- WeasyPrint runs on Lambda within the cold-start and render-time targets (TD-9). Measured locally on x86_64 under the Lambda image (spike, `team/staff2/td9-weasyprint-spike.md`): about 1.3 s cold and 0.3 s warm at 1024 MB. **Still open: the arm64 re-measure on the first staging deploy** (invoke the renderer with `{"task": "selftest"}`; read Init Duration, Duration and Max Memory Used). Fallback: ReportLab.

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
- **Change password after the provider accepted it (done in S1-c4c1).** If tx B fails after `ChangePassword` succeeded, the request logs at ERROR, still calls the provider's global sign-out so the old tokens die, and returns 500. The session rows stay until their idle limit.
- **Two nits (decided in S1-c4c1).** `/me/password` refuses a new password equal to the current one (422 `password_unchanged`). `PATCH /me` writes **no** audit row for a name change: the name is display text, it grants nothing, and LLD-1 §12 lists no action for it. Revisit if the PO wants it in the activity view.
- **TOTP enrolment (S1-c4b).** `/me/totp/confirm` has no app-level rate limit: it needs a live session, and Cognito limits `VerifySoftwareToken` itself (to verify in S0b). `users.totp_enabled_at` only mirrors the provider for `GET /me`; if the provider call succeeds and the transaction then fails, the flag is stale until the next change. Sign-in always asks the provider.
- **Provider error mapping (done: S1-c4c1 for the fake, S1-c4c2 for `identity/cognito.py`).** `AuthRefused` codes: `not_authorized` (wrong current password) is 422 `current_password_wrong`; `token_invalid` (an access token the provider no longer accepts) is 401; `password_rejected` is 422 `password_weak`; `rate_limited` is 429 with `Retry-After: 60` (provisional); anything else is a 500, never a guess. The adapter maps `NotAuthorizedException` by its message (wrong password or token expired or revoked), `InvalidPasswordException`, and `LimitExceededException` / `TooManyRequestsException`.
- **CognitoAuthProvider is tested only against botocore's Stubber (S1-c4c2).** The Stubber checks each call's parameters against Cognito's API model, but no real pool has been called. Before go-live, S0b's LLD-1 §7.4 checks must pass on staging: C1 (`origin_jti`), C2 and C7 (the admin and access-token calls through the interface endpoint), C4 (`AdminDeleteSoftwareToken`, which is in the API model), C5 and C6. The NotAuthorizedException message text that tells an expired token from a wrong password ("Access Token ...") is also to be confirmed there. Also confirm there that the JWKS fetch (`{issuer}/.well-known/jwks.json`) works from the API Lambda over the cognito-idp PrivateLink endpoint (Staff 2, #77). For C4, call `remove_totp` twice on the same user and confirm the second call succeeds; if Cognito refuses it (TOTP already off, no software token), map that error code to success in the adapter, because S2-b's recovery retries call it again (EM, #77).
- **`limits.read` opens one short read-only transaction per request (Staff 2, #48 nit; deferred).** Fine with the refdata reader's snapshot cache. If background refresh polls show up in RDS connection counts, serve the limits from the cached snapshot without a transaction.
- **`/me/password` is not on `me_uow` (S1-c4).** `rate.hit` must commit before the first transaction, so the route resolves the caller in its own short transaction, the same check `me_uow` runs (`service/account.py`).
- **`PATCH /me {name}` has no product rule yet.** The code trims it, stores a blank as no name, and refuses more than 100 characters or any character that is not printable, such as a line break or a direction override (422). **PO** to confirm the limit and whether a name is required.

## Support (S2) follow-ups (owner: Staff)

- **TOTP recovery at the provider (S2-b, fake only).** Confirm runs `remove_totp(sub)` before the database step, so a retry after a database failure calls it a second time. The Cognito adapter (S1-c4c2) must make `AdminSetUserMFAPreference` off plus `AdminDeleteSoftwareToken` harmless when TOTP is already off. `AdminDeleteSoftwareToken` is still an unverified name (LLD-1 C4).
- **Recovery limits (provisional refdata, RM42-4).** `support.totp_recovery_per_support_user_per_hour` = 10 and `support.totp_recovery_per_email_per_day` = 3. PO to confirm.
- **Support grants (S2-c, S2-d).** The owner's `POST`, `POST …/revoke` and `GET /b/{id}/support-grants` (LLD-2 §6.1) and support's own `GET /support/grants` (§6.2) are built. The length is refdata `support.grant_hours` = 24 (provisional, PO), read on the database's date in India, the same clock as the grant's start and expiry. A grant that a newer one replaced shows as `revoked` with the owner who gave the new one as `ended_by`; LLD-2 names only `expired | revoked`, so there is no separate "replaced" state: the replaced grant gets its own `support.revoke` audit row with reason `replaced`, and the new grant's `support.grant` row names it in `data.replaced`. Revoking a grant that already ended is 409 `grant_ended`. `GET /support/grants` lists live grants on businesses that aren't closed (a closing business stays open to support, as `auth_resolve` allows) through the definer `identity.auth_support_grants()`, with the business's account name (`identity.businesses.name`), not the legal or trade name from the business profile; PO to confirm which name the support banner shows. The list is team-wide (every support user with TOTP on sees every live grant) and listing writes no audit row, by design: it shows only what the owner chose to share, and every page support opens is a `support.view` row (LLD-2 §6.2, Staff 2 on #92). Web (S2-e): Settings › Support access gives and ends access for owners and shows it read-only to admins. The button names no hours, because the length is refdata; the card shows the end time the server sent. The mock's "How long" choice and "See what support viewed" link are left out until a second length exists and the audit-log screen is built. Designer and PO to confirm. Web (S2-f): support staff land on `/support` (sign-in and `GET /me/businesses` carry `is_support`), a list of the businesses they may open with when access ends; every screen of such a business shows a fixed "Support view · read-only · ends <time>" banner. Both lists refresh when a grant ends. The owner's hint now says support "can see your data but can't change anything or file returns" (EM on #95: opening a PDF is a view).
- **Support users and memberships (AC2-14, done in S2-b).** Triggers refuse an active membership for a support user and refuse making a member into support, so a support user always reaches a business through a grant (TOTP required, read-only, every view audited), never as a member. Existing data: none in any environment yet.

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
| Home checklist links for screens not built yet (`/settings/company`, `/settings/filing`, `/onboarding/marketplaces`, `/settings/team`; products and customers are built) | Home returns these paths under `/b/{id}`. The web links only to a screen it has (`web/src/screens/home/links.ts`, LLD-6 RM46-J7) and shows "Coming soon" for the rest; each new screen adds its path there | Designer confirms the "Coming soon" state |
| Home checklist count when the server sends a key the web has no label for | The rows leave that item out, but "N of M done" is the server's count, so it can disagree with the rows shown until the web adds the label | Designer and PO: count only shown rows, or keep the server's count |
| Products list: a taxable product with no rate on today's date (only a future-dated rate) | Its GST rate column shows "—" with no chip; the invoice screen will refuse it on that date (`no_rate_on_date`, LLD-3 §3) | Designer: is a "No rate today" chip wanted on M8 |
| Product form: the same field changed by the user and by someone else (after the "someone changed this product" banner) | The user's value wins: it stays in the field with "Now saved as: X" beside it, and is sent on the next save. A field only the other person changed takes their value, with "Someone else changed this." | Designer confirms |
| Rate history copy (M8): "This product's GST rate changed recently. Check invoices dated around the change.", "Confirmed with CA (your note)" shown as "Yes (note)", and "Until" as the day before the next rate starts | Provisional, in `web/src/screens/products/RateHistory.tsx`; the recency window is the server's refdata `catalog.rate_change_warning_days`, so the web names no number of days | Designer and PO |
| M9 Customers has no artboard in mocks v11 (`team/design/mock-coverage.md`, BH-3) | The web follows M8: list with Active/Archived/All tabs, "Search by name or GSTIN" (the server matches a name fragment or a GSTIN prefix), columns Customer, GSTIN ("Unregistered" when none), Billing state, Credit days; chips are the server's warning messages | Designer draws M9 (list, form, GSTIN error, missing state, empty state) |
| Home checklist labels | Provisional, from M3, in `web/src/screens/home/HomePage.tsx`: Business details, Filing frequency, Marketplaces you sell on, Add your first product, Add your first customer, Invite your CA or a teammate | Designer and PO confirm (with the six items, LLD-1 §10) |
| Onboarding labels that would name an amount: the turnover band and the e-invoicing history question (mock v11 and `refdata-lld4.md` say "₹5 crore") | The web names no amount: "Up to the limit for quarterly filing (QRMP)" / "Above that limit", and "…been above the e-invoicing limit in any financial year since 2017-18?". No threshold is in refdata yet | GST expert loads the thresholds with citations; PO and Designer confirm the words, or a refdata route serves the label |
| What the turnover band is measured against: `business.turnover_band_threshold` (₹5 crore, rule 61A QRMP limit) | A provisional tax row (the figure not re-read on the CBIC page). `business.hsn_min_digits` and `einvoice_status` use a band only when it settles their rule: "up to" a band limit at or below the rule's threshold, or "above" one at or above it; otherwise the stricter answer (6 digits; `unsure` for e-invoicing when a band is above a lower limit). Today all three thresholds are ₹5 crore. The invoice's "tell us last year's band" block (`business.hsn_band_missing`) uses the same condition, so it is shown only when an "up to" band could lower the count | GST expert confirms the row and its citation (LLD-1 [S4P-1]); listed as a validation item in `team/product/ca-questions.md` |
| HSN minimum digits by turnover: which FY's band (LLD-1 §8.3 says "the FY of `on`") | Uses the band of the FY **before** `on`'s FY, as the cited rule says (AATO in the preceding FY, `refdata-rates-uqc.md` §5(b)); no band gives 6 digits. No rows before 01-04-2021, so an earlier date raises `RefdataMissing` | LLD-1 erratum [S4P-1] (done, Lead); GST expert for the pre-2021 rule if ever needed |
| HSN on B2C invoices at AATO up to ₹5 crore | Notification 78/2020-CT (as cited in `refdata-rates-uqc.md` §5(b)) makes the 4-digit HSN mandatory on B2B invoices and optional on B2C ones at that turnover, but LLD-4 §3.4 blocks a missing or short HSN on every invoice, B2C included. The code follows LLD-4 (the stricter rule) | PO product choice: keep blocking on B2C, or relax to a warning for B2C below the band (raised by Staff on #85) |
| Onboarding warning words (`window_unknown`, `outside_window`, `last_return_unfiled`, `aato_above_threshold`, `address_state_mismatch`, `pan_shape`, `gstin_not_z`) | Provisional text in `web/src/screens/onboarding/warnings.ts`; each says "check with your CA" and names no date or amount | PO and GST expert confirm |
| Frequency `effective_from` from onboarding | The current quarter's start, in India's time zone; the web never offers the FY start that L1-13 allows a first row | PO confirms, with L1-13 |

## Catalog (S3) items waiting on the GST expert, CA or PO
| Item | What the code does until then | Source needed |
|---|---|---|
| **HSN 8-digit cap** (`hsn.pattern`) | Accepts 4, 6 or 8 digits from the provisional refdata row; the lower bound 4 is cited, the cap and the even lengths are not | GST expert, `team/gst/refdata-rates-uqc.md` open item 6: primary texts of Notification 78/2020-CT and 12/2017-CT and the e-invoice schema's HSN length |
| `gst.rate_values` sets, especially 6% after 22-09-2025 and the end of 28% on 01-02-2026 | Refuses any rate not on the provisional list for its date | CA via the GST expert (open items 1 and 2) |
| HSN minimum digits by turnover (`hsn_min_digits`) | No warning in catalog yet; LLD-4 blocks at finalize once built | business refdata, `refdata-rates-uqc.md` §5(b) |
| Product limits (`catalog.product_code.max_length` 40, `catalog.rate_valid_from_max_days_ahead` 366) | LLD-3's proposals, provisional | PO |
| Customer limits (`customer.credit_days_max` 365, `address.pin_pattern` six digits not starting with 0) | LLD-3's proposals, provisional | PO |
| Product import limits (`catalog.import.max_bytes` 2 MB, `catalog.import.max_rows` 5,000, `catalog.import.keep_days` 90) | LLD-3's proposals, provisional | PO |
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
- `retention.purge_operational()` is built (D-041) and ships **disabled**. Still open:
  - **Periods (PO):** every row in `refdata/values/retention.yaml` is a provisional LLD design period, not a statutory one: jobs and sent outbox 14 days, idempotency keys 24 h, pending sign-ups and codes 24 h, sessions and closed invitations 30 days.
  - **Rate windows:** LLD-0 says "old windows" with no period, so there is no `retention.rate_window_keep_hours` row and the table is kept. The longest window in use is one hour; the PO picks a period.
  - **Switching it on:** a refdata change after a dry run on staging, which waits for the staging decision. The retention Lambda and its two schedules exist in Terraform, both schedules disabled.
  - **Sessions past the 24 h idle limit** but before absolute expiry are kept until absolute expiry + 30 days. That is conservative; LLD-1 §12 names only revocation and absolute expiry.
- A job whose last SQS message is lost while `failed_retryable` stays there; the outbox sweep only resends unsent rows. The DLQ alarm covers exhausted messages, not this. A "stuck jobs" sweep can come with the alarms (TD-24).
- The real-S3 policy checks (limit + 1 byte, other key, after 5 minutes, other KMS key) are QA's staging checks (HLD §6.5); the local store only mirrors them.

## PDF renderer follow-ups (D-042)
- **arm64 re-measure** on the first staging deploy (above). CI only builds and checks the arm64 zip; it renders on x86_64.
- **S4 render pipeline: done for the draft preview** (D-042). It has the worker's put and send, and the renderer's read, write and KMS grants (no delete: inputs expire), a deny-all `url_fetcher`, escaped fields, and the planted-URL and no-partial-PDF tests. Still open:
  - **Tax on the preview.** Wire `compute(load_inputs(...))` into `sales.preview.build` once `load_inputs` merges (it needs #85). The template already prints line tax, totals and amount in words when they are in the input.
  - **Finalized invoices.** A template titled "Tax Invoice", with the number and the snapshot, comes with finalize, behind the **[CA] template approval** (T-305 gate, `team/gst/document-fields.md`).
  - **Bengali script.** Only Noto Sans and Noto Sans Devanagari are bundled, so a Bengali buyer or product name prints as empty boxes. Add Noto Sans Bengali (static, OFL) to `fonts.lock` before West Bengal tenants use PDFs. Its size is to be measured against the zip budget.
  - **Line cap.** 1000 lines took 12 s locally. Drafts are capped at 200 lines (`drafts.MAX_LINES`), within the 60 s timeout.
  - **A failed render** shows as "rendering" forever on the status route, because the renderer has no way to mark the job. The DLQ alarm catches it. A render-failed status needs the renderer to report back, a later choice.
  - **Styling** is the Junior's (`renderer/renderer/template.py`).
- **Renderer input (decided and built, D-042):** `render-input` is a storage area with a 1-day expiry, written by the worker and read once by the renderer. The logo should travel inside the input (a data URL is refused by the fetcher, so it needs the template to embed it from the input) rather than as a `branding/` read. Decide that with the logo feature.
- **Idle SQS polling.** Lambda polls a trigger queue even when it is empty, so the render queue adds SQS requests every month. With the jobs and mail queues it may pass SQS's 1 million free requests (about USD 0.40 per further million). Check on the first staging bill.
- **Devanagari proof:** the self-test shows the glyphs are shaped and that only Noto fonts are embedded; an Indian-language reader should check a real invoice before launch.
- **Other scripts** (for example Bengali for West Bengal sellers) each add one Noto family, about 0.2–0.5 MB per weight. That is a product decision.

## Staging infrastructure follow-ups (S0b, D-040)
- The `purge` (hourly) and `retention` (daily, 02:30 IST) schedules target the `retention` Lambda (L6-5) and stay **disabled** until the staging decision; each rule is also off in refdata. Raw uploads now expire 90 days after upload through the `uploads/` lifecycle rule (TD-18; `upload_retention_days`).
- **Mail wording** (`platform_common/mail_templates.py`) is a first draft with no product name and no code lifetime in it. The PO should review it before launch.
- **Backlog (infra):** a least-privilege policy for the deploy role. Today it needs broad rights to create the stack (docs/DEPLOYMENT.md).
- **Staging checks only a real AWS account can answer** (QA and Staff 2, at the first staging deploy): whether CloudFront passes `Authorization` and cookies through to the JWT authorizer with the managed AllViewerExceptHostHeader policy; whether the Cognito endpoint exists in ap-south-1 and the admin calls work through it (tech plan §4.5); the exact Cognito admin actions CognitoAuthProvider uses (S1-c4), so the IAM list can be trimmed; `SHOW max_connections`; and the account's Lambda concurrency quota.
- **Pankaj:** the staging decision (no AWS resource exists or is created until he decides), the domain (CloudFront aliases, the ACM certificate, and the SES identity, `mail_domain`), and creating the OIDC deploy role and repository variables listed in `.github/workflows/deploy-staging.yml`.
- **Prod endpoints sit in one AZ**, like staging's. If that AZ fails, the Lambdas lose SQS, Parameter Store and Cognito until it recovers. A second AZ doubles the endpoint line (about USD 28.5 a month more). Decide with Multi-AZ RDS at public launch (TD-22).
- The HTTP API's own `execute-api` URL also answers. It applies the same authorizer and app checks, but it bypasses CloudFront's response headers. Restricting it to CloudFront needs a shared-secret header or a WAF, and is not done.

## Decision handling
For each answer, update `docs/DECISIONS.md` with the decision, rationale, trade-offs, and approval status. Do not silently turn assumptions into requirements.
