# Held rows screen (web, #369)

Short UI spec. The API already exists (D-102, docs/MARKETPLACE_POS.md, docs/IMPORTS.md "Deciding held rows"); this is the page that uses it. Mocks v15 only show a "Fix N held rows" link on a marketplace card and no row screen, so this spec follows the v15 look (cards, chips, banners, the cross-check table) and the web kit; the page is added to the mocks as a follow-up if the owner wants it drawn first.

## Where it lives

- Route `/b/:businessId/uploads/runs/:runId/held`, title "Held rows". Reached from a file on the Upload page: a file whose run has undecided held rows shows "N rows held" and a "Review held rows" link (one per run; a zip makes several).
- Visible to owner, admin and CA (`uploads.view`); billing sees the "no access" page. Only owner and admin can decide (`uploads.create`); a CA sees the rows read-only with "Only an owner or admin can decide these rows."

## What it shows

1. A "Needs a CA check" banner at the top whenever any listed row has `needs_ca_check`: the server's own `ca_check_note` words per row, and a page line that these rules are not yet confirmed by a CA (OQ-POS-1/2), so the choice and note are kept for the CA to review. The page never says what the law is.
2. Held rows grouped by reason (`reason_label`), each group with a count. A row card shows file name and row number, the cells the server returned (invoice number and date, order id, buyer GSTIN, ship-to state, HSN, taxable value, invoice amount: only those present), the reason, the effect note, and the CA flag. All amounts and dates are shown as sent.
3. A decided row (has `resolution`) is shown as decided: the action, the value picked, the note and the time. It cannot be changed (server rule).

## What the user can do (only what `allowed_actions` offers)

- **Pick the state** (`pick_state`): state list (refdata, same list as addresses) and a required note (max 500). Button "Use this state".
- **Enter HSN** (`enter_hsn`): 4, 6 or 8 digits and a required note.
- **Use as the file states it** (`accept`): only where the server offers it (shipped off); note required.
- **Leave this row out** (`set_aside`): note required, and a second "Yes, leave it out" step that repeats the server's effect note, because it cannot be undone.
- **Bulk**: tick rows of the same offered action. "Pick one state for N rows" (state and one note) and "Leave N rows out" (one note, with a second "Yes, leave N rows out" step like a single row, because it cannot be undone). Each row is its own decision call with its own idempotency key, sent one after another; the result says how many were done and lists any the server refused with its words. Rows already decided are not tickable.

## States

- Loading, load error with Try again, 404 (not found), no access.
- Nothing held: "No rows are held. Nothing to decide." with a link back.
- Run no longer staged (confirmed or discarded): rows shown read-only with "This file's preview is closed, so its rows can't be changed."
- Field errors (note missing, state not chosen, server refusals) shown on the field or in an error banner in the server's words. A 409 `run_not_staged` refreshes the page into the read-only state.
- More than one page: "Show more rows".

## Phone layout

Single column, row cards stack, 44px buttons (existing kit rules), the bulk bar sits above the list and wraps; no horizontal scroll.

## Tests

`web/tests/unit/held-rows.test.tsx`: groups and labels, CA note, pick a state with a note (request body and idempotency key), note required, set-aside two-step, bulk pick (one call per row, partial failure listed), decided row read-only, CA role read-only, empty, closed run, load error, link from the upload card.

## Not in this change

No API change (no `schema.d.ts` or `openapi.json` change). Confirming a run is not part of this screen.
