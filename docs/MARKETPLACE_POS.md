# Marketplace place of supply: hold the row when Bill To and Ship To differ (#345)

Status: specification and build for issue #345 (R2 backlog). Decision D-102 in `docs/DECISIONS.md`. The CA must confirm before release (OQ-POS-1).
Sources: CA expert answers v1 and v2, CA-4 (`team/program-lead/ca-answers-from-govt-docs-v2.md`), IGST Act s.10(1)(a) and (b), ss.7 and 8 (as updated to 27 March 2020 in the pack).

## 1. The rule

For a marketplace row that carries both a Bill To and a Ship To state:

| Bill To state and Ship To state | Place of supply | What we do |
|---|---|---|
| Same | That state (s.10(1)(a): where the goods' movement ends) | Read as before |
| Different | Ship To's state if the goods went to the buyer's own other location; the buyer's (Bill To) principal place of business if the buyer had them delivered to a third person (s.10(1)(b)) | **Hold the row** (`bill_ship_diff`); the report does not say which |

We never guess. The CA expert's default (v2) is exactly this: use Ship To when the two agree, hold the row as "needs check" when they differ.

## 2. What data each report has

| Report | Bill To | Ship To | Result |
|---|---|---|---|
| Amazon MTR B2B | `Customer Bill To Gstid`: the first two characters are the Bill To state | `Ship To State` (a name or code) | The rule applies |
| Amazon MTR B2C | none (the end customer is both) | `Ship To State` | Unchanged: no Bill To to compare |
| Flipkart and Meesho | none | one delivery state | Unchanged, same reason |

Flipkart and Meesho files carry no separate Bill To column, so the rule cannot be applied to them today. If a real file shows one, the same check is added to that reader. `Customer Ship To Gstid` is not used: a GSTIN at the Ship To address would say the other location is the buyer's own, but the report does not say the buyer is the same legal person, so it does not settle the question.

## 3. Defaults chosen

1. Bill To state is the buyer GSTIN's state code, compared with the Ship To state by state code (a Ship To name is looked up in the state list, case and spacing ignored).
2. A Ship To state that is not in the state list counts as different: the row is held rather than read as the same state.
3. A B2B row with no Bill To GSTIN, or whose GSTIN prefix is not a state in the list, is not decided by this rule and is read as before (other checks already hold a bad GSTIN-less B2B row).
4. Sales, refunds and credit notes follow the same rule (a refund repeats its sale's states).

## 4. What the user sees and how it is released

- Upload summary: the section says "rows held" and the run's held count names the reason: "Bill-to and ship-to states differ", flagged for a CA check (`needs_ca_check` true). Its effect note: "This row is left out of the return until you choose its place of supply."
- The row offers two actions: **Set aside** and **Pick the state**. It never offers Accept (`accept_allowed` false), because which state applies is a legal reading the user decides, not a data fix.
- Picking the state takes a note, as every decision does, and a state from the refdata list; the file's row is never changed (the choice is stored beside it, as for `unknown_state`). Picking Bill To's state or Ship To's state is the user's judgement, with the note saying why.
- GSTR-1: marketplace reports do not enter the return yet (their treatment is not confirmed, `imports.profile.<id>.treatment_confirmed`). When they do, a held row is left out of the return like every other held row, and a fixed row uses the picked state. Nothing here changes the return today.
- Web: the held-row screen (#369, docs/HELD_ROWS_SCREEN.md) lists these rows, offers Pick the state and Leave this row out, and shows the "needs a CA check" note until OQ-POS-1/2 are answered.

## 5. Technical notes

- New hold reason `bill_ship_diff` (the first draft name did not fit the `varchar(20)` column), a forward-only migration widening the check constraint, and four refdata keys `imports.held.bill_ship_diff.*`.
- `pick_state` is now offered on `unknown_state` and on `bill_ship_diff`; `enter_hsn` stays on `blank_hsn`.
- `reading._context` passes readers a state-name-to-code map (`state_codes`) beside the existing set; a reader that asks for a context (`refdata_keys` set, here empty) gets it.
- Idempotency and duplicates are unchanged: the dedupe key does not depend on the states, so re-uploading a file keeps the held row and any decision on it.

## 6. Acceptance criteria and tests

| # | Criterion | Test |
|---|---|---|
| 1 | B2B row, Bill To 27, Ship To West Bengal: held `bill_ship_diff` | `test_amazon_reader.py` |
| 2 | Same state (by name or by code): not held | `test_amazon_reader.py` |
| 3 | Ship To not in the state list: held | `test_amazon_reader.py` |
| 4 | No Bill To GSTIN, or no state list: read as before; B2C never held for this | `test_amazon_reader.py` |
| 5 | Through the upload: the row is held, labelled, CA-flagged, offers Set aside and Pick the state only, counts show in the run | `test_fixes_postgres.py` |
| 6 | Picking a state needs a note and a state from the list; the file's row is not changed; held count drops | `test_fixes_postgres.py` |
| 7 | The hold reason is allowed by the database (migration) | `test_fixes_postgres.py`, `test_amazon_postgres.py` |

Tenant scoping and permissions use the existing row-resolution route (own business only, existing permission); not changed.

## 7. Open questions

- **OQ-POS-1 (CA):** confirm holding on every Bill To and Ship To difference, and how the user should decide a held row (is the note enough, or should the app ask whether the goods went to a third party?).
- **OQ-POS-2 (CA, test file):** whether a real Flipkart or Meesho file has a Bill To column; the rule is added to that reader if so.
