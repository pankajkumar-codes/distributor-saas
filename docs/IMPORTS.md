# Marketplace import parsing

Backlog: E4-1 (import engine), generic part. Code: `app/src/app/modules/imports/parsing`.

`parsing` turns an uploaded report into a **preview**: every source row with the raw
values of its mapped, non-personal columns, its normalized values when valid, its
errors, and a de-duplication key.
`app/src/app/modules/imports/staging.py` stores that preview as an import run (see "Storage" below). Neither
touches S3, stock or money. The upload/confirm API (in a business unit of work, LLD-0) and handing confirmed rows to commerce (T-202) are later slices.

## Flow

1. `read_table(bytes, filename, sheet=None)` reads `.csv` (UTF-8, BOM allowed) or
   `.xlsx` into a grid of strings and computes the SHA-256 of the bytes. A renamed copy
   has the same checksum, so the next slice can detect "already imported".
2. `parse(table, profile)` finds the header row, maps columns through the profile,
   validates and normalizes each row, and flags duplicates.
3. `ParseResult.summary()` gives counts per status for the preview screen.

## Mapping profiles

A `MappingProfile` (marketplace, report type, version) lists the fields we want, the
header spellings that may carry each one, its kind (`text`, `integer`, `decimal`,
`date`, `datetime`), whether it is required, the explicit date formats, and which
fields form the de-duplication key. Profiles are plain data (`MappingProfile.from_dict`)
so they can later be stored per business.

**No marketplace profiles exist yet.** They are written by the channel-adapter owner
from real, redacted sample reports (OPEN_QUESTIONS.md question 2) and set
`verified=True` only after being checked against those samples. Every result carries
`profile_verified` so the UI can warn on an unverified layout.

## Rules the parser enforces

| Situation | Result |
|---|---|
| Unsupported type, legacy `.xls`, non-UTF-8 CSV, corrupt workbook | Whole file rejected with a reason; nothing guessed |
| File over 20 MB, over 200,000 rows or 300 columns, xlsx inflating over 200 MB | Whole file rejected |
| Workbook with several sheets and none chosen | Rejected, listing the sheet names |
| Title/date lines above the header | Header searched in the first `header_search_rows` rows |
| Required column missing | Rejected, naming the missing fields |
| Two columns match one field | Rejected as ambiguous |
| Bad value in a row | That row is `invalid` with per-field errors; other rows unaffected |
| Amounts | `Decimal` only. Accepts `₹`/`Rs.`/`INR` prefix and Indian or western comma grouping. Rejects exponents, parentheses, `NaN`, odd grouping |
| Excel number cells | Converted to their shortest exact decimal text (`199.99`), never scientific notation |
| Dates | Only the profile's formats. A value that reads as two different dates under those formats is `ambiguous_date`, not guessed |
| Formula cells, or text starting with `=`, `@`, `+`, `-`, tab or CR (after folding look-alikes such as full-width `＝` and dropping invisible characters) | Row `invalid` (`formula`); formulas are never evaluated. Number fields still accept a leading sign |
| Digits from other scripts (e.g. `١٢٣`) in number fields | Row `invalid`; only ASCII digits are numbers |
| Blank rows | Skipped and counted |
| Same key, same values | Later copies `duplicate` |
| Same key, different values | All copies `conflict`, for review |

Amounts are compared canonically, so `10` and `10.00` are the same value for
de-duplication. Each valid row also carries a `content_hash` of its normalized values,
so a later re-import can tell "same row again" from "same external ID, changed".

## Storage (`imports` schema)

Migration: `app/src/app/modules/imports/migrations/202610261000_imports_staging.sql`.

- `import_runs`: one per uploaded file and report type: business, marketplace, report
  type, profile id and whether it is verified, filename, checksum, header row, summary
  (counts, and the names of the columns not stored), uploader's user id and time,
  status `staged` → `confirmed` or `discarded`. `app_rw` may update only `status`,
  `confirmed_by` and `confirmed_at`.
- `import_rows`: one per non-blank source row: row number, status, raw values of the
  mapped non-personal columns, normalized values (amounts as strings), errors, key
  digest, content hash, all `jsonb`. Insert-only: `app_rw` has no UPDATE or DELETE.
- **Personal and unmapped columns are never stored** (LLD-7 L7-2, AC7-12). A profile
  field marked `personal` (buyer name, address, phone, email) is matched so the header
  is found, then dropped from both raw and normalized values; columns the profile
  doesn't map, and cells beyond the header, are dropped too. Only their header names
  are kept, in the run summary, so the preview can say what was not stored. A key
  field can't be personal.
- Staging the same bytes again for the same business and report type returns the existing
  run, including when two uploads race (a partial unique index decides). A discarded
  run frees the file to be staged again.
- Each valid row is compared with the latest **confirmed** row carrying the same key for
  that business, marketplace and report type: `new`, `already_imported` (same values) or
  `changed` (for example a status moved from shipped to delivered). Staged but
  unconfirmed runs are not compared against.
- Row-level security (enabled and forced) keys off `app.tenant_id`, which the unit of
  work sets to the business id; with none set, `app_rw` sees and writes nothing, and a
  support session (`app.support_grant_id` set) gets no tenant access. Under a live grant
  (`platform.support_grant_active`), the `support_read` policy lets it read that
  business's runs and rows, never write them. `app_ro` reads only.
  Rows can only reference a run of the same business (composite key).

## Limitations

- `datetime` fields are kept as written, without a timezone. Whether a report's times
  are IST or UTC must be recorded per profile once samples arrive.
- Raw file storage and retention are handled when files are persisted (S8 `uploads`),
  not here.
- `.xlsx` files are read in openpyxl's read-only mode after `reset_dimensions()`, because
  some marketplace workbooks store no or a wrong sheet dimension and would otherwise
  read as the header row only.


## Uploads (R1-M3, `imports/uploads.py`, `api.py`, `jobs.py`, `readers/`)

