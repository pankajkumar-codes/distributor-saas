-- business.series_settings (LLD-1 §4, used from S4): each kind's number prefix, width and
-- first value, and whether the business still issues practice documents (BH-5). sales owns
-- number_series and copies these into a series row at the FY's first finalize (LLD-4
-- L4-2), so a later change applies from the next FY's series.
--
-- F1 (S5) only reads this table: no row, or practice_mode true, means practice. The
-- settings screen that writes it (and the switch to live numbering) comes with live
-- finalize.

create table business.series_settings (
    business_id uuid not null,
    kind text not null check (kind in ('invoice', 'credit_note')),
    prefix text not null,
    width smallint not null check (width between 1 and 10),
    first_value int not null default 1 check (first_value >= 1),
    practice_mode boolean not null default true,  -- BH-5: practice until the owner switches live
    updated_at timestamptz not null default now(),
    updated_by uuid not null,
    primary key (business_id, kind)
);

alter table business.series_settings enable row level security;
alter table business.series_settings force row level security;
create policy tenant_rw on business.series_settings to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on business.series_settings for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on business.series_settings for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert, update (prefix, width, first_value, practice_mode, updated_at, updated_by)
    on business.series_settings to app_rw;
grant select on business.series_settings to app_ro;
