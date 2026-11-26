-- #450: the invoice PDF prints each line's MRP and, for a percent discount, the percent. Both are snapshotted at
-- finalize from the product and the draft line, so a later MRP change never alters an issued invoice (CLAUDE.md 9).
-- Nullable, no backfill: documents finalized before this migration never stored them and print "-" (an MRP read
-- from today's product would not be what the invoice was issued with). Insert-only stays as it was.
alter table sales.document_lines
    add column mrp numeric(18, 2) check (mrp >= 0),
    add column discount_percent numeric(5, 2) check (discount_percent >= 0 and discount_percent <= 100);