A file is uploaded into a **section** (`amazon`, `flipkart`, `meesho`, `own_invoices_excel`, `own_invoices_pdf`).
`POST /uploads` checks the section, extension and size (refdata `imports.max_file_bytes`) and returns a presigned
POST for the exact key; `POST /uploads/{id}/complete` asks the store whether the file arrived at the declared size and
queues the `imports.parse` job (the upload is the job's natural key, so a second complete is the same job). The job
re-checks that the queuing user still has `uploads.create`, reads the object from this business's key, records the
SHA-256, and moves the upload to `parsed`, `stored` (a PDF, kept for later; nothing is read until R1-M6) or `rejected` with a reason and plain message. A read error, or an unexpected error on the last retry, settles the upload as `rejected` with `read_failed`, so the screen needs only the upload status. `imports.uploads` holds no
cell values; `raw_deleted_at` is set by the retention rule `purge_uploads` (see Retention below).

Roles: owner and admin upload; owner, admin and CA read (`uploads.view`); billing gets 404 (D-046).

**Readers** (`readers/`) are the plug-in point: `register(reader)` with an id, a section, a report type, `accepts`
(zip entry names), `detect` (required headers) and a `MappingProfile`. A reader is used in production only when
refdata `imports.profile.<id>.verified` is true. This slice ships no readers, so a platform file is rejected with
"We can't read this kind of report yet", and a PDF in the own-invoice section is stored (status `stored`) with no rows.

### Reading and staging (R1-M3 slice 2, `reading.py`, `runs.py`, `parsing/zipguard.py`)

For a section with readers the parse job (1) opens a `.zip` through the guard, which refuses a folder or odd name,
a password, a duplicate name, a file no reader of the section accepts, more than `imports.zip.max_entries` files,
or more than `imports.zip.max_inflate_bytes` once inflated (counted as it is read); (2) reads each file into a table;
(3) asks every reader of the section to `detect` it: none rejects with `unknown_layout`, more than one with
`needs_choice` (the choose endpoint comes with a second reader of one layout); (4) requires the reader's `gstin(table)`
to equal the business's own GSTIN (`gstin_missing`, `wrong_gstin`; the whole file is refused); (5) stages through
`staging.stage` with the reader's hold rule `classify`. Every file in the upload is read before any is staged, and
staging runs in the job's transaction, so a crash leaves no run and the retry starts again. A zip yields one run per
file; `uploads.run_id` points at the first.

A row that parsed as valid is `held` (with a `hold_reason` from `HOLD_REASONS`) or `skipped_zero` when the reader says
so. Held rows are kept and counted separately, never dropped or guessed, and are not counted as new, already imported
or changed. Their wording (`imports.held.<reason>.label`, `.effect_note`) and flags (`.accept_allowed`,
`.needs_ca_check`) are refdata, all provisional. `GET /runs/{id}` and `GET /runs/{id}/rows` (owner, admin, CA) return
the preview: counts, held-by-reason, a "layout unchecked" warning while the profile is not verified (by the reader and
by refdata), and each row's cells as read (non-personal mapped columns only), errors and plain reason.

### Discard, sections and overlap (R1-M3 slice 3)

`POST /runs/{id}/discard` (owner, admin; audited as `imports.run_discarded`) sets a staged run aside and frees its file
to be uploaded again; repeating it is a no-op and a confirmed run answers 409 `run_not_staged`. `GET /upload-sections`
(owner, admin, CA) always returns the five sections with `status` exactly one of "not uploaded", "processing" (a file is
received or parsing), "rows held" (a live staged run has held rows) or "ready"; rejected, expired and discarded uploads
do not count as uploaded. The two own-invoice sections are `enabled: false` until their readers exist (R1-M5, R1-M6).
`UploadOut.run_ids` lists every run of an upload (a zip makes one per file; `run_id` is the first).

On the upload path a record that another live staged file of the same report type already holds is shown as a
`duplicate` (error code `duplicate_in_other_file`) so the preview never promises a count that confirming both files would
double; the first file keeps it and discarding that file frees it for files uploaded afterwards. Rows already staged as `duplicate` in a later file stay so (rows are insert-only): the user discards that file and uploads it again, and the page says so. The rule covers only rows that would be `new`; a `changed` row present in two live files is not flagged and is settled at confirm (StaleRun). The older flow (catalog, confirm) leaves this off and
settles overlap at confirm (StaleRun).

### Deciding held rows (R1-M3 slice 4, `runs.resolve`, `imports.row_resolutions`)

`POST /rows/{row_id}/resolve` (owner, admin; Idempotency-Key) takes `{action: "set_aside" | "accept", note}`. A decision
is a new insert-only `imports.row_resolutions` row (one per import row, held by a unique index so two simultaneous decisions cannot both land; the second is answered like a decided row; nothing is updated or deleted, and the
import row itself is never edited); it is audited as `imports.row_set_aside` or `imports.row_accepted` with the note as the
reason and no cell values. `set_aside` leaves the row out of the return and counts it as set aside; `accept` uses the row
as the file states it and exists only where refdata `imports.held.<reason>.accept_allowed` is true, shipped `false`
everywhere because whether an inconsistent row may be used is a PO and CA decision (CLAUDE.md rule 12). Only a held row
of a staged run can be decided (409 `run_not_staged` after discard or confirm; 422 `action_not_allowed`, `note_required`);
deciding the same way twice records nothing new, and a decided row cannot be switched. **For the slice that confirms a run (R1-M4/M5):** a row's own status stays `held` after a decision; confirm must read the row's resolution, must not import an unresolved or `set_aside` row, and may import an `accepted` row only as the file states it. `RowOut.allowed_actions` (label and
effect note from refdata `imports.action.<action>.*`) and `RowOut.resolution` carry the state, so the page needs no logic
of its own. `RunOut.counts.held` and `held_by_reason` count unresolved rows only, with `set_aside` and `accepted` counted
beside them; a section reads "rows held" until none remain, and `needs_ca_check` stays true for accepted rows whose reason
is flagged.

Not yet: `months` and `already_uploaded_of` on the run, the `from`/`to` filters and `GET /marketplace-coverage` (all need
the months a real reader reads from its file, R1-M4); value fixes (`enter_hsn`, `pick_state`, R1-M4).

## Amazon readers (R1-M4 slice 1, `readers/amazon.py`, `readers/base.py`)

Two readers, `amazon_mtr_b2c_v1` and `amazon_mtr_b2b_v1`, registered by `register_platform_readers()` at start-up.
A report is a CSV named `MTR_B2C-*.csv` or `MTR_B2B-*.csv`, alone or inside a zip (UTF-8 BOM allowed). A reader
claims a file by its header names, not by position or file name alone: six marker headers must be present and the
B2C reader refuses a file that has `Customer Bill To Gstid`. The business GSTIN is read from the `Seller Gstin`
column (compared in upper case); a blank or different one rejects the file whole (`wrong_gstin`).

- **Fields kept:** GSTIN, order/shipment ids, invoice and credit note numbers, the candidate dates (order, shipment,
  invoice, credit note), quantity, HSN, ship-to and ship-from state, taxable value, tax by head and rate, and for B2B
  the buyer GSTIN. Buyer names and addresses are never mapped, so never stored.
- **Rates** arrive as fractions (0.18) and are stored as percent through `FieldSpec.scale` (exact `Decimal`, never inferred).
- **Dedupe key:** `(seller GSTIN, shipment item id, transaction type, credit note no)`. An invoice number is *not*
  part of it: two units of one order share one, and a refund repeats its sale's. A blank credit note number is
  allowed in the key (`key_blank_ok`) because only refunds carry one.
- **Rows by type:** `Shipment` is a sale; `Refund` needs a credit note number; `Cancel` and `FreeReplacement` at zero
  value are `skipped_zero` (provisional, see OPEN_QUESTIONS); a Cancel carrying value is held `sanity`; any other type is held
  `unknown_txn_type`. Blank HSN, quantity or ship-to state hold the row (`blank_hsn`, `blank_qty`, `unknown_state`);
  IGST together with CGST/SGST on one row is held `sanity`.
- **Guards against a wrong guess:** a rate above 100 or below 0 after scaling is held `sanity`, so a file that already
  writes `18` shows as held rows, not as 1800. A file naming more than one seller GSTIN is refused whole (`wrong_gstin`).
  `unknown_state` is held only for a blank state; an unrecognised state name is not yet checked against the state list.
- **To check on the first real report:** whether a real B2C file carries a `Customer Bill To Gstid` column (even empty),
  which would make the B2C reader refuse it and the B2B reader claim it; whether rates are fractions or percents.
- **Not mapped yet:** shipping, gift-wrap tax and TCS columns (exact header names unknown until a real file is checked).
- **Unchecked layout:** both profiles ship with refdata `imports.profile.<id>.verified` false, so every run shows
  the "layout unchecked" warning until a real report has been checked on the owner's machine.

## Flipkart readers (R1-M4 slice 2, `readers/flipkart.py`)

`flipkart_sales_v1` (sheet `Sales Report`, report type `orders`) and `flipkart_cashback_v1` (sheet `Cash Back Report`,
report type `cashback`) read one `Sales Report - <range>.xlsx`, alone or in a zip. A workbook with several sheets is
read sheet by sheet: each sheet a reader of the section names becomes its own table and run (the `Help` sheet is not
read; a sheet with a header and no rows makes an empty run with a "This report had no rows" warning, since a month may have no cash-back; a sheet with nothing at all is skipped). A reader declares its sheet
(`Reader.sheet`); a workbook none of whose sheets any reader names is read as before and refused if it has several.
The whole sheet is read whatever size it declares (the declared-size bug).

- **Rates** are kept as written (percent numbers like 18.0); a rate outside 0 to 100 holds the row `sanity`.
- **Sales rows** are held for: an event type or sub type outside Sale/Return and Sale/Cancellation/Return/Return
  Cancellation (`unknown_txn_type`), blank HSN, quantity or delivery state, IGST with CGST/SGST on one row, and a
  Cancellation or Return Cancellation carrying value (`sanity`). A zero-value one is `skipped_zero`. How Cancellation and
  Return Cancellation count is a CA question (spec section 5, item 4) and nothing here decides it.
- **Dedupe keys:** sales `(seller GSTIN, order item id, event type, event sub type)`; cash-back `(seller GSTIN, note
  id, order item id)`, a blank item id allowed.
- **Cash Back rows** are all held as `cashback_adjustment` (new hold reason; accept is off and the CA check is on). Migration
  `202611131400` widens the `hold_reason` check; no row changes.
- **The same all-sellers rule as Amazon:** a sheet naming more than one seller GSTIN is refused whole.
- **Personal columns** (customer name, address, pincodes) are not mapped, so never stored.
- **To check on the first real report:** the exact names of the tax rate and amount columns, the shipped-from and
  delivery state columns, and the Cash Back sheet's header names (the spec lists only some; its seller GSTIN column is assumed
  to be `Seller GSTIN`). Both profiles ship unverified.

