-- Table 13 (documents issued) of GSTR-1, issue #353 (docs/TABLE13_SPEC.md).
--
-- The person confirms, per return, the series of documents they issued in the period. A confirmation is a new version, never an
-- edit: the latest version of an instance is the current answer, and it counts only while its build fingerprint equals the
-- return's (a document added or changed since makes it stale). Counts only; no amounts, no GSTIN, no counterparty.
-- Snapshot lines gain the nature of a Table 13 row so a snapshot reproduces the file.

create table filing.table13_confirmations (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    version int not null check (version >= 1),
    build_fingerprint char(64) not null check (build_fingerprint ~ '^[0-9a-f]{64}$'),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id),
    unique (id, business_id),
    unique (instance_id, version)
);

create table filing.table13_rows (
    confirmation_id uuid not null,
    business_id uuid not null,
    row_no int not null check (row_no >= 1),
    nature smallint not null check (nature between 1 and 12),
    from_no varchar(16) not null check (from_no ~ '^[A-Za-z0-9/-]+$'),
    to_no varchar(16) not null check (to_no ~ '^[A-Za-z0-9/-]+$'),
    total_count int not null check (total_count >= 0),
    cancelled_count int not null check (cancelled_count >= 0 and cancelled_count <= total_count),
    source text not null check (source in ('own_live', 'uploaded_own', 'marketplace', 'manual')),
    counted boolean not null,
    primary key (confirmation_id, row_no),
    foreign key (confirmation_id, business_id) references filing.table13_confirmations (id, business_id)
);

alter table filing.snapshot_lines add column nature smallint check (nature between 1 and 12);

alter table filing.table13_confirmations enable row level security;
alter table filing.table13_confirmations force row level security;
create policy tenant_rw on filing.table13_confirmations to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.table13_confirmations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.table13_confirmations for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.table13_confirmations to app_rw;
grant select on filing.table13_confirmations to app_ro;
create trigger table13_confirmations_insert_only before update or delete on filing.table13_confirmations
    for each row execute function filing.refuse_snapshot_change();
create trigger table13_confirmations_no_truncate before truncate on filing.table13_confirmations
    for each statement execute function filing.refuse_snapshot_change();

alter table filing.table13_rows enable row level security;
alter table filing.table13_rows force row level security;
create policy tenant_rw on filing.table13_rows to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.table13_rows for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.table13_rows for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.table13_rows to app_rw;
grant select on filing.table13_rows to app_ro;
create trigger table13_rows_insert_only before update or delete on filing.table13_rows
    for each row execute function filing.refuse_snapshot_change();
create trigger table13_rows_no_truncate before truncate on filing.table13_rows
    for each statement execute function filing.refuse_snapshot_change();
