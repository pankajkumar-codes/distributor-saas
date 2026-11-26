-- Credit notes (#456, LLD-4 §5, CGST s.34 and Rule 53(1A)). Additive only.
--
-- - A practice credit note (Pankaj, 2026-11-26: practice notes on practice invoices, so the feature can be tried before
--   live numbering) has its own series kind, never the invoices' practice series.
-- - A goods-returned note says where the goods went (rule 56(2), GST CA expert 2026-11-26): back to stock, or written
--   off. Other notes move no stock. Kept on the draft and copied to the insert-only document.
-- - Remaining-to-credit per original line is read from document_lines.original_line_id; this index serves it.
alter table sales.number_series drop constraint number_series_kind_check;
alter table sales.number_series
    add constraint number_series_kind_check check (kind in ('invoice', 'credit_note', 'practice', 'practice_credit_note'));

alter table sales.drafts add column stock_treatment text check (stock_treatment in ('restock', 'write_off'));
alter table sales.documents add column stock_treatment text check (stock_treatment in ('restock', 'write_off'));

create index document_lines_original on sales.document_lines (business_id, original_line_id)
    where original_line_id is not null;
create index documents_original on sales.documents (business_id, original_document_id)
    where original_document_id is not null;

-- Two kinds of document never print the same number (Staff review of #463): one prefix per GSTIN and FY across kinds.
-- Month series carry the month in the prefix (INV/26-11/), so each month's row is its own prefix. allocate refuses a
-- reused prefix with a message first; this index stops a race between two kinds.
create unique index number_series_prefix_uq on sales.number_series (business_id, gstin, fy, lower(prefix));