## Months, coverage and filters (R1-M4 slice 4)

- **`summary.months` on a run** (`RunOut.months`, `["2026-07"]`): the calendar months of one date field each reader names
  (`coverage_field`: Amazon shipment date, Flipkart order approval date for sales and invoice date for cash-back, Meesho
  order date for sales and return date for returns). It is **for the coverage view only**: it is not the return period.
  Which date places a row in a return is a CA question (spec section 5, item 1) and the build decides it (R1-M7). A sheet
  with no rows takes the months of the other sheets of its file. No migration: it lives in the run's `summary`.
- **`already_uploaded_of`** (`RunOut`): the id of an earlier preview of the same file that was discarded, so the page can
  say "you uploaded this before". A file that is still live is not a new run at all (the existing run is returned).
- **`GET /marketplace-coverage?from=&to=`**: months with any live preview, and for each of the three platforms the report
  types it needs (from its readers), the ones received, `complete` (all needed ones received) and `held_rows` (open held
  rows in those previews; a preview covering two months counts in both). Read-only; CA and members read it, another
  business gets nothing.
- **`from` / `to` on `GET /uploads` and `GET /upload-sections`**: an upload is listed when any month its live previews
  cover falls in the range (compared by calendar month). An upload with no month known (turned away, still being
  read, or no dated rows) is always listed in `/uploads`, since hiding it would hide a problem. `to` before `from` is 422.
