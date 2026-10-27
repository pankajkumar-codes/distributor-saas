# Reference data (LLD-0 §6)

Dated, cited rules that code reads instead of hard-coding: limits, thresholds,
character sets, the H-2 treatment, GST state codes and, later, template files. The
migrator loads these files after the SQL migrations on every run
(`migrator/migrator/refdata.py`); modules read them with
`app.modules.refdata.value_on(tx, key, on)` and `state_name(tx, code, on)`.

## Files

- `values/*.yaml`: one list of scalar rules per area. Every entry has `key`, `value`
  (always a quoted string), `type` (`integer`, `decimal`, `text`, `boolean`, `pattern`,
  `enum` with `allowed`), `kind` (`tax` or `product`), `valid_from`, optional
  `valid_to`, `source_url`, `source_title`, `last_checked`, `status`, optional `note`,
  and `confirmed_by` / `confirmed_on` once confirmed.
- `state_codes.yaml`: GST state and UT codes, with the same date and source fields.
- `templates/index.yaml`: one entry per file in `templates/`, checked by SHA-256.

## Rules

- **Cite every row; invent nothing.** `source_url` is an `https://` link, or a
  `team/` path for a decision recorded only in the project's documents (the BRD
  link is used for BRD rows). Tax rows come from the GST expert's documents.
- **Status.** Everything starts `provisional`. Product rows are confirmed by the PO
  (`po_confirmed`); tax rows by the GST expert or the CA (`expert_confirmed`,
  `ca_confirmed`). QA's release checklist lists every provisional row a release reads.
- **A confirmation names who and when.** Any status but `provisional` needs
  `confirmed_by` (the person or role and where they said it, e.g. `"GST expert, CA-1
  answer"`) and `confirmed_on` (a date, not in the future); a provisional row has
  neither. The loader and a database constraint both refuse anything else, so the row
  itself records who let `require_confirmed` pass (D-038).
- **Never edit a value.** A loaded `(key, valid_from)` row keeps its value, type and
  kind. To change a value, add an entry with a later `valid_from`; the loader closes
  the old row there. Only `last_checked`, `status`, `source_url`, `source_title`,
  `note`, `confirmed_by` and `confirmed_on` may be updated in place. Removing a loaded entry is refused.
- **No defaults.** A date no row covers raises `RefdataMissing`.

## Checking

    cd migrator && python -m migrator.refdata check ../refdata

CI runs this in the `refdata` job, and the migrator job's tests load the files into
PostgreSQL (`migrator/tests/test_refdata.py`).
