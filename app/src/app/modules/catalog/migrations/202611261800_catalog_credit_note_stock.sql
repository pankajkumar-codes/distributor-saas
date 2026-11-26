-- Credit notes move stock (#456; GST CA expert 2026-11-26 on rule 56(2)): a goods-returned note puts the goods back
-- (return_in, positive, source type sales_credit_note) and, when the returned goods are written off, records that too
-- (written_off, negative, source type credit_note_write_off), each linked to the credit note line. The two source
-- types keep the existing one-movement-per-source-line index. Price or deficiency notes move nothing.
-- Additive: the kind, source type and shape checks gain the new values; every existing row still passes.
alter table catalog.stock_movements drop constraint stock_movements_kind_check;
alter table catalog.stock_movements add constraint stock_movements_kind_check
    check (kind in ('purchase_in', 'sale_out', 'adjustment', 'reversal', 'return_in', 'written_off'));
alter table catalog.stock_movements drop constraint stock_movements_source_type_check;
alter table catalog.stock_movements add constraint stock_movements_source_type_check
    check (source_type in ('purchase_invoice', 'sales_invoice', 'sales_credit_note', 'credit_note_write_off'));
alter table catalog.stock_movements drop constraint stock_movements_check;
alter table catalog.stock_movements add constraint stock_movements_check
    check ((kind = 'purchase_in' and quantity > 0 and source_type = 'purchase_invoice'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'sale_out' and quantity < 0 and source_type = 'sales_invoice'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'adjustment' and source_id is null and source_line_id is null and reverses_id is null
                and btrim(coalesce(reason, '')) <> '')
        or (kind = 'reversal' and source_id is null and source_line_id is null and reverses_id is not null
                and btrim(coalesce(reason, '')) <> '')
        or (kind = 'return_in' and quantity > 0 and source_type = 'sales_credit_note'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'written_off' and quantity < 0 and source_type = 'credit_note_write_off'
                and source_id is not null and source_line_id is not null and reverses_id is null));
