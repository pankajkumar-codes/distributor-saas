-- imports schema: staged marketplace report uploads (LLD-7 L7-1, L7-2).
-- Nothing here changes stock, money or a return; confirmed rows reach filing only
-- through the confirmed-document tables of slice S8.
--
-- Reshaped from #11's 0001_imports.sql before it was ever applied (LLD-7 L7-1):
-- business_id, the LLD-0 roles and policies, jsonb, and no raw cells for personal or
-- unmapped columns (the parser drops those before they reach this table).
-- Policies are the LLD-0 §4.2 standard pair written out, as identity's reshape does,
-- until platform.apply_tenant_policies exists; support_read follows with
-- platform.support_grant_active (S0a c2).

create schema if not exists imports;
grant usage on schema imports to app_rw, app_ro;

create table imports.import_runs (
    id uuid primary key,
    business_id uuid not null,
    marketplace varchar(20) not null,
    report_type varchar(20) not null,
    profile_id varchar(120) not null,
    profile_verified boolean not null,
    filename varchar(255) not null,
    checksum_sha256 char(64) not null,
    sheet varchar(100),
    header_row_number integer not null,
    status varchar(20) not null default 'staged' check (status in ('staged','confirmed','discarded')),
    -- Counts and column names only, never cell values.
    summary jsonb not null default '{}',
    uploaded_by uuid not null,
    uploaded_at timestamptz not null default now(),
    confirmed_by uuid,
    confirmed_at timestamptz,
    unique (id, business_id)
);
-- The same bytes for the same report type are one live run, however often uploaded.
-- A discarded run frees the file to be staged again.
create unique index import_runs_one_live_per_file on imports.import_runs
    (business_id, marketplace, report_type, checksum_sha256) where status <> 'discarded';
create index import_runs_business_uploaded on imports.import_runs (business_id, uploaded_at desc);

create table imports.import_rows (
    id uuid primary key,
    run_id uuid not null,
    business_id uuid not null,
    row_number integer not null,
    status varchar(20) not null check (status in ('new','already_imported','changed','duplicate','conflict','invalid')),
    -- Only the profile's mapped, non-personal cells, exactly as the file had them.
    raw jsonb not null,
    normalized jsonb,
    errors jsonb not null default '[]',
    -- The profile's key fields as a JSON array (readable, for the confirm step)
    -- and their sha256, which is what lookups use.
    dedup_values jsonb,
    dedup_key char(64),
    content_hash char(64),
    unique (run_id, row_number),
    -- A row can only belong to a run of its own business.
    foreign key (run_id, business_id) references imports.import_runs (id, business_id)
);
-- Finds earlier confirmed rows for the same source record across files.
create index import_rows_business_dedup on imports.import_rows (business_id, dedup_key) where dedup_key is not null;

-- A run moves only staged -> confirmed or staged -> discarded, and records who confirmed
-- it only then. Without this, app_rw could turn a confirmed run back to discarded and so
-- re-open its rows for a later import.
create function imports.guard_run_transition() returns trigger
language plpgsql set search_path = imports, pg_temp as $$
begin
    if new.status is distinct from old.status
       and not (old.status = 'staged' and new.status in ('confirmed', 'discarded')) then
        raise exception 'import run % cannot move from % to %', old.id, old.status, new.status
            using errcode = 'check_violation';
    end if;
    if (new.confirmed_by is distinct from old.confirmed_by or new.confirmed_at is distinct from old.confirmed_at)
       and not (old.status = 'staged' and new.status = 'confirmed') then
        raise exception 'confirmed_by and confirmed_at are set only when a run is confirmed'
            using errcode = 'check_violation';
    end if;
    return new;
end $$;
revoke all on function imports.guard_run_transition() from public;
create trigger guard_run_transition before update on imports.import_runs
    for each row execute function imports.guard_run_transition();

alter table imports.import_runs enable row level security;
alter table imports.import_runs force row level security;
alter table imports.import_rows enable row level security;
alter table imports.import_rows force row level security;

-- Runs: read, insert, and the status change at confirm or discard (column grant below).
create policy tenant_rw on imports.import_runs to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null)
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null);
create policy tenant_read_ro on imports.import_runs for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null);

-- Rows are insert-only: the record of what the file said.
create policy tenant_select on imports.import_rows for select to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null);
create policy tenant_insert on imports.import_rows for insert to app_rw
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null);
create policy tenant_read_ro on imports.import_rows for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and nullif(current_setting('app.support_grant_id', true), '') is null);

grant select, insert on imports.import_runs, imports.import_rows to app_rw;
-- A run only moves staged -> confirmed | discarded; nothing else on it changes.
grant update (status, confirmed_by, confirmed_at) on imports.import_runs to app_rw;
grant select on imports.import_runs, imports.import_rows to app_ro;
