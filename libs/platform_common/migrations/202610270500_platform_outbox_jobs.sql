-- The outbox and jobs (LLD-0 §3.7, §4.5; HLD §7, TD-3). A request writes a job and an
-- outbox row in its own transaction; after commit the outbox row goes to SQS, and a
-- 1-minute sweep resends anything not marked sent within 30 s. The worker claims a job
-- by ID before doing anything, so a second delivery of the same job does nothing.
--
-- Beyond §3.7 (D-039):
-- - jobs.unique is (business_id, type, natural_key), not (type, natural_key): a natural
--   key from one business must never find, or collide with, another business's job.
-- - claim_job takes the lease length, so the worker passes its own Lambda timeout + 1
--   minute (HLD §7) instead of the database guessing it.
-- - Both tables take the support-grant exclusion the audit log has: support views
--   nothing here until the support flow exists.

create table platform.outbox (
    id uuid primary key,
    business_id uuid,
    type text not null,
    payload jsonb not null,  -- IDs only, never data
    created_at timestamptz not null default now(),
    sent_at timestamptz
);
create index outbox_unsent on platform.outbox (created_at) where sent_at is null;

create table platform.jobs (
    id uuid primary key,
    business_id uuid,
    type text not null,
    actor_user_id uuid,
    status text not null default 'queued'
        check (status in ('queued', 'running', 'done', 'failed', 'failed_retryable')),
    attempt int not null default 0,
    started_at timestamptz,
    lease_until timestamptz,
    progress_done int,
    progress_total int,
    result jsonb,
    error_code text,
    natural_key text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, type, natural_key)
);
create index jobs_business_created on platform.jobs (business_id, created_at desc);

alter table platform.outbox enable row level security;
alter table platform.outbox force row level security;
alter table platform.jobs enable row level security;
alter table platform.jobs force row level security;

-- app_rw: inside its business's unit of work only.
create policy outbox_tenant on platform.outbox to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy jobs_tenant on platform.jobs to app_rw, app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');

grant select, insert on platform.outbox to app_rw;
grant select, insert on platform.jobs to app_rw;
-- What a handler's unit of work writes back; attempt, lease and started_at change only
-- through claim_job.
grant update (status, progress_done, progress_total, result, error_code, updated_at) on platform.jobs to app_rw;
grant select on platform.jobs to app_ro;

-- platform_ops (NOLOGIN) owns the three functions below and nothing else. Its policies
-- see every row, which is safe because the functions return IDs only (§4.5).
grant usage on schema platform to platform_ops;
grant select, update on platform.outbox, platform.jobs to platform_ops;
create policy outbox_ops_select on platform.outbox for select to platform_ops using (true);
create policy outbox_ops_update on platform.outbox for update to platform_ops using (true) with check (true);
create policy jobs_ops_select on platform.jobs for select to platform_ops using (true);
create policy jobs_ops_update on platform.jobs for update to platform_ops using (true) with check (true);

-- Rows not marked sent 30 s after they were written: the after-commit send failed, or
-- its mark did. Sending one again is harmless (the claim is idempotent).
create function platform.sweep_outbox(max_rows int)
returns table (outbox_id uuid, business_id uuid, type text, payload jsonb)
language sql stable security definer set search_path = pg_catalog, platform, pg_temp as $$
    select o.id, o.business_id, o.type, o.payload
    from platform.outbox o
    where o.sent_at is null and o.created_at <= now() - interval '30 seconds'
    order by o.created_at
    limit greatest(least(max_rows, 500), 0)
$$;

create function platform.mark_outbox_sent(ids uuid[]) returns void
language sql volatile security definer set search_path = pg_catalog, platform, pg_temp as $$
    update platform.outbox set sent_at = now() where id = any(ids) and sent_at is null
$$;

-- HLD §7: zero rows when another delivery holds the job or it is finished. A running job
-- whose lease has passed counts as retryable, so a crashed attempt isn't stranded.
create function platform.claim_job(job_id uuid, lease_seconds int)
returns table (business_id uuid, actor_user_id uuid, type text, attempt int)
language sql volatile security definer set search_path = pg_catalog, platform, pg_temp as $$
    update platform.jobs j
    set status = 'running', attempt = j.attempt + 1, started_at = now(),
        lease_until = now() + make_interval(secs => greatest(lease_seconds, 1)), updated_at = now()
    where j.id = claim_job.job_id
      and (j.status in ('queued', 'failed_retryable') or (j.status = 'running' and j.lease_until < now()))
    returning j.business_id, j.actor_user_id, j.type, j.attempt
$$;

-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for these statements and taken back.
grant create on schema platform to platform_ops;
alter function platform.sweep_outbox(int) owner to platform_ops;
alter function platform.mark_outbox_sent(uuid[]) owner to platform_ops;
alter function platform.claim_job(uuid, int) owner to platform_ops;
revoke create on schema platform from platform_ops;
revoke all on function platform.sweep_outbox(int), platform.mark_outbox_sent(uuid[]),
    platform.claim_job(uuid, int) from public;
grant execute on function platform.sweep_outbox(int), platform.mark_outbox_sent(uuid[]),
    platform.claim_job(uuid, int) to app_rw;
