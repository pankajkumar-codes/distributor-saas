-- filing schema, R1-M8b slice W2: the GSTR-3B worksheet (a worksheet of numbers to check and enter on the GST portal, never a filing).
--
-- `worksheet_versions`: one row per explicit build of the outward supplies from the matching GSTR-1 build, with the fingerprint of
-- the build it was made from (out of date = the live GSTR-1 fingerprint differs from the latest version's). Money inside the jsonb is
-- decimal text, a display copy.
-- `worksheet_entries`: what the seller typed (ITC, reverse charge, Table 5, interest), one row per save, each pointing at the one it
-- replaced, so who changed what and when stays readable. Entries survive a rebuild.
-- Both are insert-only (update, delete and truncate are refused) like snapshots.

create function filing.refuse_worksheet_change() returns trigger
    language plpgsql as $$
begin
    raise exception 'filing worksheets are insert-only' using errcode = '55000';
end $$;
revoke all on function filing.refuse_worksheet_change() from public;

create table filing.worksheet_versions (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    version int not null check (version >= 1),
    build_fingerprint char(64) not null check (build_fingerprint ~ '^[0-9a-f]{64}$'),
    outward jsonb not null,
    flags jsonb not null default '[]',
    built_by uuid,
    built_at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id),
    unique (id, business_id),
    unique (instance_id, version)
);
create index worksheet_versions_by_instance on filing.worksheet_versions (business_id, instance_id, version desc);

create table filing.worksheet_entries (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    seq int not null check (seq >= 1),
    entry jsonb not null,
    previous_seq int,
    changed_by uuid,
    changed_at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id),
    unique (id, business_id),
    unique (instance_id, seq),
    check ((seq = 1) = (previous_seq is null)),
    check (previous_seq is null or previous_seq = seq - 1)
);
create index worksheet_entries_by_instance on filing.worksheet_entries (business_id, instance_id, seq desc);

alter table filing.worksheet_versions enable row level security;
alter table filing.worksheet_versions force row level security;
create policy tenant_rw on filing.worksheet_versions to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.worksheet_versions for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.worksheet_versions for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.worksheet_versions to app_rw;
grant select on filing.worksheet_versions to app_ro;
create trigger worksheet_versions_insert_only before update or delete on filing.worksheet_versions
    for each row execute function filing.refuse_worksheet_change();
create trigger worksheet_versions_no_truncate before truncate on filing.worksheet_versions
    for each statement execute function filing.refuse_worksheet_change();

alter table filing.worksheet_entries enable row level security;
alter table filing.worksheet_entries force row level security;
create policy tenant_rw on filing.worksheet_entries to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.worksheet_entries for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.worksheet_entries for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.worksheet_entries to app_rw;
grant select on filing.worksheet_entries to app_ro;
create trigger worksheet_entries_insert_only before update or delete on filing.worksheet_entries
    for each row execute function filing.refuse_worksheet_change();
create trigger worksheet_entries_no_truncate before truncate on filing.worksheet_entries
    for each statement execute function filing.refuse_worksheet_change();
