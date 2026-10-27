-- catalog.customers, S3-b (LLD-3 §2, §6.2). Buyer business data: LLD-6's closure rule
-- deletes it with the business (retention), so no other table keys onto it here.
--
-- GSTIN is stored normalised (trim, upper, no spaces) and only after gstin.md's checks
-- in the service; its state code is derived from digits 1-2, never typed. State codes
-- are checked against refdata.state_codes in the service (no cross-schema keys, LLD-0 §7).
-- Delete is status = 'deleted' while never used [RM43-1]; there is no DELETE grant.

create table catalog.customers (
    id uuid primary key,
    business_id uuid not null,
    name varchar(200) not null check (name = btrim(name) and name <> ''),
    gstin char(15) check (gstin ~ '^[0-9]{2}[0-9A-Z]{13}$'),  -- null = unregistered
    gstin_state_code char(2),
    billing_line1 varchar(200),
    billing_line2 varchar(200),
    billing_city varchar(100),
    billing_pin char(6) check (billing_pin ~ '^[0-9]{6}$'),  -- shape from refdata address.pin_pattern (service)
    billing_state_code char(2) not null check (billing_state_code ~ '^[0-9]{2}$'),  -- BH-3
    delivery_same_as_billing boolean not null default true,
    delivery_line1 varchar(200),
    delivery_line2 varchar(200),
    delivery_city varchar(100),
    delivery_pin char(6) check (delivery_pin ~ '^[0-9]{6}$'),
    delivery_state_code char(2) check (delivery_state_code ~ '^[0-9]{2}$'),
    credit_days int not null default 0 check (credit_days >= 0),  -- upper bound from refdata
    status text not null default 'active' check (status in ('active', 'archived', 'deleted')),
    first_used_at timestamptz,             -- set once by catalog.interface.mark_used (L3-6)
    version int not null default 1,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    updated_at timestamptz not null default now(),
    updated_by uuid not null,
    check ((gstin is null) = (gstin_state_code is null)),
    check (gstin is null or gstin_state_code = left(gstin, 2)),
    -- One address or two, never a half-filled second one beside "same as billing".
    check (case when delivery_same_as_billing
                then num_nonnulls(delivery_line1, delivery_line2, delivery_city, delivery_pin,
                                  delivery_state_code) = 0
                else delivery_state_code is not null end)
);
create index customers_name_trgm on catalog.customers using gin (name gin_trgm_ops);
create index customers_gstin on catalog.customers (business_id, gstin) where gstin is not null;
create index customers_list on catalog.customers (business_id, lower(name), id) where status <> 'deleted';

alter table catalog.customers enable row level security;
alter table catalog.customers force row level security;
create policy tenant_rw on catalog.customers to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.customers for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.customers for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert, update on catalog.customers to app_rw;
grant select on catalog.customers to app_ro;
