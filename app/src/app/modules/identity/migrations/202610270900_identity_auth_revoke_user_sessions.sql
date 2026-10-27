-- Revoking every session of one user (LLD-1 §5.7 sign out everywhere, §5.8 reset,
-- §5.9 password change). Keyed on the provider's sub, like auth_end_session: callers
-- pass a sub the provider just vouched for (a reset's set_password, a verified token).

-- Revokes the user's live sessions with `p_reason`; one row (user_id, revoked count),
-- or none if no user has this sub.
create function identity.auth_revoke_user_sessions(p_sub text, p_reason text)
returns table (user_id uuid, revoked int)
language sql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
    with u as (select id from identity.users where cognito_sub = p_sub),
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
alter function identity.auth_revoke_user_sessions(text, text) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_revoke_user_sessions(text, text) from public;
grant execute on function identity.auth_revoke_user_sessions(text, text) to app_rw;
