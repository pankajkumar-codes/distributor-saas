# Table 13 (documents issued) in the GSTR-1 export, with check C-08

Status: specification for issue #353 (R1). Docs only; nothing here is built. Decision D-099 (proposed) in `docs/DECISIONS.md`.
Sources: CA expert answer `team/program-lead/ca-table-13-answer-v1.md` and v3 point 2; portal expert answer `team/gst-portal-expert/TABLE13-documents-issued.md`; the structure of a real tool-exported file in `team/research/gstr1-offline-json-structure.md` section 3 (doc_issue); worked example `team/gst/gstr1-examples.md` A7 and Part E. The people who answered are AI readers of government documents, not a registered CA; items marked **[CA]** need a human check before go-live.

## 1. Why

The portal blocks Generate Summary when Tables 4 to 10, 14 or 15 hold data and Table 13 is empty (GSTR-1 FAQ Table-13 Q11; manual Notes 6 and 7). Today `render_json.py` writes no Table 13 and `export_model.NOT_IN_FILE` tells the person to type it on the portal. Every R1 return with B2B, B2CL, B2CS, CDNR or CDNUR data is therefore stopped on the portal. This spec makes the export carry Table 13 and makes the app say so before download.

## 2. What is settled and what is not

| Point | State | Source |
|---|---|---|
| Table 13 mandatory when Tables 4 to 10, 14 or 15 have data | Settled | FAQ Table-13 Q11; manual Notes 6, 7 |
| Practice documents are never issued documents | Settled in principle | rule 46 and s.31; CA answer Q3 |
| Draft with no legal number is not counted; finalised then cancelled counts in Total and Cancelled | Recommended rule | CA answer Q2 |
| Numbers consecutive and unique per FY; Table 13 covers the return period only | Law frame | rule 46(b); GSTR-1A manual |
| JSON key names, doc_num codes and row keys | **Verified on one real file** (not on the portal) | research file section 3: `doc_issue {flag, doc_det[{doc_num, docs[{num, from, to, totnum, cancel, net_issue}]}], chksum}`. All 12 `doc_num` slots were present, unused ones with `docs: []`. |
| Whether the portal accepts the file with `chksum` omitted, flags dropped, or empty slots omitted | Unknown | Pankaj's planned test upload |
| Whether marketplace-issued invoices belong in the seller's Table 13 | **Not settled** | CA answer Q1 |
| Portal-side validations (totnum >= cancel, no overlap) | Unknown | general knowledge only |

## 3. Assumptions (explicit and reversible)

A1. **Own series only, by default.** Table 13 rows come from series issued under the seller's control: our own live documents and the seller's own invoices uploaded from other software. Marketplace-issued numbers (Amazon, Flipkart, Meesho and the like) are **not** counted by default. Reverse by ticking "Count this series" on that row (section 5). **[CA]**

