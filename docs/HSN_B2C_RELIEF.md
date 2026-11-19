# Blank HSN on an invoice line: warn for B2C when the seller is within the limit (#344)

Status: specification and build for issue #344 (R2 backlog). Decision D-101 in `docs/DECISIONS.md`. The CA must confirm the reading before this goes to a paying business (OQ-HSN-1).
Sources: CA expert answers v2, "N-1 and H-1" (`team/program-lead/ca-answers-from-govt-docs-v2.md`) and v4 (refdata check, `hsn.min_digits_*` now `expert_confirmed`); Notification 78/2020-CT.

## 1. The rule

| Buyer | Seller's aggregate turnover, preceding FY | Blank HSN on a line | HSN shorter than the minimum |
|---|---|---|---|
| Registered (has a GSTIN) | any | **Block** (`hsn_missing`) | **Block** (`hsn_too_short`) |
| Unregistered or cash sale | up to Rs 5 crore, band known | **Warn** (`hsn_missing_b2c`) | **Warn** (`hsn_short_b2c`) |
| Unregistered or cash sale | above Rs 5 crore | **Block** | **Block** |
| Unregistered or cash sale | band not set | **Block** (the stricter default; says so) | **Block** |

- The proviso of Notification 78/2020-CT (verified by the CA expert) relieves a seller up to Rs 5 crore of "the number of digits" on invoices to unregistered persons. Whether it also allows no HSN at all is a **judgement** by the CA expert ("optional for small-seller B2C, warn rather than block"), so the CEO's change is built as a warning, never silent.
- The short-HSN row follows from the same proviso (the digit count is what is relieved) and is the part with firmer support. The 8-digit cap and the digit pattern are unchanged.
- The Rs 5 crore limit is never typed in code. It is refdata `hsn.min_digits_aato_threshold`, and the seller's side is the existing turnover band for the **preceding** financial year, compared with `business.turnover_band_threshold` exactly as `hsn_min_digits` does. A band that does not settle "up to Rs 5 crore" (not set, above, or "up to" a higher limit) gives the strict answer.
- "Unregistered" is the buyer having no GSTIN. A cash sale has none.

## 2. Data that exists

- Buyer type: `Buyer.gstin` in the compute input (already there; no new field).
- Seller band: `business.turnover_bands` per FY, read through `business.interface`. New helper `hsn_b2c_relief(tx, on)`: true only when last FY's band is `up_to_threshold` and its limit is not above the HSN limit. Nothing new is stored and no new setting is asked for.
- If last year's band is unknown the rule stays as today (block), and the existing "set last year's turnover band" check already tells the user where to set it.

## 3. What the user sees

- Invoice screen, "Please check" (not "Fix before finalizing"): "This product has no HSN code. This invoice is for a buyer without a GSTIN and your turnover last year was within the small-business limit, so we allow it. Ask your CA to confirm, and add the HSN before you file GSTR-1; the return needs it." The wording says the rule is allowed pending the CA, because OQ-HSN-1 is open, and does not quote the limit. The inline "HSN for <product>" box stays on the line, so adding it is one step. Create stays enabled.
- A short code: "This HSN has fewer than N digits. This invoice is for a buyer without a GSTIN and your turnover last year was within the small-business limit, so we allow it. Ask your CA to confirm, and check the code before you file GSTR-1."
- Product page warning: "Missing HSN: add it before invoicing a buyer with a GSTIN; GSTR-1 needs it too."
- B2B invoice: unchanged ("Add the product's HSN code.", a block).

## 4. What goes into the GSTR-1 output for a blank HSN

Nothing changes in the return. A line finalized with a blank HSN is stored as it was (an empty string, never an invented code). The GSTR-1 build keeps check C-01 (block: "HSN is missing") because Table 12 on the portal needs an HSN from the dropdown (GSTR-1 FAQ Table-12 Q1, Q3), and the relief is about the tax invoice, not the return. The user is told this on the invoice at the moment of the warning. The return is not made easier by this change; it is only that the invoice is no longer refused.

Limitations, disclosed:
- A finalized invoice is never edited, so a blank HSN on a finalized B2C line is not repaired afterwards. Today every invoice is a practice invoice (D-010), practice documents are not in the return, and live numbering is off. Before live numbering is turned on, the CA must say how a line without an HSN is to be reported in Table 12 (OQ-HSN-2). Until then the C-01 block is the safe default.
- Digit count in Table 12 for sellers up to Rs 5 crore (phased by the portal) is a separate question and is not touched.

## 4a. Edge cases

1. Mixed invoice: one line with a blank HSN, buyer unregistered: warning on that line only.
2. Buyer changes from cash to registered on the same draft: the warning becomes a block on the next save (the check runs on every read and save).
3. Archived product, rate missing and other line blocks are unaffected.
4. The invoice date is in a different FY from the band that was set: the band used is the FY before the invoice date's FY, as for `hsn_min_digits`.
5. Band set by "up to" a limit above Rs 5 crore: no relief.
6. Credit notes are not built (R2), so nothing is decided for them here.

## 5. Acceptance criteria and tests

| # | Criterion | Test |
|---|---|---|
| 1 | Blank HSN, unregistered buyer, relief true: warning `hsn_missing_b2c`, no block, `ready` true | `sales/tests/test_compute.py`, `test_finalize_postgres.py` |
| 2 | Cash sale counts as unregistered | `test_compute.py` |
| 3 | Registered buyer: block, relief true | `test_compute.py`, `test_finalize_postgres.py` (422, no document) |
| 4 | Relief false (band not set or above): block | `test_compute.py`, `test_finalize_postgres.py` |
| 5 | Short HSN: warning under relief, block otherwise | `test_compute.py` |
| 6 | Finalize stores an empty HSN, not a made-up code | `test_finalize_postgres.py` |
| 7 | Relief is computed from the band and refdata, never a typed limit | `business/tests/test_thresholds.py` (table) |
| 8 | The web shows the check as a warning, Create enabled, inline HSN box present | `web/tests/unit/invoice.test.tsx` |

Tenant scoping and permissions are unchanged: the rule is evaluated server-side on the caller's own business through the existing draft and finalize routes.

## 6. Open questions

- **OQ-HSN-1 (CA):** confirm that a seller up to Rs 5 crore may issue a tax invoice to an unregistered buyer with no HSN at all, not only with fewer digits. Until confirmed the product is a warning that says the return needs it.
- **OQ-HSN-2 (CA):** how a blank-HSN B2C line is to appear in Table 12, before live numbering is turned on.
