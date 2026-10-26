-- business schema, S1-d1 (LLD-1 §4): the business and filing profile a new business
-- starts with. Branding and series settings come with S4 (EM, 2026-10-26).
--
-- Policies are LLD-0 §4.2's standard pair written out, as identity and imports do,
-- until platform.apply_tenant_policies exists: tenant_rw (app_rw) and tenant_read_ro
-- (app_ro), both refusing a request that carries a support grant id, then support_read
-- (select only) through platform.support_grant_active. profiles also gets
-- profile_card_ro so /me/businesses can show each business's name and GSTIN without
-- binding a tenant (LLD-1 §4, §8.2).
--
-- No foreign keys to identity: a module reads another's tables only through its
-- interface (LLD-0 §7). The business row and its profile are written in one
-- transaction by identity.interface.create_business (LLD-1 §5.10).

create schema if not exists business;
grant usage on schema business to app_rw, app_ro;

create table business.profiles (
    business_id uuid primary key,
    legal_name text,                      -- required before the first PDF or export (ON-3), not at creation
    trade_name text,
    registration_kind text not null check (registration_kind in ('gstin', 'enrolment')),
    gstin char(15) check (gstin ~ '^[0-9]{2}[0-9A-Z]{10}[1-9A-Z][0-9A-Z][0-9A-Z]$'),
    enrolment_number text check (enrolment_number = btrim(enrolment_number) and enrolment_number <> ''),
    state_code char(2) not null check (state_code ~ '^[0-9]{2}$'),
    gstin_locked_at timestamptz,          -- L1-14
    address_line1 text,
    address_line2 text,
    city text,
    pin char(6) check (pin ~ '^[0-9]{6}$'),
    address_state_code char(2) check (address_state_code ~ '^[0-9]{2}$'),
    einvoice_history text check (einvoice_history in ('no', 'yes', 'not_sure')),
    marketplaces_answered_at timestamptz,
    updated_at timestamptz not null default now(),
    updated_by uuid not null,
    check ((registration_kind = 'gstin') = (gstin is not null)),
    check ((registration_kind = 'enrolment') = (enrolment_number is not null)),
    -- A GSTIN's own state; an enrolment's state is the one the user chose.
    check (gstin is null or state_code = left(gstin, 2))
);

create table business.turnover_bands (
    business_id uuid not null,
    fy char(7) not null check (fy ~ '^[0-9]{4}-[0-9]{2}$'),          -- '2026-27'
    band text not null check (band in ('up_to_threshold', 'above_threshold')),  -- threshold from refdata
    declared_turnover numeric(18, 2) check (declared_turnover >= 0),  -- optional, for the AI-4 nudge
    set_at timestamptz not null default now(),
    set_by uuid not null,
    primary key (business_id, fy)
);

-- Insert-only history (L1-13): app_rw has no UPDATE or DELETE on it.
create table business.filing_frequency_history (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    frequency text not null check (frequency in ('monthly', 'quarterly')),
    effective_from date not null
        check (extract(day from effective_from) = 1 and extract(month from effective_from) in (1, 4, 7, 10)),
    warnings text[] not null default '{}',
    chosen_at timestamptz not null default now(),
    chosen_by uuid not null
);
create index filing_frequency_history_lookup
    on business.filing_frequency_history (business_id, gstin, effective_from, chosen_at desc);

create table business.marketplace_channels (
    business_id uuid not null,
    marketplace text not null check (marketplace in ('amazon', 'flipkart', 'meesho')),
    enabled boolean not null,
    changed_at timestamptz not null default now(),
    changed_by uuid not null,
    primary key (business_id, marketplace)
);

-- Row-level security -----------------------------------------------------------------
-- `tenant` = nullif(current_setting('app.tenant_id', true), '')::uuid and
-- `not support` = coalesce(current_setting('app.support_grant_id', true), '') = ''.

alter table business.profiles enable row level security;
alter table business.profiles force row level security;
alter table business.turnover_bands enable row level security;
alter table business.turnover_bands force row level security;
alter table business.filing_frequency_history enable row level security;
alter table business.filing_frequency_history force row level security;
alter table business.marketplace_channels enable row level security;
alter table business.marketplace_channels force row level security;

create policy tenant_rw on business.profiles to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on business.profiles for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on business.profiles for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
create policy profile_card_ro on business.profiles for select to app_ro
    using (identity.is_active_member(business_id)
           and coalesce(current_setting('app.support_grant_id', true), '') = '');

create policy tenant_rw on business.turnover_bands to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on business.turnover_bands for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on business.turnover_bands for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

create policy tenant_rw on business.filing_frequency_history to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on business.filing_frequency_history for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on business.filing_frequency_history for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

create policy tenant_rw on business.marketplace_channels to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on business.marketplace_channels for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on business.marketplace_channels for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

-- Grants: no DELETE anywhere; the frequency history is insert-only.
grant select, insert, update on business.profiles, business.turnover_bands, business.marketplace_channels to app_rw;
grant select, insert on business.filing_frequency_history to app_rw;
grant select on business.profiles, business.turnover_bands, business.filing_frequency_history,
    business.marketplace_channels to app_ro;
