-- filing schema, R1-M8 slice 2 (LLD-5 §2.3, TD-13): insert-only snapshots of a built return.
--
-- A snapshot is what an export or a lock contained: the rows as they were written and the
-- documents behind them. Nothing in a snapshot is ever edited or removed (update, delete and truncate are refused),
-- so a locked return can always be shown, and downloaded again, exactly as it was filed. A snapshot is written by an
-- export (purpose 'export') and by a lock (purpose 'lock'), never by a view of the return.
-- The files of an export (`export_files`) and the acceptances an export relied on arrive with the export job (slice 4).
-- Money is stored as numeric on the rows; the jsonb `totals` is a display copy only (LLD-5 NF-2).

create function filing.refuse_snapshot_change() returns trigger
    language plpgsql as $$
begin
    raise exception 'filing snapshots are insert-only' using errcode = '55000';
end $$;
revoke all on function filing.refuse_snapshot_change() from public;

create table filing.return_snapshots (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    version int not null check (version >= 1),
    purpose text not null check (purpose in ('export', 'lock')),
    fingerprint char(64) not null check (fingerprint ~ '^[0-9a-f]{64}$'),
    builder_version text not null,
    template_version text,
    refdata_as_of jsonb not null,
    totals jsonb not null default '{}',
    changed_since_export boolean not null default false,
    accept_reason text,
    difference jsonb,
    created_by uuid,
    created_at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id),
    unique (id, business_id),
    unique (instance_id, version),
    -- a difference and its reason are recorded together, and only on a lock (LLD-5 L5-5)
    check (changed_since_export = (accept_reason is not null)),
    check (changed_since_export = (difference is not null)),
    check (not changed_since_export or purpose = 'lock')
);
create index return_snapshots_by_instance on filing.return_snapshots (business_id, instance_id, purpose, version desc);

create table filing.snapshot_lines (
    snapshot_id uuid not null,
    business_id uuid not null,
    section text not null check (section in ('b2b', 'b2cl', 'b2cs', 'cdnr', 'cdnur', 'hsn_b2b', 'hsn_b2c', 'docs', 'eco')),
    row_no int not null check (row_no >= 1),
    doc_number varchar(16),
    doc_date date,
    counterparty_gstin char(15),
    pos_state_code char(2),
    rate numeric(5, 2),
    hsn varchar(8),
    uqc varchar(3),
    note_type char(1),
    ur_type text,
    quantity numeric(18, 3),
    invoice_value numeric(18, 2),
    taxable_value numeric(18, 2) not null default 0,
    igst numeric(18, 2) not null default 0,
    cgst numeric(18, 2) not null default 0,
    sgst numeric(18, 2) not null default 0,
    cess numeric(18, 2) not null default 0,
    series_prefix text,
    from_no text,
    to_no text,
    total_count int,
    cancelled_count int,
    file_part int,
    primary key (snapshot_id, row_no),
    foreign key (snapshot_id, business_id) references filing.return_snapshots (id, business_id)
);

create table filing.snapshot_members (
    snapshot_id uuid not null,
    business_id uuid not null,
    source_kind text not null,
    source_id uuid not null,
    via_instance uuid not null,
    primary key (snapshot_id, source_kind, source_id),
    foreign key (snapshot_id, business_id) references filing.return_snapshots (id, business_id),
    foreign key (via_instance, business_id) references filing.return_instances (id, business_id)
);
create index snapshot_members_by_source on filing.snapshot_members (business_id, source_id);

alter table filing.return_snapshots enable row level security;
alter table filing.return_snapshots force row level security;
create policy tenant_rw on filing.return_snapshots to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.return_snapshots for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.return_snapshots for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.return_snapshots to app_rw;
grant select on filing.return_snapshots to app_ro;
create trigger return_snapshots_insert_only before update or delete on filing.return_snapshots
    for each row execute function filing.refuse_snapshot_change();
create trigger return_snapshots_no_truncate before truncate on filing.return_snapshots
    for each statement execute function filing.refuse_snapshot_change();

alter table filing.snapshot_lines enable row level security;
alter table filing.snapshot_lines force row level security;
create policy tenant_rw on filing.snapshot_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.snapshot_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.snapshot_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.snapshot_lines to app_rw;
grant select on filing.snapshot_lines to app_ro;
create trigger snapshot_lines_insert_only before update or delete on filing.snapshot_lines
    for each row execute function filing.refuse_snapshot_change();
create trigger snapshot_lines_no_truncate before truncate on filing.snapshot_lines
    for each statement execute function filing.refuse_snapshot_change();

alter table filing.snapshot_members enable row level security;
alter table filing.snapshot_members force row level security;
create policy tenant_rw on filing.snapshot_members to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.snapshot_members for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.snapshot_members for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.snapshot_members to app_rw;
grant select on filing.snapshot_members to app_ro;
create trigger snapshot_members_insert_only before update or delete on filing.snapshot_members
    for each row execute function filing.refuse_snapshot_change();
create trigger snapshot_members_no_truncate before truncate on filing.snapshot_members
    for each statement execute function filing.refuse_snapshot_change();

