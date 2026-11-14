-- R1-M5 slice 1: two more reasons a row can be held, for the seller's own invoices (a credit or debit note
-- with no original invoice number; a document number that does not fit the usual shape). Forward-only and
-- additive: the check constraint is widened (both names fit the existing varchar(20)), no row changes.
alter table imports.import_rows drop constraint import_rows_hold_reason_check;
alter table imports.import_rows
    add constraint import_rows_hold_reason_check check (hold_reason in (
        'blank_hsn', 'blank_uqc', 'unknown_state', 'unknown_txn_type', 'blank_qty', 'sanity',
        'cashback_adjustment', 'price_adjustment', 'missing_original', 'number_format'));
