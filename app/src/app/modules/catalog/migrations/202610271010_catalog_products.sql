-- catalog schema, S3-a (LLD-3 §2, §14 step 1): products and their GST rate history.
-- Customers (S3-b) and the CSV import tables (S3-c) come in their own files.
--
-- Rate history is insert-only (L3-1, L3-2): product_rates, product_rate_voids and
-- product_rate_confirmations get SELECT and INSERT only, so no row is ever updated or
-- deleted. A rate's end is the next live row's valid_from, computed, never stored.
-- Products are never deleted either: delete is status = 'deleted' [RM43-1].
--
-- Policies are LLD-0 §4.2's standard trio written out, as business does, until
-- platform.apply_tenant_policies exists: tenant_rw (app_rw), tenant_read_ro (app_ro),
-- both off under a support grant, then support_read through support_grant_active.
-- No foreign keys to other modules (LLD-0 §7).

create schema if not exists catalog;
grant usage on schema catalog to app_rw, app_ro;

create table catalog.products (
    id uuid primary key,
    business_id uuid not null,
    code varchar(40) not null check (code = btrim(code) and code <> ''),
    name varchar(200) not null check (name = btrim(name) and name <> ''),
    hsn varchar(16) check (hsn ~ '^[0-9]+$'),  -- null = "Missing HSN"; shape from refdata hsn.pattern (service)
    uqc char(3) not null check (uqc ~ '^[A-Z]{3}$'),  -- in refdata.uqc_codes, checked in the service
    sale_rate numeric(18, 2) not null check (sale_rate >= 0),  -- per unit, excluding GST [RM43-3]
    barcode varchar(64) check (barcode = btrim(barcode) and barcode <> ''),
    tax_category text not null check (tax_category in ('taxable', 'exempt', 'nil_rated', 'non_gst')),
    has_cess boolean not null default false,
    status text not null default 'active' check (status in ('active', 'archived', 'deleted')),
    first_used_at timestamptz,             -- set once by catalog.interface.mark_used (L3-6)
    source_import_row_id uuid,             -- set when a CSV import created it (S3-c)
    version int not null default 1,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    updated_at timestamptz not null default now(),
    updated_by uuid not null,
    unique (id, business_id)               -- the target of the rate tables' composite keys
);
-- L3-7 with [RM43-1]: unique ignoring case among products not deleted (archived count).
create unique index products_code_uq on catalog.products (business_id, lower(code)) where status <> 'deleted';
create index products_code_prefix on catalog.products (business_id, lower(code) text_pattern_ops)
    where status <> 'deleted';  -- [RM43-9]: lower(code) like 'q%'
create unique index products_barcode_uq on catalog.products (business_id, lower(barcode))
    where barcode is not null and status = 'active';

create table catalog.product_rates (
    id uuid primary key,
    business_id uuid not null,
    product_id uuid not null,
    rate numeric(5, 2) not null check (rate > 0),  -- one of refdata gst.rate_values, checked in the service
    valid_from date not null,
    source text not null check (source in ('manual', 'csv_import')),
    source_import_row_id uuid,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    -- With business_id, so a rate can't point at another business's product: foreign
    -- key checks don't see row-level security.
    foreign key (product_id, business_id) references catalog.products (id, business_id),
    unique (id, business_id)
);
create index product_rates_product on catalog.product_rates (product_id, valid_from);

create table catalog.product_rate_voids (
    rate_id uuid primary key,
    business_id uuid not null,
    reason text not null check (btrim(reason) <> ''),
    created_at timestamptz not null default now(),
    created_by uuid not null,
    foreign key (rate_id, business_id) references catalog.product_rates (id, business_id)
);

create table catalog.product_rate_confirmations (
    id uuid primary key,
    business_id uuid not null,
    rate_id uuid not null,
    action text not null check (action in ('confirm', 'unconfirm')),
    note text,                             -- confirm: the owner's note; unconfirm: the reason
    created_at timestamptz not null default now(),
    created_by uuid not null,
    check (action = 'confirm' or btrim(coalesce(note, '')) <> ''),
    foreign key (rate_id, business_id) references catalog.product_rates (id, business_id)
);
create index product_rate_confirmations_rate on catalog.product_rate_confirmations (rate_id, created_at, id);

-- Row-level security, written out per table (no dynamic SQL; migrator.lint, migrator.checks).

alter table catalog.products enable row level security;
alter table catalog.products force row level security;
create policy tenant_rw on catalog.products to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.products for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.products for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table catalog.product_rates enable row level security;
alter table catalog.product_rates force row level security;
create policy tenant_rw on catalog.product_rates to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.product_rates for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.product_rates for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table catalog.product_rate_voids enable row level security;
alter table catalog.product_rate_voids force row level security;
create policy tenant_rw on catalog.product_rate_voids to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.product_rate_voids for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.product_rate_voids for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table catalog.product_rate_confirmations enable row level security;
alter table catalog.product_rate_confirmations force row level security;
create policy tenant_rw on catalog.product_rate_confirmations to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.product_rate_confirmations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.product_rate_confirmations for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

-- Grants: no DELETE anywhere; the three rate tables are insert-only (AC3-2).
grant select, insert, update on catalog.products to app_rw;
grant select, insert on catalog.product_rates, catalog.product_rate_voids, catalog.product_rate_confirmations
    to app_rw;
grant select on catalog.products, catalog.product_rates, catalog.product_rate_voids,
    catalog.product_rate_confirmations to app_ro;

-- Current rates [RM43-2]: a function, not a view, because the date comes from the
-- Python clock (no current_date in module SQL). Per product of the caller's business
-- (RLS applies: security invoker), the live rate row with the latest valid_from on or
-- before `on`, and whether its latest confirmation event is 'confirm'.
create function catalog.current_rates(p_on date)
returns table (product_id uuid, rate_id uuid, rate numeric, valid_from date, confirmed boolean)
language sql stable security invoker set search_path = pg_catalog, catalog, pg_temp as $$
    select distinct on (r.product_id)
           r.product_id, r.id, r.rate, r.valid_from,
           coalesce((select c.action = 'confirm' from catalog.product_rate_confirmations c
                     where c.rate_id = r.id order by c.created_at desc, c.id desc limit 1), false)
    from catalog.product_rates r
    where r.business_id = nullif(current_setting('app.tenant_id', true), '')::uuid  -- as well as RLS
      and r.valid_from <= p_on
      and not exists (select 1 from catalog.product_rate_voids v where v.rate_id = r.id)
    order by r.product_id, r.valid_from desc
$$;
revoke all on function catalog.current_rates(date) from public;
grant execute on function catalog.current_rates(date) to app_rw, app_ro;
