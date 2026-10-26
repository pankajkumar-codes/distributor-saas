-- Follow-ups from Staff 2's review of #27 (LLD-0 §3.6, §4.4, §4.5).

-- A business audit row names the signed-in user as its actor, or no one (jobs), never
-- someone else. audit.record already does this; RLS is the second wall.
alter policy audit_business_insert on platform.audit_log
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
                and support_grant_id is null
                and user_id is not distinct from nullif(current_setting('app.user_id', true), '')::uuid);

-- The retention job's owner role (RM4-1) purges expired idempotency keys and old rate
-- windows; retention.purge_operational() itself comes with the first job PR. Its RLS
-- access is on only while a retention function has set retention.active.
-- (LLD-0 §4.2 writes "for select, delete" in one policy; PostgreSQL takes one command
-- per policy, hence two.)
grant usage on schema platform to retention_owner;
grant select, delete on platform.idempotency_keys to retention_owner;
create policy retention_purge_select on platform.idempotency_keys for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on platform.idempotency_keys for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');

-- rate_counters is global with no RLS, so the grant is all it needs.
grant select, delete on platform.rate_counters to retention_owner;
