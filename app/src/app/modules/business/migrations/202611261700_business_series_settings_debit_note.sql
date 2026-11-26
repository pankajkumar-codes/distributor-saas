-- #461: the numbering settings screen keeps a prefix for each document type the seller numbers: tax invoices, credit
-- notes and debit notes (CGST Rule 53(1A)(c): each in its own series). Debit notes are not issued by the app yet; their
-- prefix is kept for when they are, and for the seller's Table 13 row meanwhile. Additive: the kind check gains one
-- value, and no existing row changes.
alter table business.series_settings drop constraint series_settings_kind_check;
alter table business.series_settings
    add constraint series_settings_kind_check check (kind in ('invoice', 'credit_note', 'debit_note'));
