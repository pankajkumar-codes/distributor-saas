-- R1-M4 slice 2: two more reasons a row can be held, for Flipkart cash-back credit and debit notes
-- and Meesho price-adjustment rows (platform-reader-spec sections 3 and 4). Forward-only and additive:
-- the check constraint is widened, no row changes.
alter table imports.import_rows drop constraint import_rows_hold_reason_check;
alter table imports.import_rows
    add constraint import_rows_hold_reason_check check (hold_reason in (
        'blank_hsn', 'blank_uqc', 'unknown_state', 'unknown_txn_type', 'blank_qty', 'sanity',
        'cashback_adjustment', 'price_adjustment'));
