-- R1 retest bug 3: GET /support/grants answered 500 for any live grant.
--
-- The list read the business's name from identity.businesses.name, but a business made
-- through POST /b has no name there (its names live in business.profiles, which support's
-- list cannot read across businesses). The grant now keeps the business's display name as
-- the owner saw it when giving access (the same snapshot idea as invitations.business_name),
-- and the list returns that. Rows made before this have none; the route shows a plain
-- fallback for them. A new nullable column with a length check: no row changes.
alter table identity.support_grants
    add column business_name varchar(200) check (business_name is null or char_length(business_name) >= 1);

grant create on schema identity to identity_auth;
set role identity_auth;

create or replace function identity.auth_support_grants()
returns table (grant_id uuid, business_id uuid, business_name text, expires_at timestamptz)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select g.id, g.business_id, coalesce(g.business_name, b.name)::text, g.expires_at
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
