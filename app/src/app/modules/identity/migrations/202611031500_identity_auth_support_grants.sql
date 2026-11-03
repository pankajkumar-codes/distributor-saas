-- S2-d: support's own list of grants (LLD-2 §6.2): GET /support/grants.
--
-- identity.auth_support_grants() is a definer owned by identity_auth. It acts for the
-- bound caller only (identity.auth_support_caller(): app.user_sub and app.user_id name a
-- support user with TOTP on), never for a user ID passed in. It returns the grants that
-- are live now (started, not expired, not revoked) on businesses that aren't closed, with the
-- business's display name and the grant's expiry. Anyone else gets no rows; the route
-- answers them 404 before calling it. app_rw can't read other businesses' grants or
-- names itself (sg_tenant, the businesses policies), so the definer is the only way in.

grant create on schema identity to identity_auth;
set role identity_auth;

create function identity.auth_support_grants()
returns table (grant_id uuid, business_id uuid, business_name text, expires_at timestamptz)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select g.id, g.business_id, b.name::text, g.expires_at
    from identity.support_grants g
    join identity.businesses b on b.id = g.business_id
    where identity.auth_support_caller() is not null
      and b.status <> 'closed'  -- as auth_resolve: a closing business is still open to support
      and g.revoked_at is null
      and g.starts_at <= now() and now() < g.expires_at
    order by g.expires_at, g.business_id
$$;

reset role;
revoke create on schema identity from identity_auth;

revoke all on function identity.auth_support_grants() from public;
grant execute on function identity.auth_support_grants() to app_rw;
