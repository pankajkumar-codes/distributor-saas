-- imports schema: staged marketplace report uploads. Applied by the migrator Lambda.
-- Nothing here changes stock or money; confirmed rows are handed to commerce later.
create schema if not exists imports;

create table imports.import_runs (
    id uuid primary key,
    tenant_id uuid not null,
    marketplace varchar(20) not null,
    report_type varchar(20) not null,
    profile_id varchar(120) not null,
    profile_verified boolean not null,
    filename varchar(255) not null,
    checksum_sha256 char(64) not null,
    sheet varchar(100),
    header_row_number integer not null,
    status varchar(20) not null default 'staged' check (status in ('staged','confirmed','discarded')),
    summary json not null default '{}',
    uploaded_by varchar(128) not null,
    uploaded_at timestamptz not null default now(),
    confirmed_by varchar(128),
    confirmed_at timestamptz,
    unique (id, tenant_id)
);
-- The same bytes for the same report type are one live run, however often uploaded.
-- A discarded run frees the file to be staged again.
create unique index import_runs_one_live_per_file on imports.import_runs
    (tenant_id, marketplace, report_type, checksum_sha256) where status <> 'discarded';
create index on imports.import_runs (tenant_id, uploaded_at desc);

create table imports.import_rows (
    id uuid primary key,
    run_id uuid not null,
    tenant_id uuid not null,
    row_number integer not null,
    status varchar(20) not null check (status in ('new','already_imported','changed','duplicate','conflict','invalid')),
    raw json not null,
    normalized json,
    errors json not null default '[]',
    -- The profile's key fields as a JSON array (readable, for the commerce handoff)
    -- and their sha256, which is what lookups use.
    dedup_values json,
    dedup_key char(64),
    content_hash char(64),
    unique (run_id, row_number),
    -- A row can only belong to a run of its own tenant.
    foreign key (run_id, tenant_id) references imports.import_runs (id, tenant_id)
);
-- Finds earlier confirmed rows for the same source record across files.
create index on imports.import_rows (tenant_id, dedup_key) where dedup_key is not null;

do $$ begin
    if not exists (select from pg_roles where rolname = 'svc_imports') then
        create role svc_imports login;
    end if;
end $$;
grant rds_iam to svc_imports;
grant usage on schema imports to svc_imports;
-- Rows are never edited once staged; a run only moves staged -> confirmed/discarded.
grant select, insert on imports.import_runs, imports.import_rows to svc_imports;
grant update (status, confirmed_by, confirmed_at) on imports.import_runs to svc_imports;

-- Defense in depth: the service sets app.tenant_id per transaction only after it has
-- checked the caller's membership (shared tenant dependency, plan task T-001).
alter table imports.import_runs enable row level security;
alter table imports.import_rows enable row level security;
create policy tenant_runs on imports.import_runs to svc_imports
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy tenant_rows on imports.import_rows to svc_imports
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
