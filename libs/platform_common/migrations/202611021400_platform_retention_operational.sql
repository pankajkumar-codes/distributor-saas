-- retention.purge_operational() (LLD-0 §4.4; LLD-1 §12, LLD-2 §11 and LLD-6 §6.2 add rows;
-- D-041). The pattern every retention rule follows:
-- - owned by retention_owner (NOLOGIN, RM4-1), SECURITY DEFINER, fixed search_path;
-- - EXECUTE only to app_retention, which the retention Lambda alone logs in as (L6-5);
-- - retention.active is set first, and retention_owner's policies match only while it is;
-- - every cutoff comes from refdata. A table whose key has no row today is kept, and the
--   rule as a whole does nothing until refdata `retention.purge_operational.enabled` is
--   true. Every row ships provisional and the rule ships disabled (default keep);
-- - no percent sign anywhere in this file: some tests apply it through a driver that parses
--   placeholders, so dynamic SQL is built by concatenation. Everything concatenated is
--   a constant in `specs` below (schema and table each through quote_ident), never a
--   parameter or a refdata value; the cutoff and the limit are bound with EXECUTE ... USING;
-- - retention.active is switched off again before the function returns;
-- - at most max_rows rows per table per call; `more` says to call again;
-- - dry_run counts without deleting; every call that runs writes a retention_runs row.
--
-- Only operational rows are in scope: finished jobs, sent outbox rows, idempotency keys,
-- rate windows, and identity's sessions, codes, pending sign-ups and closed
-- invitations, each only once it can no longer be used. retention_owner has no grant on
-- the audit log or on any financial, stock or GST table; tests/isolation/test_retention.py
-- lists every privilege it holds and fails on any other.

create schema retention;
grant usage on schema retention to app_retention;

-- The run record. audit_log needs a business or a user and a run has neither
-- (OPEN_QUESTIONS, job runner follow-ups), so runs get their own insert-only table.
create table platform.retention_runs (
    id uuid primary key default gen_random_uuid(),
    rule text not null,
    dry_run boolean not null,
    cutoffs jsonb not null,  -- table -> cutoff, or null where the table was kept
    counts jsonb not null,   -- table -> rows deleted (or that would be), or null
    more boolean not null,
    at timestamptz not null default now()
);
grant usage on schema platform to retention_owner;
grant insert on platform.retention_runs to retention_owner;

grant select, delete on platform.jobs, platform.outbox to retention_owner;
create policy retention_purge_select on platform.jobs for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on platform.jobs for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_select on platform.outbox for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on platform.outbox for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');

create function retention.purge_operational(dry_run boolean default true, max_rows int default 5000)
returns jsonb
language plpgsql volatile security definer set search_path = pg_catalog, pg_temp as $$
declare
    lim int := least(greatest(coalesce(max_rows, 5000), 1), 5000);
    today date := (now() at time zone 'Asia/Kolkata')::date;
    -- name, table, refdata key, unit, the rows that may go (cutoff is $1). Each condition
    -- also refuses a row that is still usable, whatever the cutoff.
    specs constant text[][] := array[
        ['jobs', 'platform.jobs', 'retention.jobs_keep_days', 'days',
         'status in (''done'', ''failed'') and updated_at < $1'],
        ['outbox', 'platform.outbox', 'retention.outbox_keep_days', 'days',
         'sent_at is not null and sent_at < $1'],
        ['idempotency_keys', 'platform.idempotency_keys', 'retention.idempotency_keep_hours', 'hours',
         'created_at < $1'],
        ['rate_counters', 'platform.rate_counters', 'retention.rate_window_keep_hours', 'hours',
         'window_start < $1'],
        ['pending_signups', 'identity.pending_signups', 'retention.pending_signup_keep_hours', 'hours',
         'created_at < $1 and last_code_at < $1 and not exists (select 1 from identity.verification_codes c'
         ' where c.email = pending_signups.email and c.purpose = ''signup'''
         ' and c.consumed_at is null and c.voided_at is null and c.expires_at > now())'],
        ['verification_codes', 'identity.verification_codes', 'retention.code_keep_hours', 'hours',
         '(consumed_at is not null or voided_at is not null or expires_at <= now())'
         ' and coalesce(consumed_at, voided_at, expires_at) < $1'],
        ['sessions', 'identity.sessions', 'retention.session_keep_days', 'days',
         '(revoked_at is not null or absolute_expires_at <= now())'
         ' and least(coalesce(revoked_at, ''infinity''), absolute_expires_at) < $1'],
        ['invitations', 'identity.invitations', 'retention.invitation_keep_days', 'days',
         '(status in (''accepted'', ''cancelled'', ''expired'') or expires_at <= now())'
         ' and coalesce(case status when ''accepted'' then accepted_at'
         ' when ''cancelled'' then cancelled_at end, expires_at) < $1']
    ];
    spec text[];
    tbl text;
    raw text;
    keep int;
    cutoff timestamptz;
    n int;
    cutoffs jsonb := '{}';
    counts jsonb := '{}';
    more boolean := false;
    result jsonb;
begin
    perform set_config('retention.active', 'on', true);

    select v.value into raw from refdata.values v
    where v.key = 'retention.purge_operational.enabled'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if coalesce(raw, 'false') <> 'true' and not dry_run then
        perform set_config('retention.active', 'off', true);
        return jsonb_build_object('rule', 'purge_operational', 'skipped', 'disabled');
    end if;

    foreach spec slice 1 in array specs loop
        raw := null;
        select v.value into raw from refdata.values v
        where v.key = spec[3] and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
        if raw is null then  -- no decided period: keep everything
            cutoffs := cutoffs || jsonb_build_object(spec[1], null);
            counts := counts || jsonb_build_object(spec[1], null);
            continue;
        end if;
        keep := raw::int;
        if keep < 0 then
            raise exception using message = 'refdata ' || spec[3] || ' is negative';
        end if;
        cutoff := now() - make_interval(days => case when spec[4] = 'days' then keep else 0 end,
                                        hours => case when spec[4] = 'hours' then keep else 0 end);
        tbl := quote_ident(split_part(spec[2], '.', 1)) || '.' || quote_ident(split_part(spec[2], '.', 2));
        if dry_run then
            execute 'select count(*) from (select 1 from ' || tbl || ' where ' || spec[5] || ' limit $2) x'
                into n using cutoff, lim;
        else
            execute 'delete from ' || tbl || ' where ctid in (select ctid from ' || tbl
                    || ' where ' || spec[5] || ' limit $2)'
                using cutoff, lim;
            get diagnostics n = row_count;
        end if;
        cutoffs := cutoffs || jsonb_build_object(spec[1], cutoff);
        counts := counts || jsonb_build_object(spec[1], n);
        more := more or n >= lim;
    end loop;

    insert into platform.retention_runs (rule, dry_run, cutoffs, counts, more)
    values ('purge_operational', dry_run, cutoffs, counts, more);
    result := jsonb_build_object('rule', 'purge_operational', 'dry_run', dry_run,
                                 'cutoffs', cutoffs, 'counts', counts, 'more', more);
    perform set_config('retention.active', 'off', true);
    return result;
end
$$;

-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back.
grant create on schema retention to retention_owner;
alter function retention.purge_operational(boolean, int) owner to retention_owner;
revoke create on schema retention from retention_owner;
revoke all on function retention.purge_operational(boolean, int) from public;
grant execute on function retention.purge_operational(boolean, int) to app_retention;
