-- R2-M3: the stock ledger and the "selling price still needed" flag.
--
-- Stock is a ledger, not a number: every change to what a business holds is one row in
-- catalog.stock_movements, signed (in is positive, out is negative), insert-only (select and
-- insert are the only grants, and a trigger refuses update and delete from any role,
-- the owner included). The balance is always derived by summing a product's rows; no
-- balance is stored anywhere, so nothing can drift from the ledger. A mistake is
-- corrected by a later row that reverses it, never by editing or removing the old one.
--
-- Nothing here refuses a movement because stock would go below zero: a sale at zero stock
-- is warned about by the screens and never blocked (Pankaj, 2026-11-10), so the balance
-- may be negative and is shown as such.
--
-- kinds: purchase_in (a confirmed purchase line, once per source line), sale_out (written
-- by R2-M4's finalize, once per invoice line), adjustment (a count correction with a reason),
-- reversal (cancels exactly one earlier movement, with a reason).
--
-- Policies are LLD-0 §4.2's standard trio, as catalog's other tables. No foreign keys to other modules.

alter table catalog.products add column price_needed boolean not null default false;
comment on column catalog.products.price_needed is
    'R2-M3: true for a product created from a confirmed purchase line until the business sets its selling price per 1 qty.';

create table catalog.stock_movements (
    id uuid primary key,
    business_id uuid not null,
    product_id uuid not null,
    kind text not null check (kind in ('purchase_in', 'sale_out', 'adjustment', 'reversal')),
    quantity numeric(15, 3) not null check (quantity <> 0),   -- signed, in the product's unit (UQC)
    occurred_on date not null,
    source_type text check (source_type in ('purchase_invoice', 'sales_invoice')),
    source_id uuid,
    source_line_id uuid,
    unit_cost numeric(18, 2) check (unit_cost >= 0),          -- per 1 qty excl. GST; kept, not used for costing
    reverses_id uuid,
    reason text,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    unique (id, business_id),
    foreign key (product_id, business_id) references catalog.products (id, business_id),
    foreign key (reverses_id, business_id) references catalog.stock_movements (id, business_id),
    check ((kind = 'purchase_in' and quantity > 0 and source_type = 'purchase_invoice'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'sale_out' and quantity < 0 and source_type = 'sales_invoice'
                and source_id is not null and source_line_id is not null and reverses_id is null)
        or (kind = 'adjustment' and source_id is null and source_line_id is null and reverses_id is null
                and btrim(coalesce(reason, '')) <> '')
        or (kind = 'reversal' and source_id is null and source_line_id is null and reverses_id is not null
                and btrim(coalesce(reason, '')) <> ''))
);
-- A source line is received or sold once: a retry finds this row instead of adding another.
create unique index stock_movements_source_uq on catalog.stock_movements (business_id, source_type, source_id, source_line_id)
    where source_id is not null;
-- A movement is reversed at most once.
create unique index stock_movements_reverses_uq on catalog.stock_movements (business_id, reverses_id)
    where reverses_id is not null;
create index stock_movements_product on catalog.stock_movements (business_id, product_id, created_at, id);

create function catalog.stock_movements_insert_only() returns trigger
language plpgsql set search_path = pg_catalog, pg_temp as $$
begin
    raise exception 'catalog.stock_movements is insert-only: reverse a movement with a new row'
        using errcode = 'restrict_violation';
end
$$;
revoke all on function catalog.stock_movements_insert_only() from public;
create trigger stock_movements_no_change before update or delete on catalog.stock_movements
    for each row execute function catalog.stock_movements_insert_only();

alter table catalog.stock_movements enable row level security;
alter table catalog.stock_movements force row level security;
create policy tenant_rw on catalog.stock_movements to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.stock_movements for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.stock_movements for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on catalog.stock_movements to app_rw;
grant select on catalog.stock_movements to app_ro;
