# Invoice creation flow: comparison with Tally and recommended changes

Status: proposed, for the owner's review. Mocks: `docs/mocks/seller-portal-mocks-v14.html` (Home, New invoice, Invoice created). Last updated 2026-11-19.
Scope: the sales invoice screen (BH-4, BH-5), its entry points, the missing-HSN case, and the PDF preview. No numbering or tax rule changes here; invoice numbering stays off until the CA confirms (D-010), so every invoice is a practice invoice.

Note: requirement ids (BH-2, BH-4a to BH-4e, BH-11), L-7 and the screen ids in `r1-invoice-screens` (I1 to I3) refer to the BRD and product files in the project folder, not to files in this repo.

## 1. What the owner reported (2026-11-19)

1. Home has no direct way to Products and Customers.
2. Invoice creation: (a) the only visible button is "Save draft", there is no "Create invoice" button; (b) a product saved with the optional HSN field blank cannot be used on an invoice; (c) "Preview PDF" says "Preparing the preview…" and then a failed network call says the session needs sign in.

## 2. What the code does today (checked in this repo, not run)

| Report | Cause found |
|---|---|
| 2a | `web/src/screens/invoices/InvoicePage.tsx` has a Save draft button in the form and a "Finalize invoice" button in a separate section far below the totals and preview. Finalize stays disabled until the draft is saved and has no checks, and says "Finalizing isn't switched on" (404) while `sales.finalize.live` is off. So the user sees a draft-only flow. |
| 2b | The product form allows a blank HSN, but `sales/compute/core.py` blocks every invoice line whose product has no HSN (`hsn_missing`, "Add the product's HSN code."). The fix is on the product page, so the user leaves the invoice. The two screens disagree: "optional" on one, "required" on the other. |
| 2c | `usePreview.ts` starts a job and polls its status. The web access token lasts 5 minutes (D-092/D-093 session rules); a poll or the PDF link that returns 401 after that surfaces as "session needs sign in" while the page keeps saying "Preparing". Not reproduced here: the EM thread owns the bug fix. This document only fixes what the user should see. |
| 1 | Home links to Filing but not to Products, Customers or Invoices. |

## 3. How Tally and others do it

Sources are web summaries only; I did not run TallyPrime. Confidence is marked. "Unverified" means do not rely on it.

| Topic | Tally Prime | Confidence |
|---|---|---|
| Open the sales voucher | F8, then Ctrl+A to accept and post. Item invoice vs accounting invoice via Ctrl+H. help.tallysolutions.com/?p=104286 | high |
| Draft | No separate draft status found. Saving posts the voucher. An "optional voucher" may act like a draft (unverified). | low |
| Print / share | Ctrl+P prints from the voucher. WhatsApp send from release 4.0, can send automatically after save. help.tallysolutions.com (WhatsApp for Business page) | high / med |
| Numbering | Automatic, automatic with manual override, manual, multi-user auto, none; multiple series from 3.0. help.tallysolutions.com/use-voucher-numbering-methods/ | high |
| Missing HSN | Shows as an exception in GSTR-1 ("Uncertain Transactions"), fixed in the stock item or the voucher. Whether the save is blocked is not confirmed. help.tallysolutions.com/resolve-hsn-sac-gstr1/ | med / low |
| Negative stock | Warns by default, voucher type option "Warn on negative stock balance". Source is the Tally.ERP 9 help, so for TallyPrime this is by analogy. | med |
| New party or item while billing | Alt+C creates it without leaving the voucher. | med |
| Zoho Invoice | "Save as Draft" and "Save and Send" are the primary buttons; the arrow gives Save and Share, Save and Print, Send later. zoho.com/invoice/help/invoice/new-invoice.html | med |
| Vyapar | Save the invoice, then share (WhatsApp, email) or print. Exact labels unverified. | low |
| Busy, B2B/B2C prompts, preview failure behaviour | Not researched or not confirmed. | unverified |

## 4. Gaps and recommendations

