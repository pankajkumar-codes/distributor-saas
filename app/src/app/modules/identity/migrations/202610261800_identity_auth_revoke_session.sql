-- Sign-out (LLD-1 §5.7). Refresh needs no new function: identity.auth_resolve with no
-- business is §5.5's session check (revoked, 24 h idle, 30-day absolute expiry).

-- Revokes the caller's own live session named by the token's key. The sub must match,
-- so a token can only revoke its own user's row. True if a row was revoked.
create function identity.auth_revoke_session(
    p_key_kind text, p_key_value text, p_sub text, p_reason text
) returns boolean
language sql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
    with done as (
        update identity.sessions s set revoked_at = now(), revoke_reason = p_reason
        from identity.users u
        where u.cognito_sub = p_sub and s.user_id = u.id
          and s.key_kind = p_key_kind and s.key_value = p_key_value
          and s.revoked_at is null
        returning 1
    )
    select exists (select 1 from done)
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_revoke_session(text, text, text, text) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_revoke_session(text, text, text, text) from public;
grant execute on function identity.auth_revoke_session(text, text, text, text) to app_rw;
