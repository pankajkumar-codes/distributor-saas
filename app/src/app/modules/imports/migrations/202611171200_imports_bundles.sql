-- Bundle upload, slice 2 (bundle-upload-plan): one ZIP of mixed report files, sorted by what each file holds,
-- shown to the user before anything is staged, then staged as one normal upload per used file.
--
-- imports.bundles        the zip itself: name, size, checksum, where it stands. No cell values, no file contents.
-- imports.bundle_files   what the classifier decided about each file, as it decided it. Insert-only.
-- imports.bundle_choices what the user then did with a file (moved it to a section, or dropped it). Insert-only,
--                        the latest choice for a file wins, so the history of choices stays.
-- imports.bundle_uploads the normal upload each used file became when the bundle was staged. Insert-only, one per
--                        file, so staging twice cannot make a second upload of the same file.
--
-- Every table carries business_id, with composite foreign keys so a row can only point at its own business's rows.
-- Forward-only and additive. The zip object follows the existing raw-file retention (imports.upload.keep_days).

create table imports.bundles (
    id uuid primary key,
    business_id uuid not null,
    s3_key text not null,
    file_name text not null check (file_name <> '' and length(file_name) <= 255),
    size_bytes bigint not null check (size_bytes > 0),
    status text not null default 'pending'
        check (status in ('pending', 'received', 'classified', 'staging', 'staged', 'rejected', 'expired')),
    reject_reason text check (reject_reason is null or status = 'rejected'),
    checksum_sha256 char(64) check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, business_id)
);
create index bundles_by_business on imports.bundles (business_id, created_at desc);

create table imports.bundle_files (
    bundle_id uuid not null,
    business_id uuid not null,
    n int not null check (n >= 1),
    file_name text not null check (file_name <> '' and length(file_name) <= 255),
    size_bytes bigint not null check (size_bytes >= 0),
    section text check (section is null
        or section in ('amazon', 'flipkart', 'meesho', 'own_invoices_excel', 'own_invoices_pdf')),
    state text not null check (state in ('used', 'not_used', 'not_selected')),
    reason_code text,
    primary key (bundle_id, n),
    unique (bundle_id, n, business_id),
    foreign key (bundle_id, business_id) references imports.bundles (id, business_id),
    -- a used file has its section and no reason; a file left out says why; only a file no section took has none
    check ((state = 'used') = (reason_code is null)),
    check ((state = 'not_used') = (section is null))
);

create table imports.bundle_choices (
    id uuid primary key,
    bundle_id uuid not null,
    business_id uuid not null,
    n int not null,
    section text check (section is null
        or section in ('amazon', 'flipkart', 'meesho', 'own_invoices_excel', 'own_invoices_pdf')),  -- null: dropped
    chosen_by uuid not null,
    created_at timestamptz not null default now(),
    foreign key (bundle_id, n, business_id) references imports.bundle_files (bundle_id, n, business_id)
);
create index bundle_choices_latest on imports.bundle_choices (bundle_id, n, created_at desc, id desc);

create table imports.bundle_uploads (
    bundle_id uuid not null,
    business_id uuid not null,
    n int not null,
    upload_id uuid not null,
    primary key (bundle_id, n),
    foreign key (bundle_id, n, business_id) references imports.bundle_files (bundle_id, n, business_id),
    foreign key (upload_id, business_id) references imports.uploads (id, business_id)
);

create function imports.refuse_bundle_change() returns trigger
    language plpgsql as $$
begin
    raise exception 'imports bundle records are insert-only' using errcode = '55000';
end $$;
revoke all on function imports.refuse_bundle_change() from public;

-- Row-level security and grants, the same shape as imports.uploads.
alter table imports.bundles enable row level security;
alter table imports.bundles force row level security;
create policy tenant_rw on imports.bundles to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.bundles for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.bundles for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.bundles to app_rw;
grant update (status, reject_reason, checksum_sha256, updated_at) on imports.bundles to app_rw;
grant select on imports.bundles to app_ro;

alter table imports.bundle_files enable row level security;
alter table imports.bundle_files force row level security;
create policy tenant_rw on imports.bundle_files to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.bundle_files for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.bundle_files for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.bundle_files to app_rw;
grant select on imports.bundle_files to app_ro;
create trigger bundle_files_insert_only before update or delete on imports.bundle_files
    for each row execute function imports.refuse_bundle_change();
create trigger bundle_files_no_truncate before truncate on imports.bundle_files
    for each statement execute function imports.refuse_bundle_change();

alter table imports.bundle_choices enable row level security;
alter table imports.bundle_choices force row level security;
create policy tenant_rw on imports.bundle_choices to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.bundle_choices for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.bundle_choices for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.bundle_choices to app_rw;
grant select on imports.bundle_choices to app_ro;
create trigger bundle_choices_insert_only before update or delete on imports.bundle_choices
    for each row execute function imports.refuse_bundle_change();
create trigger bundle_choices_no_truncate before truncate on imports.bundle_choices
    for each statement execute function imports.refuse_bundle_change();

alter table imports.bundle_uploads enable row level security;
alter table imports.bundle_uploads force row level security;
create policy tenant_rw on imports.bundle_uploads to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.bundle_uploads for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.bundle_uploads for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.bundle_uploads to app_rw;
grant select on imports.bundle_uploads to app_ro;
create trigger bundle_uploads_insert_only before update or delete on imports.bundle_uploads
    for each row execute function imports.refuse_bundle_change();
create trigger bundle_uploads_no_truncate before truncate on imports.bundle_uploads
    for each statement execute function imports.refuse_bundle_change();
