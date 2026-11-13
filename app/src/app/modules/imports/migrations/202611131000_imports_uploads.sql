-- imports.uploads: one row per presigned POST (LLD-7 §2.1, R1-M3). A file is uploaded into
-- a section (a platform, or the user's own invoices); a job later reads it and, from the
-- next slice, stages its rows as an import run. This table holds no cell values, only the
-- file's name, size, checksum and where it stands.
--
-- raw_deleted_at: the object is purged after refdata imports.upload.keep_days by a
-- retention rule (a later file); the row stays. No DELETE grant. app_rw may change only
-- what the flow moves: status, the reject reason, the checksum, the run it produced, and
-- when the raw file was purged.

create table imports.uploads (
    id uuid primary key,
    business_id uuid not null,
    section text not null
        check (section in ('amazon', 'flipkart', 'meesho', 'own_invoices_excel', 'own_invoices_pdf')),
    s3_key text not null,
    file_name text not null check (file_name <> '' and length(file_name) <= 255),
    size_bytes bigint not null check (size_bytes > 0),
    status text not null default 'pending'
        check (status in ('pending', 'received', 'parsing', 'parsed', 'stored', 'rejected', 'expired')),
    reject_reason text check (reject_reason is null or status = 'rejected'),
    checksum_sha256 char(64) check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    run_id uuid,
    raw_deleted_at timestamptz,
    created_by uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, business_id),
    foreign key (run_id, business_id) references imports.import_runs (id, business_id)
);
create index uploads_by_business on imports.uploads (business_id, created_at desc);
create index uploads_pending on imports.uploads (created_at) where status = 'pending';

alter table imports.uploads enable row level security;
alter table imports.uploads force row level security;
create policy tenant_rw on imports.uploads to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.uploads for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.uploads for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on imports.uploads to app_rw;
grant update (status, reject_reason, checksum_sha256, run_id, raw_deleted_at, updated_at)
    on imports.uploads to app_rw;
grant select on imports.uploads to app_ro;
