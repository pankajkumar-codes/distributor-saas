-- R2-M6: the monthly and quarterly sales-and-purchases files (an Excel workbook and a purchase register JSON).
-- `period_exports` is one generation: the period, a fingerprint of every row that went into it (so the same data
-- asked for twice finds the same export instead of making a second), and who asked. `period_export_files` holds each file
-- with where it was stored and its SHA-256. Both insert-only like return snapshots: a changed period makes a new
-- export, the old one stays.

create table filing.period_exports (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    kind text not null check (kind in ('month', 'quarter')),
    period_start date not null,
    period_end date not null,
    fingerprint char(64) not null check (fingerprint ~ '^[0-9a-f]{64}$'),
    sales_lines int not null check (sales_lines >= 0),
    purchase_lines int not null check (purchase_lines >= 0),
    practice_documents int not null check (practice_documents >= 0),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    check (period_end >= period_start),
    unique (id, business_id),
    unique (business_id, kind, period_start, fingerprint)
);
create index period_exports_by_period on filing.period_exports (business_id, period_start desc, created_at desc);

create table filing.period_export_files (
    export_id uuid not null,
    business_id uuid not null,
    name text not null check (name in ('workbook', 'purchase_register')),
    object_key text not null check (length(object_key) <= 300),
    sha256 char(64) not null check (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes int not null check (size_bytes > 0),
    primary key (export_id, name),
    foreign key (export_id, business_id) references filing.period_exports (id, business_id)
);

alter table filing.period_exports enable row level security;
alter table filing.period_exports force row level security;
create policy tenant_rw on filing.period_exports to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.period_exports for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.period_exports for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.period_exports to app_rw;
grant select on filing.period_exports to app_ro;
create trigger period_exports_insert_only before update or delete on filing.period_exports
    for each row execute function filing.refuse_snapshot_change();
create trigger period_exports_no_truncate before truncate on filing.period_exports
    for each statement execute function filing.refuse_snapshot_change();

alter table filing.period_export_files enable row level security;
alter table filing.period_export_files force row level security;
create policy tenant_rw on filing.period_export_files to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.period_export_files for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.period_export_files for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.period_export_files to app_rw;
grant select on filing.period_export_files to app_ro;
create trigger period_export_files_insert_only before update or delete on filing.period_export_files
    for each row execute function filing.refuse_snapshot_change();
create trigger period_export_files_no_truncate before truncate on filing.period_export_files
    for each statement execute function filing.refuse_snapshot_change();
