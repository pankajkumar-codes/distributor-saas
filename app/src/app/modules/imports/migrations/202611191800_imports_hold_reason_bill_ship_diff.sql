-- #345: one more reason a marketplace row can be held, where Bill To and Ship To are in different states so the place
-- of supply cannot be told from the report (`bill_ship_diff`, 14 characters, fits the existing varchar(20)).
-- Forward-only and additive: the check constraint is widened, no row changes.
alter table imports.import_rows drop constraint import_rows_hold_reason_check;
alter table imports.import_rows
    add constraint import_rows_hold_reason_check check (hold_reason in (
        'blank_hsn', 'blank_uqc', 'unknown_state', 'unknown_txn_type', 'blank_qty', 'sanity',
        'cashback_adjustment', 'price_adjustment', 'missing_original', 'number_format', 'pdf_unclear',
        'bill_ship_diff'));