- **`requirement_note`** on a section comes from refdata `imports.requirement.<section>.note` (wording to be settled).
## Meesho readers (R1-M4 slice 3, `readers/meesho.py`)

`meesho_sales_v1` (`tcs_sales.xlsx`, report type `orders`) and `meesho_returns_v1` (`tcs_sales_return.xlsx`, report
type `returns`) read the two workbooks of a month's zip (one sheet each, named after the supplier id). The return file
is the one with `cancel_return_date`; `transaction_type` is empty in the samples and is not used. The text `null` is a
blank (`FieldSpec.blank_tokens`, applied to the mapped fields of this profile). The supplier name and enrolment number are not mapped, so never stored.

- **Dedupe key and why (D-051).** Meesho's files carry no stable row id, and `sub_order_num` is not unique (a month had
  57 sales rows for 55 orders: the extra two were price adjustments). The key is the spec's composite
  `(gstin, sub_order_num, order_date, quantity, total_taxable_sale_value, total_invoice_value)` plus the file kind (the
  run's report type) plus an occurrence counter (`MappingProfile.occurrence_field`). Rows with the same key and the
  same content in one file are separate records counted 1, 2, ... in file order. Rows with the same key and
  different other values (state, rate, tax, shipping, HSN, dates) are never merged or dropped: **all of them are flagged
  `conflict`** (an ambiguous duplicate) for the user to look at. Cost: a re-issued file with a corrected taxable or invoice
  value looks like new rows, which the "changed" logic cannot see; the live-file overlap rule and the file checksum
  still stop the same file being staged twice.
- **Adjustments:** a row with quantity 0 and any value is held `price_adjustment` (a new reason, accept off, CA check on).
  A quantity-0 row with no value is `skipped_zero`. A blank quantity is `blank_qty`.
- **Other holds:** blank HSN, blank customer state (`unknown_state`), a rate outside 0 to 100, a negative taxable or
  invoice value on a row that has units, and a return with no `cancel_return_date` (`sanity`).
  `taxable + tax = invoice` is not checked: the values are long fractions and no tolerance is invented.
- **No tax split:** the file has one `tax_amount`; the build derives CGST/SGST/IGST from the place of supply (a CA item).
- **To check on the first real report:** the zip entry names (taken as exact from the spec), the date formats, and
  whether the sales file really lacks `cancel_return_date`. A sheet naming more than one seller GSTIN is refused whole.

## Value fixes and the local checker (R1-M4 slice 4b)

- **`enter_hsn` and `pick_state`** are new `resolve` actions with a `value`. `enter_hsn` is offered only on a `blank_hsn` row
  and takes an HSN in the shape refdata `hsn.pattern` allows (a typo check, never which HSN fits); `pick_state` only on an
  `unknown_state` row and takes a code from the refdata state list. Both need a note, like every decision. They are stored in
  `row_resolutions` (`kind = 'fixed'`, `fix_field`, `fix_value`; migration `202611131500`, additive): insert-only, one
  decision per row, the same fix twice is one decision, a different value or another action is refused. **The row as the
  file said it is never changed**; the build (R1-M7) reads the decision to use the value. Runs count them as `counts.fixed`.
  The audit event `imports.row_fixed` names the field, never the value.
- **`scripts/check_reader.py <file>`** (local only): prints which reader claims each file or sheet, which headers were found
  or missing, and row counts (new, held by reason, skipped, invalid by code). Never a cell value, GSTIN, order number, path or
  a sheet name a reader does not name. Writes nothing and uses no database or network. The reader `verified` flags stay false
  until someone has run it on a real report and the headers all matched; flipping a flag is then a reviewed refdata change.
- **Not built: the choose-reader endpoint.** No two real readers claim one layout, so `needs_choice` cannot happen (EM, 2026-11-13).

## Own sales invoices, Excel (R1-M5 slice 1, `readers/own_excel.py`)

The `own_invoices_excel` section reads our own template: one row per invoice line on a sheet named `Invoices`
(a CSV with the same headers is read too; other sheets, such as `How to fill`, are not read). `own_excel.COLUMNS` is
the one list of columns, so the template download (slice 2) and the reader cannot drift. The profile ships unverified
(`imports.profile.own_invoices_excel_v1.verified` false) until the owner has filled one real month and run the local
checker (`python scripts/check_reader.py --section own_invoices_excel file.xlsx`). The section is `enabled: true` since
slice 2, which adds the template download.

- **Template download (slice 2, `template.py`):** `GET /b/{b}/uploads/own-invoices-template` (`uploads.view`: owner, admin and
  CA; billing and strangers get 404) returns an .xlsx built in code from `own_excel.COLUMNS`: an `Invoices` sheet with the
  header row and no values (the Document type cell offers the three types), and a `How to fill` sheet the reader does not
  read. That sheet says in plain words that exports, SEZ supplies, reverse charge, advances, nil-rated or exempt supplies
  and e-commerce operator sales are not supported yet and must not be entered as ordinary rows. A test reads the generated
  workbook back through the reader, so the headers cannot drift. The blank template uploads as an empty run. The
  marketplace coverage view stays platform-only: an own-invoice run still carries its `months` (from the document date),
  so the `from`/`to` filters on uploads and sections apply to it; whether the build wants an own-invoice coverage row is
  R1-M7's to say.
- **Kept:** the seller GSTIN (every row; the whole file is refused unless it is the business's own, as for platform
  files), document type, number and date, the original invoice number and date of a note, the buyer GSTIN (the only
  buyer detail: the template has no name or address column and any extra column is not stored), place of supply, HSN,
  quantity, unit, taxable value, the rate as typed, the four tax amounts as typed, and the document total. Money is
  `Decimal` with the typed text kept. A rate of 0 is kept as typed.
- **Held:** `unknown_txn_type` (a document type other than Invoice, Credit note or Debit note),
  `missing_original` (a note with no original invoice number), `number_format` (a number that does
  not match refdata `imports.own_invoices.document_number_pattern`: the wording says to check it against the invoice,
  never that it is invalid), `blank_hsn` and `blank_qty` and `blank_uqc` (unit), `unknown_state` (place of supply blank
  or not a state name or code in refdata), `sanity` (a rate outside 0 to 100, IGST together with CGST or SGST, CGST
  different from SGST). The two new reasons are never acceptable as typed and carry the CA flag (D-053).
- **Not checked here (R1-M7 conditions):** taxable value times rate against the tax, intra- against inter-state from
  the place of supply, the HSN's minimum digits, and any period. Exports, SEZ supplies, reverse charge, advances,
  nil-rated or exempt marking and an e-commerce operator's GSTIN have no column and are not supported yet.
- **Identity:** seller GSTIN, document type, document number (each upper-cased with spaces removed for the key only)
  and the line's position within that document in the file. A later file with the same document and other values,
  with lines in another order, or with the same number reused in another financial year shows those rows as `changed`
  against a confirmed earlier file (or `duplicate` against a live one), never as a silent second copy.
- **Known limit (gate for R1-M7):** two different documents that carry the same number in one file are not caught by the
  reader. They are counted as lines 1 and 2 of one document (a test pins this), with no hold and no conflict, because
  a document's lines share a number by nature. The build must not assume the reader caught reused numbers: it has to
  check that the rows of one document agree on date, original invoice, buyer GSTIN and total (the template repeats the
  total on every line).

## Confirm check (R1-M7 slice 1, `confirm.py`)

`GET /b/{b}/runs/{run}/confirm-check` (`uploads.view`: owner, admin, CA; billing and other businesses 404; a run that is not staged 409 `run_not_staged`) says whether a staged run could be confirmed and, if not, why. It is read-only and decides nothing about tax. The confirm itself is slice 2.

Included rows are `new` and `changed` rows and held rows the user accepted or fixed; never a set-aside row, and never `already_imported`, `duplicate` or `skipped_zero` rows (counted in `left_out`). Each blocker has a code, refdata wording (`imports.confirm.<code>.label`), a count and up to 20 row numbers, never a cell value, GSTIN or document number:

| Code | When |
|---|---|
| `profile_not_verified` | the layout is not verified (LLD-7 L7-13). A local demo (`DEMO_READERS=1` in a debug environment, never on Lambda) opens this gate so synthetic files can be taken end to end; production profiles stay unverified. |
| `period_date_unconfirmed` | the profile has no `imports.profile.<id>.period_field` row. Flipkart and Meesho have none until the CA answers (question sheet M-4). |
| `rows_undecided`, `rows_invalid`, `rows_conflict` | a held row has no decision; a row could not be read; the file repeats a record with other values. Nothing is left out silently. |
| `document_rows_disagree` | lines of one document (own invoices: seller GSTIN, type, number, and the financial year of its date) differ on date, original invoice, buyer GSTIN or total. |
| `rows_conflict_across_runs` | a reader with a `cross_run_key` (Meesho: GSTIN, sub-order number, order date) has a live row of another file with the same key and different values. The user may set aside the new row (the only decision offered on a `new` or `changed` row, and only for such a clash); an older confirmed row stays. Reported even while the period date is open. |
| `hsn_too_short` | an included row's HSN (a fix replaces it) is shorter than `business.hsn_min_digits` for its date. With no turnover band the stricter count applies and the note `hsn_band_missing` says so (needs CA check). |

**Known performance limit.** Because `allowed_actions` on a `new` or `changed` row depends on the cross-file clash, every row-list or single-row request for a staged run of a reader with a `cross_run_key` (Meesho) loads every row of that run and the matching rows of other live runs to work out the clash. That is fine for a month of a small seller and slow for a very large file. The fix is a cap on rows per run or a query that fetches only the keys on the page; it can be a later slice.

The date used is the profile's `period_field` (a comma list, the first present wins), never the coverage `months` label (D-052). See D-056.

## Confirm into documents (R1-M7 slice 2, `confirm.py`, `documents.py`)

`POST /runs/{id}/confirm` turns a checked preview into confirmed documents and lines (insert-only tables, one document per seller GSTIN, kind, folded number and financial year of its date) and assigns each to a return once, by the filing period of the profile's period date. It runs the confirm check first and refuses with `confirm_blocked` while anything blocks. Other refusals: `changes_undecided` (a changed row nobody decided), `change_needs_correction_note` (an accepted change needs a note), `run_stale` (rows moved since the check), `period_locked` (409). Re-confirming the same run changes nothing.

Confirm locks the run row and the report type first, then re-runs every gate (`check`) inside the same transaction, so a file confirmed by someone else between a check and the confirm is seen, not missed. A row with no readable document date is an invalid row at staging and so blocks the confirm (`rows_invalid`); `rows_undated` guards the same case if a reader ever lets one through. A PDF row whose required field is unreadable also becomes an invalid row, which the check treats as undecidable: the seller corrects the source and uploads again.

Confirms are serialised per business (a second advisory lock beside the report-type lock). **Condition on a future PDF `treatment_confirmed` flag:** see OPEN_QUESTIONS; an Excel and a PDF run of the same invoice must not attach duplicate lines.

Only the own-invoice reader maps documents. A platform profile whose refdata `treatment_confirmed` is not true is refused with `treatment_unconfirmed` and its `open_ca_items`; the screen says the treatment is not settled yet, never that the data is wrong. `POST /uploads/none-this-month` and `GET` record that a section has nothing for a month (audited, counts only).

## Build a return from confirmed documents (R1-M7 slice 3, `filing/build.py`)

`imports.v_filing_lines` publishes the current line of every confirmed own-upload invoice and credit note (a superseded line is not shown); `filing.v_supply_lines` unions it with `sales.v_filing_lines` in view contract v1 (LLD-5 §3, columns unchanged, tested). `build_return(tx, instance)` is the one place that sums a return: a monthly GSTR-1 or an IFF uses the lines assigned to it; a QRMP quarter uses its own plus skipped IFFs forwarded to it for the liability tables, and its own plus every IFF month for Table 12, and its reconciliation adds the filed IFF months' liability. Each section row carries `source_refs` of the form `file name row N`. The result has a fingerprint over the instance, the debit-note count and every member line (stable in any order; one paisa or one line more changes it), `ca_flags`, `draft` (true until the return is locked) and `debit_notes`.

What is not in the build: debit notes (no supply class yet, so no section) and marketplace documents. `imports.v_unsummed_documents` lets the build count the debit notes dated in the instance's own period (a debit note has no return of its own, so an IFF month and the quarter that holds it both show it); the return shows them as "not in this return yet, needs CA check". **M8 must refuse, or warn with an explicit acknowledgement, on export while `debit_notes > 0`.** The units come from the file as typed (upper-cased; blank is `NA`, which is not on the list either); any unit not on the refdata UQC list, blank ones included, is named in a `uqc_unlisted` flag, and the mapping itself needs a CA check. Every build lists what it rests on and the CA has not answered (`ca_flags`: the builder's pending items, exports/SEZ/reverse charge/advances/nil-exempt, marketplace reports, UQC mapping), for the returns screen and the CA pack. S4 adds the checks and S5 the returns API.

