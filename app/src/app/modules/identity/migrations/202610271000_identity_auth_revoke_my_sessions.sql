-- Sign out everywhere for the bound caller only (LLD-1 §5.7; Staff, #48). Unlike
-- auth_revoke_user_sessions, which reset needs before any user is bound, this takes no
-- sub: it reads the unit of work's app.user_sub and app.user_id, so a future caller
-- can't sign out somebody else by passing the wrong argument.

-- Revokes the bound user's live sessions; one row (user_id, revoked count), or none if
-- the unit of work isn't bound to a user.
create function identity.auth_revoke_my_sessions(p_reason text)
returns table (user_id uuid, revoked int)
language sql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
    with u as (
        select id from identity.users
        where cognito_sub = nullif(current_setting('app.user_sub', true), '')
          and id = nullif(current_setting('app.user_id', true), '')::uuid
    ),
    done as (
        update identity.sessions s set revoked_at = now(), revoke_reason = p_reason
        from u where s.user_id = u.id and s.revoked_at is null
        returning 1
    )
    select u.id, (select count(*) from done)::int from u
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_revoke_my_sessions(text) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_revoke_my_sessions(text) from public;
grant execute on function identity.auth_revoke_my_sessions(text) to app_rw;
