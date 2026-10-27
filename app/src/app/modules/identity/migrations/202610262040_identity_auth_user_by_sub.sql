-- Sign-in (LLD-1 §5.3). The provider's verified token names the user only by `sub`;
-- a public unit of work has no user yet, so users' RLS has nothing to key on. Like
-- auth_user_by_email this reads one row through a definer function (L1-3).

-- The user with this sub, or no row: a provider user with no users row is refused.
create function identity.auth_user_by_sub(p_sub text) returns table (user_id uuid, email text)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select id, email from identity.users where cognito_sub = p_sub
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_user_by_sub(text) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_user_by_sub(text) from public;
grant execute on function identity.auth_user_by_sub(text) to app_rw;
