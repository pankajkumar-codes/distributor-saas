-- filing schema, R1-M8 slice 4 (LLD-5 §2.3, §7): the files of an export and the acceptances it relied on.
--
-- `export_files`: one row per file (part) of an export snapshot, with where it was stored, its SHA-256 and size, so a file can be
-- served again and checked against what was written. `snapshot_acceptances`: the warnings the user had accepted when the
-- snapshot was written (LLD-5 §6). Both are insert-only like the snapshot they belong to.

create table filing.export_files (
    snapshot_id uuid not null,
    business_id uuid not null,
    part_no int not null check (part_no >= 1),
    object_key text not null check (length(object_key) <= 300),
    sha256 char(64) not null check (sha256 ~ '^[0-9a-f]{64}$'),
    size_bytes int not null check (size_bytes > 0),
    row_count int not null check (row_count >= 0),
    primary key (snapshot_id, part_no),
    foreign key (snapshot_id, business_id) references filing.return_snapshots (id, business_id)
);

create table filing.snapshot_acceptances (
    snapshot_id uuid not null,
    business_id uuid not null,
    acceptance_id uuid not null references filing.check_acceptances (id),
    primary key (snapshot_id, acceptance_id),
    foreign key (snapshot_id, business_id) references filing.return_snapshots (id, business_id)
);

alter table filing.export_files enable row level security;
alter table filing.export_files force row level security;
create policy tenant_rw on filing.export_files to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.export_files for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.export_files for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.export_files to app_rw;
grant select on filing.export_files to app_ro;
create trigger export_files_insert_only before update or delete on filing.export_files
    for each row execute function filing.refuse_snapshot_change();
create trigger export_files_no_truncate before truncate on filing.export_files
    for each statement execute function filing.refuse_snapshot_change();

alter table filing.snapshot_acceptances enable row level security;
alter table filing.snapshot_acceptances force row level security;
create policy tenant_rw on filing.snapshot_acceptances to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.snapshot_acceptances for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.snapshot_acceptances for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.snapshot_acceptances to app_rw;
grant select on filing.snapshot_acceptances to app_ro;
create trigger snapshot_acceptances_insert_only before update or delete on filing.snapshot_acceptances
    for each row execute function filing.refuse_snapshot_change();
create trigger snapshot_acceptances_no_truncate before truncate on filing.snapshot_acceptances
    for each statement execute function filing.refuse_snapshot_change();
