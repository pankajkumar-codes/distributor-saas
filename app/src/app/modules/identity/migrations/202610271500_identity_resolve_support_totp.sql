-- S2-a: a support user without TOTP is refused on every business route (LLD-2 L2-5,
-- AC2-10): identity.auth_resolve answers session_invalid (401) for an is_support caller
-- with no totp_enabled_at once a business is named. /me is unchanged, so a new support
-- user can still turn TOTP on. Same signature and result as 202610261000, replaced in
-- place; the owner and the app_rw-only grant carry over. Only its owner may replace it,
-- and the owner needs CREATE on the schema to do so, lent here and taken back.

grant create on schema identity to identity_auth;
set role identity_auth;
create or replace function identity.auth_resolve(
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
                when u.is_support and u.totp_enabled_at is null            then 'session_invalid'
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
reset role;
revoke create on schema identity from identity_auth;