| # | Gap against what small shops expect | Recommendation | Requirement |
|---|---|---|---|
| G1 | Tally posts with one accept; we make the user find Finalize below the fold and call the draft button the main action. | **"Create invoice" is the primary button** next to the totals (sticky on phone). While numbering is off it reads "Create practice invoice". It saves the form and finalizes in one step. "Save draft" becomes the secondary button. One request, retry safe with one idempotency key. | BH-4a |
| G2 | Tally shows blocking data problems where you are, and lets you fix them in place (Alt+C). We send the user to the product page. | **Fix on the line.** A line whose product has no HSN shows an inline HSN box and "Save HSN", which writes the code to the product (same validation as the product form). The Create button stays off until it is fixed and says why. We never choose a code. | BH-4b |
| G3 | The product form says "optional" but invoices need it. | Product form wording: "Optional while you add products. Needed before this product can go on a tax invoice." Whether the HSN requirement and digit count apply to a given business depends on the turnover band; the server already applies the rule from refdata. The CA confirms the legal position (open question OQ-INV-1). | BH-2 |
| G4 | Tally has Alt+C for new masters. | Keep the existing inline "new customer" and "new product" mini-forms on the invoice screen (r1-invoice-screens I1, I3); the new product form asks for HSN but allows blank, with the line fix above. | BH-4c |
| G5 | Preview never finishes and then fails with a sign-in message. | Preview states: idle, preparing, ready, slow (over 30 seconds, offers retry), session ended. On a session end the page keeps the draft, shows "Sign in again", returns to the same invoice and restarts the preview. A preview never blocks Create. | BH-4d |
| G6 | Home hides Products and Customers. | Home shows New invoice (primary), Products, Customers, Invoices as first-level links, and the top bar carries the same destinations. | BH-4e / BH-11 |
| G7 | Tally warns on negative stock, never blocks. | Unchanged: we warn only (D-081, D-082). | none |
| G8 | WhatsApp or email send, as in Tally 4.0 and Zoho. | After Create: Download PDF, Copy link. WhatsApp and email sending stay later (L-7), not in this change. | later |

## 5. Recommended flow (see mocks v14)

1. Home: tap **New invoice** (or Continue draft).
2. One screen: customer (search, cash sale, or new inline), items (search, qty, rate, new product inline), live totals from the server, preview.
3. A missing HSN shows an inline box on that line. Save it, the warning clears.
4. Tap **Create practice invoice**. Confirmation shows the PR- number, "not for your customer", Download PDF, Copy link, and "New invoice for the same customer".
5. "Save draft" remains for work in progress.

## 6. Acceptance criteria

1. On Home, Products, Customers and Invoices open in one click, and New invoice is visible without scrolling at 1366x768 and at 360 px.
2. On the invoice screen the primary button is Create invoice (Create practice invoice while numbering is off); Save draft is secondary. Create works from an unsaved form in one request, and a double press creates one invoice.
3. A product with no HSN can be added to an invoice. Its line shows the HSN box; saving a valid HSN updates the product, clears the check and enables Create. An invalid HSN shows the existing "use digits only" error. Server rules are unchanged: with the HSN blank, the server still refuses the finalize.
4. Preview shows each of the five states in the mock. When the token has expired the page refreshes it or shows "Sign in again" and returns to the same draft with nothing lost. "Preparing" never shows for longer than 30 seconds without the slow-state message.
5. Stock never blocks Create.
6. Tenant scoping, role checks (`canCreateDocuments`) and idempotency are tested for the combined create endpoint, and the HSN write on the product uses the existing product permission.

## 7. Open questions

- OQ-INV-1 (CA): is an HSN mandatory on every sales invoice for this business, and with how many digits? Until answered the server rule stays as built, except that D-101 (`docs/HSN_B2C_RELIEF.md`) turns a blank HSN into a warning for a buyer without a GSTIN when the seller is known to be up to Rs 5 crore.
- OQ-INV-2 (owner): should "Create invoice" also be allowed to skip the confirmation sheet in r1-invoice-screens I2? The mock goes straight to the result because invoices are practice-only.
- Tally behaviours marked low or unverified above were not confirmed from Tally itself.

## 8. Hand-off

Code changes (primary button, inline HSN, preview session handling, Home links) are for the EM thread. This pull request changes documents and mocks only.
