-- filing schema, S6 periods (LLD-5 §2.1, §2.2, §4, §8; LLD-4 §11, L4-12): return instances
-- and their insert-only event log. Snapshots, acceptances and worksheets come with later
-- slices, each in its own file.
--
-- A return instance is one return for one GSTIN and period (D-035). It is created lazily
-- (ensure_instances, ON CONFLICT DO NOTHING) and never deleted. app_rw may update only the
-- status columns, the due date and the IFF running total (the column grant is also what lets
-- app_rw take FOR SHARE / FOR UPDATE). The status guard [RM45-8] refuses a status,
-- forwarded_to or due_date change that is not an allowed transition with its event row
-- written in the same transaction; no code in this slice changes status.
--
-- iff_b2b_taxable [S6-3]: the taxable value of B2B invoices assigned to an IFF so far, kept
-- by target_return_instance under the IFF's advisory lock for the L5-3 cap. It only grows:
-- documents are insert-only and R1 has no cancellation; credit notes don't count (L5-3).
--
-- Policies are LLD-0 §4.2's standard trio written out per table (migrator.lint).

create schema if not exists filing;
grant usage on schema filing to app_rw, app_ro;

create table filing.return_instances (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    form text not null check (form in ('GSTR1', 'IFF', 'GSTR3B', 'PMT06')),
    frequency text not null check (frequency in ('monthly', 'quarterly')),
    filer_frequency text not null check (filer_frequency in ('monthly', 'qrmp')),
    period_start date not null,
    period_end date not null,
    return_period char(7) not null check (return_period ~ '^[0-9]{4}-[0-9]{2}$'),
    due_date date,  -- null: no date exists for this GSTIN's state (quarterly GSTR-3B, state 97)
    due_date_ref text not null,
    status text not null default 'open'
        check (status in ('open', 'filed_locked', 'unlocked', 'skipped', 'superseded')),
    forwarded_to uuid references filing.return_instances (id),
    iff_b2b_taxable numeric(18, 2) not null default 0 check (iff_b2b_taxable >= 0),
    status_changed_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    check (period_start <= period_end),
    check (form = 'IFF' or iff_b2b_taxable = 0),
    unique (id, business_id)
);
create unique index return_instances_one_live on filing.return_instances (business_id, gstin, form, period_start)
    where status <> 'superseded';
create index return_instances_by_period on filing.return_instances (business_id, gstin, period_start);

create table filing.instance_events (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    kind text not null
        check (kind in ('filed', 'paid', 'unlocked', 'skipped', 'unskipped', 'superseded', 'due_date_changed')),
    filed_on date,
    arn varchar(32),
    amount numeric(18, 2),
    cpin varchar(32),
    reason text,
    snapshot_id uuid,
    actor_user_id uuid,
    txid bigint not null default txid_current(),
    at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id)
);
create index instance_events_by_instance on filing.instance_events (business_id, instance_id, at);

alter table filing.return_instances enable row level security;
alter table filing.return_instances force row level security;
create policy tenant_rw on filing.return_instances to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.return_instances for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.return_instances for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table filing.instance_events enable row level security;
alter table filing.instance_events force row level security;
create policy tenant_rw on filing.instance_events to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.instance_events for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.instance_events for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

-- [RM45-8] Status, forwarded_to and due_date change only by an allowed transition whose
-- event row exists in this transaction. The IFF running total only grows.
create function filing.guard_instance_status() returns trigger
language plpgsql security invoker set search_path = pg_catalog, filing, pg_temp as $$
declare
    needed text;
begin
    if new.id <> old.id or new.business_id <> old.business_id or new.gstin <> old.gstin or new.form <> old.form
       or new.period_start <> old.period_start or new.period_end <> old.period_end then
        raise exception 'return instance % identity cannot change', old.id using errcode = 'FRI01';
    end if;
    if new.iff_b2b_taxable < old.iff_b2b_taxable then
        raise exception 'IFF % running total cannot go down', old.id using errcode = 'FRI02';
    end if;
    if new.due_date is distinct from old.due_date then
        if old.status <> 'open' then
            raise exception 'due date of % can change only while open', old.id using errcode = 'FRI03';
        end if;
        needed := 'due_date_changed';
    end if;
    if new.status is distinct from old.status or new.forwarded_to is distinct from old.forwarded_to then
        needed := case
            when old.status = 'open' and new.status = 'filed_locked' then 'filed'
            when old.status = 'unlocked' and new.status = 'filed_locked' then 'filed'
            when old.status = 'skipped' and new.status = 'filed_locked' then 'unskipped'
            when old.status = 'filed_locked' and new.status = 'unlocked' then 'unlocked'
            when old.status = 'open' and new.status = 'skipped' then 'skipped'
            when old.status = 'open' and new.status = 'superseded' then 'superseded'
        end;
        if needed is null then
            raise exception 'return instance % cannot go from % to %', old.id, old.status, new.status
                using errcode = 'FRI04';
        end if;
    end if;
    if needed is not null and not exists (
        select 1 from filing.instance_events e
        where e.instance_id = old.id and e.business_id = old.business_id and e.kind = needed
          and e.txid = txid_current()
    ) then
        raise exception 'return instance % change needs a % event in the same transaction', old.id, needed
            using errcode = 'FRI05';
    end if;
    return new;
end
$$;
revoke all on function filing.guard_instance_status() from public;
create trigger return_instances_status_guard before update on filing.return_instances
    for each row execute function filing.guard_instance_status();

-- Grants: no DELETE anywhere; events are insert-only (L5-2).
grant select, insert on filing.return_instances, filing.instance_events to app_rw;
grant update (status, forwarded_to, status_changed_at, due_date, due_date_ref, iff_b2b_taxable)
    on filing.return_instances to app_rw;
grant select on filing.return_instances, filing.instance_events to app_ro;
