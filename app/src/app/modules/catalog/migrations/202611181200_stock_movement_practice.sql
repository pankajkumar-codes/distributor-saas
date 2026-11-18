-- R2-M4 follow-up (CEO, 2026-11-18): a practice invoice takes stock out like any other (the goods
-- really left), and its sale_out movement says so, so practice sales can be filtered or
-- reversed later. Additive, with a constant default: every existing row is a real movement
-- and no row is rewritten (the ledger stays insert-only).
alter table catalog.stock_movements add column is_practice boolean not null default false;
comment on column catalog.stock_movements.is_practice is
    'true on a sale_out written by a practice-numbered invoice (R2-M4); false everywhere else.';