## Checks over a build (R1-M7 slice 4, `filing/checks.py`)

`run_checks(tx, build)` returns the findings for a build, in registry order. **Report-only:** nothing blocks, changes a value or stops a build in M7; `level` (block, warn, info) is what the export in R1-M8 will act on. A finding has a code, a message that names the row (file and row number), `source_refs`, a `subject_fp` that moves when its rows move (for acceptances later) and `needs_ca_check`. It is read-only and gives the same findings twice for the same build.

LLD-5 §6 checks built: C-01 missing HSN, C-02 customer GSTIN (shape and check digit), C-03 document number length and characters (refdata `invoice.number.*`, provisional), C-04 same number twice in one financial year for one GSTIN and kind (case-insensitive), C-05 unknown place of supply, C-10 HSN digits below the minimum (`hsn_min_digits`; `needs_ca_check` while the turnover band is unset), C-12 a B2CS row netting negative (refdata `gstr1_offline.allow_negative_b2cs`, false until QA open item 3), C-16 relied-on refdata values not confirmed. Own-invoice and arithmetic findings (decision 6, no tolerance chosen, any difference shown): A-01 tax is not taxable x rate (difference shown), A-02 heads do not fit the place of supply, A-03 CGST differs from SGST, A-04 a number used in more than one financial year (information). C-13 (more rows than one file holds, warn; refdata `gstr1.offline_tool.max_lines`, provisional) and C-17 (the offline tool works tax out again per invoice-and-rate row: round half up of taxable x rate per head, CGST and SGST at half the rate, both figures shown, any difference, cess not compared, needs a CA answer CA-2) are built in R1-M8 follow-up 1. C-07, C-09 and C-11 follow in follow-up 2. C-06 stays an export gate reason (`not_open`), not a finding: as a finding it would show a block on every filed return (CEO, 2026-11-18). C-08, C-14 and C-15 are not built, with their reasons in OPEN_QUESTIONS. Some findings cannot arise from an upload because the file's row is held first (an over-long number, unequal CGST and SGST); the checks still run on them for sales documents and for a row a user accepted.

