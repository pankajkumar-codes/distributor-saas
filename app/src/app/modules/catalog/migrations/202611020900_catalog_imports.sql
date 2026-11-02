-- Product CSV import, S3-c1 (LLD-3 §7.2): one run per uploaded file, one row per data row.
-- Neither table is a GST record. import_runs keeps a status; import_rows is written by the
-- parse and only its outcome is set, once, by the apply. LLD-6's retention rule deletes
-- both after refdata catalog.import.keep_days; no DELETE grant here.
--
-- Deviations from LLD-3 §7.2, for §7.3 and §7.4's rules: import_rows carries the code it
-- matched on (code_key), the product version it was compared against (compared_version,
-- RM43-6), and an outcome (applied, stale or skipped) instead of a bare applied flag, so
-- the run can report stale rows. import_runs records the run it duplicates or that
-- superseded it, and a failure's error code.

create table catalog.import_runs (
    id uuid primary key,
    business_id uuid not null,
    file_name text not null check (file_name <> '' and length(file_name) <= 255),
    s3_key text not null,
    sha256 char(64) check (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes int check (size_bytes > 0),
    status text not null default 'awaiting_upload'
        check (status in ('awaiting_upload', 'parsing', 'preview', 'applying', 'applied', 'discarded', 'failed')),
    counts jsonb,                      -- per row status and outcome; numbers only
    error_code text,                   -- why a parse or apply failed, or why the file was refused
    error_message text,
    duplicate_of uuid,                 -- discarded: the same file was already applied by this run [RM43-5]
    superseded_by uuid,                -- discarded: a later upload of the same file replaced this preview
    apply_changes boolean,
    confirmed_by uuid,
    confirmed_at timestamptz,
    created_at timestamptz not null default now(),
    created_by uuid not null,
    updated_at timestamptz not null default now(),
    version int not null default 1,
    unique (id, business_id),
    foreign key (duplicate_of, business_id) references catalog.import_runs (id, business_id),
    foreign key (superseded_by, business_id) references catalog.import_runs (id, business_id)
);
-- [RM43-5] one applied (or applying) run per file per business.
create unique index import_runs_live_checksum on catalog.import_runs (business_id, sha256)
    where status in ('applying', 'applied');
-- At most one open preview per file per business: a new upload supersedes the old one.
create unique index import_runs_open_preview on catalog.import_runs (business_id, sha256)
    where status = 'preview';
create index import_runs_list on catalog.import_runs (business_id, created_at desc);

create table catalog.import_rows (
    id uuid primary key,
    business_id uuid not null,
    run_id uuid not null,
    row_number int not null check (row_number > 1),   -- the file's line or sheet row; 1 is the header
    code_key text,                     -- lower(trim(code)) when the row has a code
    parsed jsonb not null,             -- the row's values after parsing (a product file holds no personal data)
    status text not null check (status in ('new', 'changed', 'unchanged', 'invalid', 'conflict')),
    product_id uuid,                   -- changed, unchanged: the product compared against
    compared_version int,              -- that product's version at parse time [RM43-6]
    diff jsonb,                        -- changed: [{field, saved, file}]
    errors jsonb,                      -- invalid, conflict: [{field, code, message}]
    outcome text check (outcome in ('applied', 'stale', 'skipped')),   -- set once by the apply
    unique (run_id, row_number),
    foreign key (run_id, business_id) references catalog.import_runs (id, business_id),
    check ((status in ('changed', 'unchanged')) = (product_id is not null and compared_version is not null))
);
create index import_rows_status on catalog.import_rows (run_id, status, row_number);

alter table catalog.import_runs enable row level security;
alter table catalog.import_runs force row level security;
create policy tenant_rw on catalog.import_runs to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.import_runs for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.import_runs for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table catalog.import_rows enable row level security;
alter table catalog.import_rows force row level security;
create policy tenant_rw on catalog.import_rows to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on catalog.import_rows for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on catalog.import_rows for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert, update on catalog.import_runs to app_rw;
grant select, insert on catalog.import_rows to app_rw;
grant update (outcome) on catalog.import_rows to app_rw;
grant select on catalog.import_runs, catalog.import_rows to app_ro;

-- products.source_import_row_id (S3-a) points at an import_rows id with no foreign key:
-- retention deletes import rows after catalog.import.keep_days while the product stays.