A2. **A marketplace-only seller still needs Table 13** (the pilot seller's filed Table 13 of 237 documents included marketplace series: examples E-8). With A1 the default set is then empty while Tables 4 to 10 have data, so C-08 blocks and the screen offers two ways out: tick the marketplace series, or enter the seller's own series by hand. The app never guesses which. This is the one place the person must act in R1.

A3. **Practice documents (`PR-` numbers) never count**, never appear in any row, and never merge into a legal series. `sales.v_filing_lines` already excludes them (`where not d.is_practice`); Table 13 must read the same live-only source and a test proves it.

A4. **Cancelled counts cannot be known from uploaded rows.** Suggested rows carry cancelled = 0 and the person must confirm or edit it. Own live documents that were cancelled after finalising (when numbering is on) are counted from the audit trail, not typed.

A5. **Never merge series.** A series is the pair (nature, prefix pattern). Marketplace series and own series never share a row, even when the digits are consecutive.

A6. **JSON follows the verified real file** (keys and nesting above), flags as the existing `Options.flags`, `chksum` left out like the other sections until the test upload (T1 to T4 in `r1-m8-gstr1-export.md`). If the upload shows empty slots are required, the renderer writes all 12 slots; if it shows they are not, it writes only used ones. Default now: all 12, as the real file did.

## 4. Behaviour

### 4.1 Which documents are candidates for a return

Documents whose document date falls in the return period (period = document date, BUSINESS_RULES section 8), for the return's GSTIN, from `sales.v_filing_lines` (own live documents) and the uploaded-source lines the build already reads. Quarterly filers: the whole quarter including IFF months (IFF has no Table 13; `gstr1-examples.md` quarterly row; **[CA]** to confirm). Quarterly rendering is not built today (`NotRenderable`), so Table 13 follows when it is.

### 4.2 Natures

R1 emits only nature `1` (invoices for outward supply) and `5` (credit note). Debit notes (`4`) are not in the file today (the build counts them and blocks export), so they are added when debit notes are. Receipt, payment and refund vouchers and delivery challans (`2`, `3`, `6` to `12`) have no document in the app; they stay `docs: []`, and a seller who issued any must enter the row by hand (section 5.3).

### 4.3 Deriving suggested rows

For each (nature, series key) among candidates:
- series key = the number with its final run of digits removed, plus the length of that run (so `INV/26-27/0001` and `INV/26-27/001` are different series);
- `from` and `to` = the numbers with the lowest and highest numeric part, written exactly as stored (prefix kept, 16 characters at most);
- `totnum` = count of **distinct** numbers found (not `to - from + 1`);
- `cancel` = 0 for uploaded series (A4), audit-trail count for own live series;
- `net_issue` = `totnum - cancel`.

If `to - from + 1` is greater than the count found, the row carries a warning "N numbers in the range are not in your files": the person either enters them as cancelled or confirms a smaller count. The app does not decide.

Rows with a zero amount or a cancelled status that still carry a document number (Amazon `Cancel` and `FreeReplacement` in E-6 and E-7) belong in the series if the series is counted; the build thread must check whether the import keeps those numbers and, if not, raise it as an open question rather than dropping them silently.

### 4.4 Confirmation

Suggested and manual rows live in a new insert-only store per return instance (new rows per version, same pattern as `return_snapshots`; the build thread chooses names). Each version records nature, from, to, totnum, cancel, source (`own_live`, `uploaded_own`, `marketplace`, `manual`), the "count this series" flag, who confirmed and when, and an audit row `return.table13_confirmed`. A confirmation is tied to the build fingerprint: if documents in the period change after it, the confirmation is stale and the person confirms again (same rule as period confirmations). Tenant and role rules: `returns.prepare` to confirm; the business id comes from the path and is checked server side; another business's return is the same 404 as an unknown one.

### 4.5 C-08 (block)

C-08 fires when the return has data in Tables 4 to 10, 14 or 15 and the confirmed counted rows are empty, or the confirmation is stale. Level: block. Message in plain words: "The GST portal will not let you generate the summary until Table 13 (documents issued) is filled. Check the suggested rows below." A return with no data in those tables (nil) does not trigger it. C-08 is not a CA-check warning; it is a gate. Remove the `Table 13` entry from `NOT_IN_FILE` once built; Table 14 stays.

### 4.6 Export

`render_json` writes `doc_issue` after `hsn` and before `fil_dt`, matching the real file's key order. Rows are numbered `num` from 1 within each nature. Empty natures write `docs: []`. Large returns: Table 13 goes once, in the last file part, with the other summary sections (`gstr1-examples.md` L1). Table 13 rows count as line items toward the 10,000 limit. The snapshot's `docs` column (D-067) is written so a snapshot reproduces the full export.

### 4.7 Numbering switched on later

When live numbering is on (D-010 confirmed, `sales.finalize.live` true), own series come from `sales.documents` with cancelled counts from the audit trail and need no typing; typed rows remain only for documents issued outside the app. Switching changes only the row `source`; confirmed rows of earlier, locked returns are never edited.

## 5. Screen

5.1 A "Documents issued (Table 13)" step on the return page, before the export button, listing rows: nature, from, to, total, cancelled, net issued, source, a "Count this series" toggle (marketplace rows start off and say "Needs CA check"), and the gap warning.
5.2 Editing cancelled and total is allowed on suggested rows; from and to are editable only on manual rows. Net issued is read-only.
5.3 "Add a series" creates a manual row; validation as in section 6.
5.4 Export button stays disabled with the C-08 reason until confirmed. Words stay plain, no GST jargon beyond "documents issued".

## 6. Validation of a row (ours, not claimed to be the portal's)

- nature is one of the allowed codes; from and to non-empty, 16 characters at most, letters, digits, `-` and `/` only (FAQ Q31);
- `totnum >= 0`, `0 <= cancel <= totnum`, `net_issue = totnum - cancel`;
- `from` and `to` share the series prefix and width; numeric(to) >= numeric(from);
- no two rows of one nature in a return overlap in range (portal rule on duplicate series per GSTIN per FY is FAQ Q29; the exact portal check is unverified);
- a series number never appears under two natures in the same return (CA question 4 is open).

## 7. Acceptance criteria

AC1. A return with B2B, B2CS, CDNR or any Tables 4 to 10 data and no confirmed Table 13 rows has finding C-08 (block) and the export is refused with that reason.
AC2. A return with no data in Tables 4 to 10, 14 or 15 has no C-08 finding and no `doc_issue` rows required.
AC3. After confirmation, the JSON contains `doc_issue.doc_det` whose rows equal the confirmed rows, `net_issue = totnum - cancel` on every row, and the structure of section 2.
AC4. Practice documents never appear in suggestions, confirmed rows or the file; adding practice invoices changes nothing in Table 13.
AC5. Marketplace series are off by default, labelled "Needs CA check", and counted only when the person ticks them; ticking changes the fingerprint and the file.
AC6. Changing a document in the period after confirmation marks the confirmation stale and re-raises C-08.
AC7. Confirming or editing Table 13 writes an audit row and a new version; old versions are never changed or deleted.
AC8. A user without `returns.prepare`, or of another business, cannot read or write rows (404 or 403 as the rest of the filing API does); a client-supplied business or instance id is checked server side.
AC9. Repeating the same confirmation request is idempotent (same version returned).
AC10. A locked (filed) return serves its lock snapshot's Table 13 unchanged.
AC11. The screen no longer lists Table 13 as "enter on the portal" once built; Table 14 still is.
AC12. Money and counts use integers and Decimal only; no float anywhere in the build.

## 8. Test cases

Pure (no database): series key and range derivation for `INV/26-27/0001..0008` with one number missing (count 7, warning); two prefixes make two rows; mixed digit widths make two series; credit notes go to nature 5; 16-character limit and bad characters rejected; `cancel > totnum` rejected; overlapping ranges rejected; renderer golden test against the masked synthetic fixture `team/gst/fixtures/gstr1-offline-synthetic.json` (12 slots, key order, `net_issue`); rendering with empty natures.

Database-backed: practice documents excluded (AC4); marketplace row off by default and on after ticking (AC5); stale confirmation after a new document in the period (AC6); insert-only guard on the store (AC7); idempotent confirm (AC9); tenant isolation and role checks (AC8); snapshot `docs` equals the export (AC3, AC10); C-08 absent for a nil return (AC2).

Release gate (Pankaj): upload three files to an open, unfiled period with test numbers and no Submit: (a) Table 13 absent, to confirm the block; (b) Table 13 present, `chksum` omitted; (c) with and without empty slots. The result settles A6 and the unknowns in section 2.

## 9. Open questions with recommended defaults

| # | Question | Default (reversible) | Who |
|---|---|---|---|
| T13-1 | Do marketplace-issued series count in the seller's Table 13? | No by default, opt-in per series (A1, A2) | Human CA |
| T13-2 | Are `chksum`, flags and empty slots required in `doc_issue`? | Omit `chksum`; flags as tool; all 12 slots | Pankaj's test upload |
| T13-3 | Portal validations (totnum, overlap, nature codes) | Our own checks in section 6; do not claim them as portal rules | Test upload |
| T13-4 | Does Table 13 for a quarterly filer cover IFF months? | Yes, whole quarter | Human CA |
| T13-5 | Can a number be reused after cancel, and can one document count under two natures? | Never reuse; one nature per number | Human CA |
| T13-6 | Does the import keep numbers of zero-value and cancelled marketplace rows? | Build thread checks; if not, add before counting marketplace series | EM and build thread |
| T13-7 | Debit notes and other natures (vouchers, challans) | Out of R1; manual rows allowed | Later release |

No decision here needs Pankaj before the build starts. The test upload (T13-2, T13-3) needs him, and he already has it planned.

## 10. Files expected to change (build thread)

`filing/render_json.py`, `filing/export_model.py` (remove the Table 13 entry from `NOT_IN_FILE`), `filing/checks.py` (C-08), `filing/snapshots.py` (write `docs`), a new filing migration (insert-only Table 13 store), filing routes and `app/openapi.json` plus `web/src/api/schema.d.ts` (`make openapi`), the web return page, tests as in section 8, `docs/OPEN_QUESTIONS.md` and `docs/DECISIONS.md`.