## The returns API over a build (R1-M7 slice 5, `filing/api.py`)

`GET /b/{b}/returns/{instance}` (`returns.prepare`: owner, admin and CA; billing and other businesses get 404, so does a GSTR-3B or PMT-06 instance, which is not built from supply lines) returns the on-screen GSTR-1 or IFF from the confirmed uploads: the instance, `draft` with a `banner` ("Draft: not filed..."), `report_only: true`, the fingerprint, line items and member count, totals (liability, Table 12, and the gap between them, which is zero when they agree), a summary per section (row count and totals), `debit_notes` (count and the "not in this return yet, needs CA check" notice), `ca_flags` (what the return rests on that a CA has not answered, including the M7 omissions), and the findings with `finding_groups` (code, level, count) so the screen can group a noisy code such as A-01 instead of listing it as errors. `GET .../sections/{section}?cursor=` lists one section's rows (`b2b, b2cl, b2cs, cdnr, cdnur, hsn_b2b, hsn_b2c`), 100 a page, each with `source_refs` (file and row). Amounts are exact decimal strings as stored; nothing is rounded. Both routes only read and the same data gives the same fingerprint. No acceptance, export or lock route exists yet (R1-M8).

## Own sales invoices, PDF (R1-M6 slice 1, `imports/pdf/`)

Wired into uploads in slice 2b (below). Slice 1 added the reader and its handoff. `InvoiceReader.read(pdf, limits)` returns `ReadResult(invoices, unreadable_pages)`; each
`ExtractedInvoice` has the Excel template's fields, its lines, the pages it came from and `unclear`, the document fields
not found or contradicting themselves. `to_table(...)` turns an extraction into a `SourceTable` with the template's
headers, one row per line (an invoice with no readable line gets one row with its document fields only), so staging,
hold rules and review are shared with the Excel reader.

`TextLayerReader` (`pdf_text_v1`) reads the text layer with pdfminer.six (MIT, pinned). It groups characters into
visual rows and cells, finds the line table by its headings (HSN, Taxable Value, GST %, CGST, SGST, IGST, Cess, Qty,
Unit), and takes the document number, date, original invoice number, place of supply, GSTINs and grand total from
printed labels. The seller's GSTIN is the one outside a Bill To / Buyer block; the buyer's is the one inside it (a
B2C invoice has none, and that is not "unclear"). A credit or debit note is told by its title. Amounts are parsed as
Decimal text, commas removed; dates become DD-MM-YYYY. No tax logic, no inference, no arithmetic check, and no buyer
name, address or item description is read into a result.

