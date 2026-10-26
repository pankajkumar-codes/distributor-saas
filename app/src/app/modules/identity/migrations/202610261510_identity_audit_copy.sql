-- The legacy audit copy (LLD-1 §3.6, LLD-0 §3.6), with the LLD-2 routes that stop writing
-- identity.audit_events:
--   1. copy every identity.audit_events row into platform.audit_log, keeping its id, so a
--      re-run copies nothing twice (on conflict do nothing);
--   2. close the legacy inserts: ae_insert refuses everything, and app_rw (and the
--      svc_identity bridge it inherits) loses INSERT. Nothing is dropped; dropping the
--      table goes to the CEO later;
--   3. platform.v_audit_log, with c3's columns, reads platform.audit_log only.
--
-- Mapping, as c3's interim view does it: tenant_id -> business_id; actor_sub -> user_id
-- through users.cognito_sub (unmatched: null, and actor_sub kept in data);
-- entity_type -> target_kind; entity_id -> target_id when it is a uuid, else
-- data.entity_id; details.reason -> reason; the other details keys pass a per-action
-- allowlist, unknown keys are dropped and counted in data.legacy_dropped_keys;
-- request_id 'legacy-copy'. details that isn't a JSON object (Staff 2's guard) keeps
-- nothing and counts as one dropped key.

-- The migrating role owns these tables, and FORCE would hold it to the app's policies.
alter table platform.audit_log no force row level security;
alter table identity.audit_events no force row level security;
alter table identity.users no force row level security;

-- 1. ------------------------------------------------------------------------------
insert into platform.audit_log
    (id, business_id, user_id, support_grant_id, action, target_kind, target_id, reason, data, request_id, at)
select e.id, e.tenant_id, u.id, null, e.action, e.entity_type,
       case when e.entity_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            then e.entity_id::uuid end,
       case when jsonb_typeof(e.details::jsonb) = 'object'
            then nullif(btrim(e.details::jsonb ->> 'reason'), '') end,
       coalesce(kept.data, '{}'::jsonb)
           || jsonb_build_object('legacy_dropped_keys', dropped.n)
           || case when u.id is null then jsonb_build_object('actor_sub', e.actor_sub) else '{}'::jsonb end
           || case when e.entity_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                   then '{}'::jsonb else jsonb_build_object('entity_id', e.entity_id) end,
       'legacy-copy', e.at
from identity.audit_events e
left join identity.users u on u.cognito_sub = e.actor_sub
cross join lateral (
    select case e.action
               when 'member.added' then array['role']
               when 'member.deactivated' then array['role']
               when 'member.reactivated' then array['role']
               when 'invitation.created' then array['role']
               when 'invitation.accepted' then array['role']
               else array[]::text[]
           end as allowed,
           case when jsonb_typeof(e.details::jsonb) = 'object' then e.details::jsonb end as details
) a
cross join lateral (
    select jsonb_object_agg(k, v) as data
    from jsonb_each(coalesce(a.details, '{}'::jsonb)) as d(k, v)
    where k = any (a.allowed)
) kept
cross join lateral (
    select case when a.details is null then 1
                else (select count(*) from jsonb_object_keys(a.details) k
                      where not (k = any (a.allowed)) and k <> 'reason')
           end as n
) dropped
on conflict (id) do nothing;

alter table platform.audit_log force row level security;
alter table identity.audit_events force row level security;
alter table identity.users force row level security;

-- 2. ------------------------------------------------------------------------------
alter policy ae_insert on identity.audit_events with check (false);
revoke insert on identity.audit_events from app_rw, svc_identity;

-- 3. ------------------------------------------------------------------------------
create or replace view platform.v_audit_log with (security_invoker = true) as
select a.id, a.business_id, a.user_id, a.support_grant_id, a.action, a.target_kind,
       a.target_id, a.reason, a.data, a.request_id, a.at
from platform.audit_log a;
