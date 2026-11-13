-- R1-M3 slice 2: a run knows the upload and the seller GSTIN it came from, and a row can be
-- held (a reason, never dropped) or skipped for a zero value (LLD-7 §3 steps 4-5).
-- Forward-only and additive. Rows stay insert-only; the run's new columns are written once,
-- at insert, so no new update grant.

alter table imports.import_runs
    add column upload_id uuid references imports.uploads (id),
    add column gstin char(15);
create index import_runs_upload on imports.import_runs (upload_id) where upload_id is not null;

alter table imports.import_rows drop constraint import_rows_status_check;
alter table imports.import_rows
    add constraint import_rows_status_check check (status in
        ('new', 'already_imported', 'changed', 'duplicate', 'conflict', 'invalid', 'held', 'skipped_zero')),
    add column hold_reason varchar(20)
        check (hold_reason in ('blank_hsn', 'blank_uqc', 'unknown_state', 'unknown_txn_type', 'blank_qty', 'sanity')),
    add constraint import_rows_hold_reason_with_held check ((status = 'held') = (hold_reason is not null));
