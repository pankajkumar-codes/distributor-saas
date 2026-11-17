-- filing schema, R1-M8 slice 1 (LLD-5 §2.4, §6): the user's acceptance of a warning, as it was shown.
--
-- A warning is accepted for one instance, one check code and one subject (`subject_fp`, a hash of the rows the
-- finding is about). An acceptance counts only while the current finding has the same `subject_fp`: new or
-- changed rows give a new fingerprint and need a new acceptance. Blocks are never accepted (the API refuses).
-- Insert-only: an acceptance is never edited or removed, and accepting the same finding again is a no-op.
-- Only the person and the time are kept besides the note; the finding's text is rebuilt from the return.

create function filing.refuse_change() returns trigger
    language plpgsql as $$
begin
    raise exception 'filing acceptances and snapshots are insert-only' using errcode = '55000';
end $$;
revoke all on function filing.refuse_change() from public;

create table filing.check_acceptances (
    id uuid primary key,
    business_id uuid not null,
    instance_id uuid not null,
    check_code text not null check (check_code ~ '^[A-Z]-[0-9]{2}$'),
    subject_fp char(64) not null check (subject_fp ~ '^[0-9a-f]{64}$'),
    note text not null check (length(btrim(note)) > 0 and length(note) <= 500),
    accepted_by uuid not null,
    accepted_at timestamptz not null default now(),
    foreign key (instance_id, business_id) references filing.return_instances (id, business_id),
    unique (business_id, instance_id, check_code, subject_fp)
);
create index check_acceptances_by_instance on filing.check_acceptances (business_id, instance_id);

alter table filing.check_acceptances enable row level security;
alter table filing.check_acceptances force row level security;
create policy tenant_rw on filing.check_acceptances to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on filing.check_acceptances for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on filing.check_acceptances for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on filing.check_acceptances to app_rw;
grant select on filing.check_acceptances to app_ro;
create trigger check_acceptances_insert_only before update or delete on filing.check_acceptances
    for each row execute function filing.refuse_change();
create trigger check_acceptances_no_truncate before truncate on filing.check_acceptances
    for each statement execute function filing.refuse_change();
