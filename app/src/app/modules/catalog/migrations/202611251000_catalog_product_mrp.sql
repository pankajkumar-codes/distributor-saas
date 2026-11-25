-- #398 (mocks v16, D-104): the optional MRP (maximum retail price) of a product, per 1 qty, in
-- rupees. Display only: it is shown on the product and on the invoice line, and never feeds
-- taxable value or tax, which still come from the line's rate (tax-inclusive pricing stays
-- out of scope, OPEN_QUESTIONS CA-5). Additive and nullable: no backfill, no row rewritten.
alter table catalog.products add column mrp numeric(14, 2) check (mrp >= 0);
comment on column catalog.products.mrp is
    'Optional MRP per 1 qty in rupees, 2 decimals, display only (D-104); null when not set.';
