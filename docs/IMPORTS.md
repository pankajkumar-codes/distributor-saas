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

## Own sales invoices, PDF (R1-M6 slice 1, `imports/pdf/`)

Not wired into uploads yet (slice 2): a PDF in the own-invoice section is still stored and not read. This slice adds the
reader and its handoff. `InvoiceReader.read(pdf, limits)` returns `ReadResult(invoices, unreadable_pages)`; each
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
Lambda's 50 MB limit for a zip uploaded directly (Terraform's `filename`) and 250 MB unzipped. The dependency audit in CI is
the EM's separate change; the Lambda size margin is about 7 MB zipped before an OCR layer.

Not read yet: tax split over two heading rows ("CGST" over "Rate" and "Amt"), labels above their values, scans and
photos (OCR, slice 4, packaging to be proved first). Tested only on synthetic PDFs made in `tests/fixtures/pdf.py`;
accuracy on real invoices is not known.

## Retention of uploads (R1-M3, TD-18)

`retention.purge_uploads()` (the third rule of the retention Lambda, after `purge_drafts`) does two things in the
database and neither touches S3: a `pending` upload older than refdata `imports.upload.pending_minutes` (60) becomes
`expired`, and an upload older than `imports.upload.keep_days` (90) gets `raw_deleted_at`, so the page stops offering the
raw file. The object itself is removed by the bucket's own lifecycle rule for the `uploads/` area (`upload_retention_days`
in `infra/modules/storage`, 90); the Lambda has no S3 rights. **The two 90s must move together.** Rows, runs, rows' held
reasons and decisions stay; nothing is deleted. The rule ships off (`retention.purge_uploads.enabled` false, like the others;
a dry run still counts) and a missing period row means keep. The definer may read only `id, business_id, status, created_at,
raw_deleted_at` and change only `status, raw_deleted_at, updated_at` on `imports.uploads`; never a file name or checksum.

