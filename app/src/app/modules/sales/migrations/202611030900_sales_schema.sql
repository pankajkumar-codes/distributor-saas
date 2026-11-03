-- sales schema, S4-a (LLD-4 §2.1, §2.2, §14 step 1): mutable drafts and the number series.
-- Documents, payments and share links come with later slices, each in its own file.
--
-- Drafts are not GST records (LLD-4 §2.1): an open draft can be edited and hard-deleted,
-- so app_rw gets update and delete on drafts and draft_lines. `version` is the If-Match token.
--
-- number_series: the numbering scope lives in ONE place, the unique constraint below
-- (business, GSTIN, kind, FY; the prefix is fixed for the FY, L4-2). PENDING APPROVAL:
-- invoice-numbering scope is an approval gate (CLAUDE.md) for the owner and the CA. This
-- file only creates the empty table; no code allocates numbers until the scope is approved.
-- app_rw may only advance next_value (column grant).
--
-- Policies are LLD-0 §4.2's standard trio written out per table (migrator.lint).
-- No foreign keys to other modules (LLD-0 §7): customer_id, product_id and the
-- original_* ids are checked in the service through the catalog and documents interfaces.

create schema if not exists sales;
grant usage on schema sales to app_rw, app_ro;

create table sales.drafts (
    id uuid primary key,
    business_id uuid not null,
    kind text not null check (kind in ('invoice', 'credit_note')),
    status text not null default 'open' check (status in ('open', 'finalized')),
    version int not null default 1,
    customer_id uuid,                      -- null = cash sale
    cash_buyer jsonb,                      -- {name?, state_code, address?}
    bill_to jsonb,
    ship_to jsonb,
    ship_to_third_party boolean not null default false,
    doc_date date,
    invoice_discount numeric(18, 2) not null default 0 check (invoice_discount >= 0),
    charges jsonb not null default '[]',   -- [{label, amount: "150.00"}], amounts as strings
    eway jsonb,
    pos_override char(2),
    pos_override_reason text,
    original_document_id uuid,             -- credit notes
    reason_code text,
    s34_override_reason text,
    copied_from_document_id uuid,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    updated_at timestamptz not null default now(),
    updated_by uuid not null,
    check (pos_override is null or btrim(coalesce(pos_override_reason, '')) <> ''),
    unique (id, business_id)
);
create index drafts_business_open on sales.drafts (business_id, kind, updated_at desc, id)
    where status = 'open';

create table sales.draft_lines (
    id uuid primary key,
    business_id uuid not null,
    draft_id uuid not null,
    line_no int not null check (line_no > 0),
    product_id uuid,                       -- invoices
    original_line_id uuid,                 -- credit notes
    quantity numeric(18, 3) check (quantity > 0),
    unit_price numeric(18, 2) check (unit_price >= 0),
    discount_kind text check (discount_kind in ('amount', 'percent')),
    discount_value numeric(18, 2) check (discount_value >= 0),
    credit_taxable numeric(18, 2) check (credit_taxable >= 0),  -- credit note by value
    check ((discount_kind is null) = (discount_value is null)),
    foreign key (draft_id, business_id) references sales.drafts (id, business_id) on delete cascade,
    unique (draft_id, line_no)
);

create table sales.number_series (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    kind text not null check (kind in ('invoice', 'credit_note', 'practice')),
    fy char(7) not null check (fy ~ '^[0-9]{4}-[0-9]{2}$'),
    prefix text not null,
    width smallint not null check (width between 1 and 16),
    next_value int not null check (next_value >= 1),
    created_at timestamptz not null default now(),
    unique (business_id, gstin, kind, fy)  -- THE numbering scope (L4-2), pending approval
);

alter table sales.drafts enable row level security;
alter table sales.drafts force row level security;
create policy tenant_rw on sales.drafts to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.drafts for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.drafts for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table sales.draft_lines enable row level security;
alter table sales.draft_lines force row level security;
create policy tenant_rw on sales.draft_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.draft_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.draft_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table sales.number_series enable row level security;
alter table sales.number_series force row level security;
create policy tenant_rw on sales.number_series to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.number_series for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.number_series for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

-- A number is never issued twice: next_value can only go up, even for the one column app_rw
-- may update. Allocation (not built yet, pending the numbering-scope approval) sets it to
-- next_value + 1 and cannot go back.
create function sales.guard_series_forward() returns trigger
language plpgsql as $$
begin
    if new.next_value < old.next_value then
        raise exception 'number series % cannot go back from % to %', old.id, old.next_value, new.next_value
            using errcode = 'SNS01';
    end if;
    return new;
end
$$;
create trigger series_only_forward before update on sales.number_series
    for each row execute function sales.guard_series_forward();

-- Grants: drafts are mutable and deletable while open; the series only ever advances.
grant select, insert, update, delete on sales.drafts, sales.draft_lines to app_rw;
grant select on sales.drafts, sales.draft_lines, sales.number_series to app_ro;
grant select, insert, update (next_value) on sales.number_series to app_rw;
