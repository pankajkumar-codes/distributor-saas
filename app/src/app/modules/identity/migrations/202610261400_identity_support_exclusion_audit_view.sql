-- S0a (c3), as the EM scoped it on 2026-10-26:
--   1. Identity's tenant policies refuse any request that carries app.support_grant_id,
--      as LLD-0 §4.2's standard pair does, so a support principal reaches identity rows
--      only through support_read (Staff 2's #32 note 1, LLD-0 v0.3 note 6).
--   2. platform.v_audit_log, LLD-0 §3.6's interim view: platform.audit_log plus the
--      legacy identity.audit_events rows mapped to its columns. The stock-era identity
--      routes still write the legacy table, so the copy (LLD-1 §3.6) and closing those
--      inserts move to the LLD-2 routes PR that replaces them; then this view is
--      redefined, with the same columns, to read platform.audit_log only.
-- Policies are altered in place; nothing is dropped.

-- `tenant` = nullif(current_setting('app.tenant_id', true), '')::uuid,
-- `me` = nullif(current_setting('app.user_id', true), '')::uuid, and
-- `not support` = coalesce(current_setting('app.support_grant_id', true), '') = ''.

-- 1. ------------------------------------------------------------------------------
-- businesses
alter policy biz_tenant on identity.businesses
    using (id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy biz_create on identity.businesses
    with check (id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and created_by = nullif(current_setting('app.user_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy biz_member_ro on identity.businesses
    using ((id = nullif(current_setting('app.tenant_id', true), '')::uuid or identity.is_active_member(id))
           and coalesce(current_setting('app.support_grant_id', true), '') = '');

-- memberships
alter policy m_tenant on identity.memberships
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy m_insert on identity.memberships
    with check (
        business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and coalesce(current_setting('app.support_grant_id', true), '') = ''
        and ((identity.caller_has_role(business_id, array['owner', 'admin'])
              and (role <> 'owner' or identity.caller_has_role(business_id, array['owner'])))
             or identity.is_bootstrap_owner(business_id, user_id, role))
    );
alter policy m_update on identity.memberships
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']))
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
                and identity.caller_has_role(business_id, array['owner', 'admin']));

-- support grants
alter policy sg_tenant on identity.support_grants
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner']))
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
                and identity.caller_has_role(business_id, array['owner']));
alter policy sg_tenant_read on identity.support_grants
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));
alter policy sg_ro on identity.support_grants
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));

-- legacy audit
alter policy ae_tenant on identity.audit_events
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy ae_ro on identity.audit_events
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy ae_insert on identity.audit_events
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
                and actor_sub = current_setting('app.user_sub', true));

-- invitations (until LLD-2 rewrites them)
alter policy inv_tenant on identity.invitations
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
alter policy inv_insert on identity.invitations
    with check (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and coalesce(current_setting('app.support_grant_id', true), '') = ''
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    );
alter policy inv_manage on identity.invitations
    using (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and coalesce(current_setting('app.support_grant_id', true), '') = ''
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    )
    with check (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and coalesce(current_setting('app.support_grant_id', true), '') = ''
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    );

-- 2. ------------------------------------------------------------------------------
-- security_invoker: each half is read under its own table's RLS as the caller, so a
-- caller sees exactly the audit rows of the business bound in app.tenant_id (and, from
-- platform.audit_log, their own user-level rows). Legacy rows map as LLD-1 §3.6's copy
-- will: actor_sub goes into data (identity.users is visible to app_rw only for the
-- caller's own row, so it can't be joined to a user_id here), target_id only when
-- entity_id is a uuid, reason from details, request_id 'legacy-copy'.
create view platform.v_audit_log with (security_invoker = true) as
select a.id, a.business_id, a.user_id, a.support_grant_id, a.action, a.target_kind,
       a.target_id, a.reason, a.data, a.request_id, a.at
from platform.audit_log a
union all
select e.id, e.tenant_id, null::uuid, null::uuid, e.action::text, e.entity_type::text,
       case when e.entity_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            then e.entity_id::uuid end,
       nullif(btrim(e.details::jsonb ->> 'reason'), ''),
       (e.details::jsonb - 'reason')
           || jsonb_build_object('actor_sub', e.actor_sub)
           || case when e.entity_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                   then '{}'::jsonb else jsonb_build_object('entity_id', e.entity_id) end,
       'legacy-copy', e.at
from identity.audit_events e;

grant select on platform.v_audit_log to app_rw, app_ro;
