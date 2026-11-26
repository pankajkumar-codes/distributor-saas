-- More goods sent than invoiced (#456 part 3): a debit note by quantity takes the extra goods out of stock, one
-- negative sale_out movement linked to the debit note line (source type sales_debit_note). Value-only debit notes move
-- nothing. Additive: the source type and shape checks gain the new value; every existing row still passes.
alter table catalog.stock_movements drop constraint stock_movements_source_type_check;
alter table catalog.stock_movements add constraint stock_movements_source_type_check
    check (source_type in ('purchase_invoice', 'sales_invoice', 'sales_credit_note', 'credit_note_write_off',
                           'sales_debit_note'));
alter table catalog.stock_movements drop constraint stock_movements_check;
alter table catalog.stock_movements add constraint stock_movements_check
    check ((kind = 'purchase_in' and quantity > 0 and source_type = 'purchase_invoice'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'sale_out' and quantity < 0 and source_type in ('sales_invoice', 'sales_debit_note')
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'adjustment' and source_id is null and source_line_id is null and reverses_id is null
                and btrim(coalesce(reason, '')) <> '')
        or (kind = 'reversal' and source_id is null and source_line_id is null and reverses_id is not null
                and btrim(coalesce(reason, '')) <> '')
        or (kind = 'return_in' and quantity > 0 and source_type = 'sales_credit_note'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'written_off' and quantity < 0 and source_type = 'credit_note_write_off'
                and source_id is not null and source_line_id is not null and reverses_id is null));
