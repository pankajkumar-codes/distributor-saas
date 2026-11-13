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
cell values; `raw_deleted_at` is set when the retention rule purges the raw file (a later slice).

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
double; the first file keeps it and discarding that file frees it. The older flow (catalog, confirm) leaves this off and
settles overlap at confirm (StaleRun).

### Deciding held rows (R1-M3 slice 4, `runs.resolve`, `imports.row_resolutions`)

`POST /rows/{row_id}/resolve` (owner, admin; Idempotency-Key) takes `{action: "set_aside" | "accept", note}`. A decision
is a new insert-only `imports.row_resolutions` row (the latest per import row wins; nothing is updated or deleted, and the
import row itself is never edited); it is audited as `imports.row_set_aside` or `imports.row_accepted` with the note as the
reason and no cell values. `set_aside` leaves the row out of the return and counts it as set aside; `accept` uses the row
as the file states it and exists only where refdata `imports.held.<reason>.accept_allowed` is true, shipped `false`
everywhere because whether an inconsistent row may be used is a PO and CA decision (CLAUDE.md rule 12). Only a held row
of a staged run can be decided (409 `run_not_staged` after discard or confirm; 422 `action_not_allowed`, `note_required`);
deciding the same way twice records nothing new, and a decided row cannot be switched. `RowOut.allowed_actions` (label and
effect note from refdata `imports.action.<action>.*`) and `RowOut.resolution` carry the state, so the page needs no logic
of its own. `RunOut.counts.held` and `held_by_reason` count unresolved rows only, with `set_aside` and `accepted` counted
beside them; a section reads "rows held" until none remain, and `needs_ca_check` stays true for accepted rows whose reason
is flagged.

Not yet: `months` and `already_uploaded_of` on the run, the `from`/`to` filters and `GET /marketplace-coverage` (all need
the months a real reader reads from its file, R1-M4); value fixes (`enter_hsn`, `pick_state`, R1-M4); raw-file retention
(next).