Several invoices in one PDF are split on the document number. A page naming a different number starts a document; a page
with no number, no title and no date continues the one before; anything else (two numbers on one page, an unnumbered
page that looks new) refuses the whole PDF with `ambiguous_split`. Refusals carry only a code: `not_a_pdf`,
`encrypted`, `unreadable`, `too_many_pages`, `too_complex`, `too_slow`, `too_many_documents`, `ambiguous_split`.
pdfminer follows no link, script or embedded file, and its debug logging, which prints raw tokens, is switched off. A
page with no text is listed in `unreadable_pages`; the time cap is checked between pages, so the page and character
caps are what bounds one page, with the 20 MB upload cap and the Lambda memory and timeout limits behind them (one
huge page can still use memory and time before a cap fires). The HSN shape is refdata `hsn.pattern`, passed to the reader; the
reader never decides a minimum length. Numeric dates are read day first (DD/MM/YYYY); one that is not a real date that way is
blank. The seller is the GSTIN outside a Bill To / Buyer block (the letterhead's), so a stray word like "from" cannot move one.

**Sandbox (S2a, `pdf/sandbox.py`, `pdf/worker.py`).** The parse never runs in the worker: pdfminer decodes a page's
streams before any cap of ours can look, so a small PDF can expand to hundreds of MB. `read_sandboxed(pdf, limits,
hsn_pattern, max_memory_bytes=...)` runs the reader in a child process that sets its own address-space and CPU limits,
has an empty environment apart from the code path, writes no files, and is killed when the wall clock runs out; any
failure comes back as a refusal code. Verified here on Linux with a synthetic bomb (a 400 KB PDF that expands to 400 MB:
refused in about 1 s under 512 MB, read in about 4 s under 1 GB, so the limit is what stops it). Not verified: the limit
inside a real Lambda (RLIMIT_AS counts address space, not resident memory, so the refdata value needs checking there before
the first deploy). Packaging, measured with `scripts/build_lambda.sh app` (aarch64 Python 3.12 wheels fetched by pip, nothing
run on arm64): the app zip is 36.1 MB zipped and 96 MB unzipped without pdfminer.six and 42.9 MB and 105 MB with it, against
Lambda's 50 MB limit for a zip uploaded directly (Terraform's `filename`) and 250 MB unzipped. The memory value must be chosen against the
Lambda memory of the worker that calls the sandbox (the parent holds the PDF and the child's answer while the child may use
up to the limit), and checked on the first deployed arm64 build: address-space limits count mapped libraries, and a CI runner
passing the bomb test does not prove it. The child is not otherwise isolated: no network block, no syscall filter, no
process-count limit; with no credentials in its environment and no network code in pdfminer that is accepted for R1. Its
stdout is read in full before the 8 MB check, bounded by its own memory limit. The child's answer is itself untrusted: the parent
requires a JSON object, accepts a `refused` code only from the known set, and checks every field (a string of at most 100
characters or null, integer pages within the page cap, at most `max_documents` invoices and a bounded number of lines,
exactly the expected keys); anything else is `unreadable`. First-deployed-build checklist: (a) read a tiny PDF through
`read_sandboxed` in the deployed runtime as a smoke check, because the child's empty environment drops `LD_LIBRARY_PATH`,
which the Lambda Python runtime may need (pass it through if so; it is not a secret); (b) check the RLIMIT_AS value there;
(c) the child has no network block. The dependency audit in CI is
the EM's separate change; the Lambda size margin is about 7 MB zipped before an OCR layer.

Two more layouts are read since slice 4c (D-079). **Tax over "Rate" and "Amt":** when the row under the headings holds only Rate and Amt cells, each under a tax heading, the Amt cell becomes that tax's column and the Rate cell is kept out of the way; an IGST rate is the line's GST % only when there is no GST % column, and a CGST or SGST rate is never doubled into one (that stays blank and unclear). **Labels above values:** a row made only of known labels (invoice no, invoice date, date, place of supply, GSTIN, credit or debit note no) over a row with exactly one value cell under each is read as "label: value". If any label has no value under it, that label row is dropped and its fields stay blank and unclear. Scans and photos are the OCR reader's job (slice 4b, D-078, not used in production). Tested only on synthetic PDFs made in `tests/fixtures/pdf.py`; accuracy on real invoices is not known.

### Own-invoice PDFs in uploads (R1-M6 slice 2b, `readers/own_pdf.py`, `reading.read_pdf`)

A PDF in the `own_invoices_pdf` section is no longer stored: the parse job reads it in the sandbox (limits from refdata
`imports.pdf.max_pages`, `max_chars_per_page`, `max_documents`, `max_seconds`, `max_memory_mb`; the HSN shape from
`hsn.pattern`), makes a table with the Excel template's headers plus `Unclear fields` (names of the fields not read,
never values) and stages it with `reading.stage_tables`, the same path as a spreadsheet: the seller's GSTIN check, hold
rules, preview, set aside, coverage months from the invoice date. The reader `own_invoices_pdf_v1` is the Excel reader's
profile with one hold first, `pdf_unclear`: a row with any unclear field is held, with the refdata wording, and is not
acceptable as read. A row missing a required field (document number, date, taxable value, rate) is an invalid row with
its errors, as in the Excel. Its report type is `invoices_pdf`, so the same document in an Excel and in a PDF are two
runs, not one that "changed". Refusals shown on the upload: `not_a_pdf`, `pdf_encrypted`, `pdf_ambiguous`,
`pdf_too_big`, `no_text_layer` ("This looks like a scan or a photo... type the rows or upload the Excel", also for a PDF
with one scanned page among text pages), `wrong_gstin`, `gstin_missing`, `read_failed`. The sandbox runs while the parse
job's transaction is open, for at most `max_seconds` plus a short grace. Limit: the value fixes (enter HSN, pick state)
are keyed to their own hold reasons, so a `pdf_unclear` row offers only "set aside" for now. Verified here on Linux,
PostgreSQL 16, Python 3.13, synthetic PDFs only; not in a Lambda.

## Excel versus PDF cross-check (R1-M6 slice 3, `crosscheck.py`)

