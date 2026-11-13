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
"We can't read this kind of report yet", and a PDF in the own-invoice section is stored and marked read with no rows.
