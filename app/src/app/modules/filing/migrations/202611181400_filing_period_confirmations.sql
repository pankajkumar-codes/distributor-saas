-- R3-M1: the per-period gate. Before filing from the business's own invoices, the business says, for each month (or quarter),
-- that every purchase invoice is uploaded and that every invoice is in the portal. A confirmation is a fact the business
-- stated at a time, against a fingerprint of the period's rows; it is never edited. Taking one back, or confirming again
-- after the data changed, is a new row: the latest row per (period, item) is the current answer.

create table filing.period_confirmations (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    kind text not null check (kind in ('month', 'quarter')),
    period_start date not null,
    item text not null check (item in ('purchases_uploaded', 'invoices_in_portal')),
    confirmed boolean not null,
    data_fingerprint char(64) not null check (data_fingerprint ~ '^[0-9a-f]{64}$'),
    created_by uuid not null,
    created_at timestamptz not null default now()
);
create index period_confirmations_latest on filing.period_confirmations
    (business_id, kind, period_start, item, created_at desc, id desc);

alter table filing.period_confirmations enable row level security;
alter table filing.period_confirmations force row level security;
create policy tenant_rw on filing.period_confirmations to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.period_confirmations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.period_confirmations for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on filing.period_confirmations to app_rw;
grant select on filing.period_confirmations to app_ro;
create trigger period_confirmations_insert_only before update or delete on filing.period_confirmations
    for each row execute function filing.refuse_snapshot_change();
create trigger period_confirmations_no_truncate before truncate on filing.period_confirmations
    for each statement execute function filing.refuse_snapshot_change();