`GET /b/{b}/own-invoices/crosscheck` (owner, admin, CA; billing and strangers get 404). Read-only, computed on request, no table: nothing is stored and nothing reaches a return. It lists every difference between the Excel and the PDF-read rows of the seller's own invoices; it never says which side is right.

- **Which rows.** Rows of live runs (staged or confirmed, never discarded) of report types `invoices` (Excel) and `invoices_pdf`. A row set aside is left out, as it will be from the return, so the difference it makes shows. An undecided held row (including `pdf_unclear`) makes its document `not_compared` (counted per side), never a false mismatch; an accepted or fixed held row counts, with a fixed place of supply applied. Invalid rows and rows with no document number or seller GSTIN cannot be placed on a document and are counted as `unplaced_rows`. A record several live files carry is counted once: `duplicate` and `already_imported` rows are skipped (they are the same record as a row of another file), and a later file's `changed` row replaces the older row with the same key, so a cumulative Excel (January, then January plus February) does not count January twice.
- **Per document**, matched on seller GSTIN, document type, document number (trimmed, case-folded) and the financial year of the document date, as the confirm check does. Compared: document date, buyer GSTIN, place of supply (a name and a code of the same state agree), the sum of taxable value, IGST, CGST, SGST/UTGST and cess, the invoice total, and the number of lines. An amount that is not a number is not read as zero: its document is `not_compared`. A blank amount column is zero. `live` comes from the runs, so an Excel with a header and no rows still counts as an upload for the note. Money is exact Decimal equality; no rounding tolerance is applied (a CA question, OPEN_QUESTIONS). A different line split with the same sums is not a difference.
- **Response.** `only_in_excel`, `only_in_pdf`, `mismatches` (per field: Excel value, PDF value; plus the row ids of both sides so the screen can colour the cells), `not_compared`, `matching`, per-side `live`, `documents`, `unplaced_rows`, and `compared` (an Excel and a PDF upload are both live). Cell values of buyer names and descriptions are not stored, so none can appear.
- **`show_validate_note`** is the R1 rule: true only with a live Excel upload and no live PDF upload. The web thread shows the note "upload invoices and we can validate" from this flag.
- **Too-complex PDFs.** A PDF that runs out of time or memory in the sandbox is now rejected as `pdf_too_complex` ("This PDF is too complex for us to read here. Type the rows or upload the Excel."), since it fails the same way every time; other unreadable files stay `read_failed`.
- **Size.** It loads every live own-invoice row of the business on each request: fine for the first customers. Add a month filter or a row cap before real history builds up (owner: R1-M6 follow-up, not yet done).
- **Not claimed.** Nothing here was run on a real invoice pair. A PDF with an unreadable required field stages invalid rows, which cannot be confirmed (R1-M7 confirm check), so it is listed as `unplaced_rows` here and the way forward is the Excel.

### Scans and photos: the OCR reader (R1-M6 slice 4b, D-078)

`pdf/ocr_reader.py` (`OcrReader`, id `pdf_ocr_v1`) reads a PDF that is only a picture. It rasterises with poppler's `pdftoppm` (longer side 2400 pixels) and reads each page with Tesseract (`--psm 6`, TSV), both run as separate programs with an empty environment (only `PATH`, one OCR thread, `LC_ALL`), a scratch directory, the remaining `imports.pdf.max_seconds` as the time limit and a bounded answer. Words become cells on rows in the same shape the text-layer reader builds, so the same field rules, hold rules, review screen and cross-check apply. A word that contains a digit and has Tesseract confidence below 60 is dropped, never kept as a guess, so the field stays blank and is named in `unclear`; a label word is kept down to 30. A page with no word it is sure of is `unreadable_pages`.

- **Not selected anywhere.** Nothing in `reading.read_pdf` or the worker uses it. In R1 a scan is held as `pdf_unclear` and the seller is asked for the Excel or a text PDF (CEO, 2026-11-18): Tesseract and poppler do not fit the Lambda package (about 7 MB of margin) and a container Lambda was not approved. It runs locally and in CI only.
- **Dependencies.** The programs `tesseract-ocr` (Apache-2.0) and `poppler-utils` (GPL-2, run as a separate program, not linked) are installed on the CI `app` job for the tests; no new Python package. Tests skip where they are absent.
- **Before any deployment.** poppler parses untrusted PDFs, so the rasterising must run inside a sandbox like the text reader's (D-055) and the container must be proved first. The Tesseract version is not pinned: CI installs the distribution's current package (5.5.0 on the run checked) and a developer machine may have another (5.3.4 here); both passed the tests.
- **Where the tests run.** The OCR tests need `pdftoppm` and `tesseract`. They run in the CI `app` job (which installs both, prints their versions and fails the tests if either is missing) and on a developer machine that has them; on any other machine they are skipped.
- **Not claimed.** Tried only on synthetic pages drawn from our own fixture generator at 200 dpi. Nothing was run on a real scan, a phone photo, a skewed or low-resolution page, or a language other than English; accuracy on those is unknown. The confidence floors (60, 30) are first guesses, not tuned.

## Retention of uploads (R1-M3, TD-18)

`retention.purge_uploads()` (the third rule of the retention Lambda, after `purge_drafts`) does two things in the
database and neither touches S3: a `pending` upload older than refdata `imports.upload.pending_minutes` (60) becomes
`expired`, and an upload older than `imports.upload.keep_days` (90) gets `raw_deleted_at`, so the page stops offering the
raw file. The object itself is removed by the bucket's own lifecycle rule for the `uploads/` area (`upload_retention_days`
in `infra/modules/storage`, 90); the Lambda has no S3 rights. **The two 90s must move together.** Rows, runs, rows' held
reasons and decisions stay; nothing is deleted. The rule ships off (`retention.purge_uploads.enabled` false, like the others;
a dry run still counts) and a missing period row means keep. The definer may read only `id, business_id, status, created_at,
raw_deleted_at` and change only `status, raw_deleted_at, updated_at` on `imports.uploads`; never a file name or checksum.

