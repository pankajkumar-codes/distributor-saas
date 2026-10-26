-- S0a (c2): support-grant checks, support reads, and the per-request session check.
--   1. platform.support_grant_active (LLD-0 §4.2 [L0v3-3]) and the audit_log support-view
--      insert policy [L0v3-2]. Both live here, not in platform's folder: the function is
--      `language sql`, so its body is checked against identity.support_grants at creation
--      and must sort after the reshape (build-readiness 2.4); platform_common's own tests
--      apply platform's folder without identity.
--   2. support_read on businesses and memberships (LLD-1 §3.4).
--   3. support_grants: writes owner-only, reads owner or admin (LLD-2 §2.4).
--   4. identity.auth_resolve (LLD-1 §6).
--   5. identity_auth loses CREATE on identity (202610251659 lent it for the reshape).
-- Nothing here drops or rewrites data; policies are created or altered in place.

-- `tenant` = nullif(current_setting('app.tenant_id', true), '')::uuid and
-- `me` = nullif(current_setting('app.user_id', true), '')::uuid, as in LLD-1 §3.4.

-- 1. ------------------------------------------------------------------------------
-- True only for the grant named by app.support_grant_id: that grant is for business b,
-- not revoked, in its window, and the caller is a support user. A grant goes to the
-- support team, so any support user may use it; each view records its own user_id.
create function platform.support_grant_active(b uuid) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select exists (
        select 1
        from identity.support_grants g
        join identity.users u on u.id = nullif(current_setting('app.user_id', true), '')::uuid
        where g.id = nullif(current_setting('app.support_grant_id', true), '')::uuid
          and g.business_id = b
          and g.revoked_at is null
          and now() between g.starts_at and g.expires_at
          and u.is_support
    )
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back.
grant create on schema platform to identity_auth;
alter function platform.support_grant_active(uuid) owner to identity_auth;
revoke create on schema platform from identity_auth;
revoke all on function platform.support_grant_active(uuid) from public;
grant execute on function platform.support_grant_active(uuid) to app_rw, app_ro;

-- A support principal writes exactly one kind of row: its own view of the business it
-- holds the named grant for. LLD-0 lists four conditions; the actor tie (user_id = me)
-- matches audit_business_insert's.
create policy audit_support_view on platform.audit_log for insert to app_rw
    with check (action = 'support.view'
                and business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and support_grant_id = nullif(current_setting('app.support_grant_id', true), '')::uuid
                and user_id = nullif(current_setting('app.user_id', true), '')::uuid
                and platform.support_grant_active(business_id));

-- 2. ------------------------------------------------------------------------------
-- FOR SELECT only: the database refuses any support write (HLD §5.1, RM3-9).
create policy support_read on identity.businesses for select to app_rw, app_ro
    using (platform.support_grant_active(id));
create policy support_read on identity.memberships for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

-- 3. ------------------------------------------------------------------------------
-- LLD-2 §2.4. sg_tenant (app_rw, all commands) narrows to the owner, so inserts and
-- updates are owner-only; sg_tenant_read adds admin reads; sg_ro (app_ro) matches it.
alter policy sg_tenant on identity.support_grants
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.caller_has_role(business_id, array['owner']))
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and identity.caller_has_role(business_id, array['owner']));
create policy sg_tenant_read on identity.support_grants for select to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.caller_has_role(business_id, array['owner', 'admin']));
alter policy sg_ro on identity.support_grants
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.caller_has_role(business_id, array['owner', 'admin']));

-- 4. ------------------------------------------------------------------------------
-- One call per request (LLD-1 §6). No row means no such user, which the caller treats
-- as session_invalid. `deny` is null when the caller may proceed. `touch` moves the
-- session's idle clock at most once a minute, and never in a read-only transaction.
create function identity.auth_resolve(
    p_key_kind text, p_key_value text, p_sub text, p_business_id uuid, p_touch boolean
) returns table (
    user_id uuid, session_id uuid, is_support boolean, role text,
    business_status text, support_grant_id uuid, deny text
)
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
#variable_conflict use_column
begin
    return query
    select u.id, s.id, u.is_support, m.role::text, b.status::text, g.id,
           case when s.id is null or s.revoked_at is not null
                     or s.last_activity_at < now() - interval '24 hours'   -- refdata auth.idle_hours
                     or s.absolute_expires_at <= now()                     then 'session_invalid'
                when p_business_id is null                                 then null
                when b.id is null or b.status = 'closed'                   then 'not_found'
                when m.id is null and not u.is_support                     then 'not_member'
                when m.id is null and g.id is null                         then 'support_no_grant'
                when m.id is not null and m.status <> 'active'             then 'not_member'
           end::text
    from identity.users u
    left join identity.sessions s
           on s.key_kind = p_key_kind and s.key_value = p_key_value and s.user_id = u.id
    left join identity.businesses b on b.id = p_business_id
    left join identity.memberships m on m.business_id = b.id and m.user_id = u.id
    -- Several live grants for one business: the one that lasts longest.
    left join lateral (
        select x.id from identity.support_grants x
        where u.is_support and x.business_id = b.id and x.revoked_at is null
          and now() between x.starts_at and x.expires_at
        order by x.expires_at desc, x.id
        limit 1
    ) g on true
    where u.cognito_sub = p_sub;

    if p_touch and current_setting('transaction_read_only') = 'off' then
        update identity.sessions x set last_activity_at = now()
        from identity.users u
        where u.cognito_sub = p_sub and x.user_id = u.id
          and x.key_kind = p_key_kind and x.key_value = p_key_value
          and x.revoked_at is null and x.absolute_expires_at > now()
          and x.last_activity_at >= now() - interval '24 hours'
          and x.last_activity_at < now() - interval '1 minute';
    end if;
end $$;
alter function identity.auth_resolve(text, text, text, uuid, boolean) owner to identity_auth;
revoke all on function identity.auth_resolve(text, text, text, uuid, boolean) from public;
-- app_rw only (LLD-1 §3.5). A read-only unit of work (none yet) resolves as app_rw
-- before it switches to app_ro, as LLD-2's two-step support flow does.
grant execute on function identity.auth_resolve(text, text, text, uuid, boolean) to app_rw;

-- 5. ------------------------------------------------------------------------------
revoke create on schema identity from identity_auth;
