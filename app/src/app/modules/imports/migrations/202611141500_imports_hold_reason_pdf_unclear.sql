-- R1-M6 slice 2b: one more reason a row can be held, for an own-invoice line read from a PDF where some detail could
-- not be read (`pdf_unclear`, 11 characters, fits the existing varchar(20)). Forward-only and additive: the check
-- constraint is widened, no row changes.
alter table imports.import_rows drop constraint import_rows_hold_reason_check;
alter table imports.import_rows
    add constraint import_rows_hold_reason_check check (hold_reason in (
        'blank_hsn', 'blank_uqc', 'unknown_state', 'unknown_txn_type', 'blank_qty', 'sanity',
        'cashback_adjustment', 'price_adjustment', 'missing_original', 'number_format', 'pdf_unclear'));
