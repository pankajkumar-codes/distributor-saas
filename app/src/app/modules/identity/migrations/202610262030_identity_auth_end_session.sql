-- Sign-out with an audit row (LLD-1 §5.7, §12 auth.signout). auth_revoke_session
-- returns only a boolean, and its return type can't change without a DROP, so this
-- adds a function that returns the revoked session and its user. The route binds the
-- unit of work to that user and writes the audit row in the same transaction.

-- Revokes the caller's own live session named by the token's key; the sub must match.
-- One row (session_id, user_id) if a session was revoked, none otherwise.
create function identity.auth_end_session(
    p_key_kind text, p_key_value text, p_sub text, p_reason text
) returns table (session_id uuid, user_id uuid)
language sql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
    update identity.sessions s set revoked_at = now(), revoke_reason = p_reason
    from identity.users u
    where u.cognito_sub = p_sub and s.user_id = u.id
      and s.key_kind = p_key_kind and s.key_value = p_key_value
      and s.revoked_at is null
    returning s.id, s.user_id
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_end_session(text, text, text, text) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_end_session(text, text, text, text) from public;
grant execute on function identity.auth_end_session(text, text, text, text) to app_rw;

-- Nothing calls the boolean version any more; app_rw loses it so there is one path.
revoke execute on function identity.auth_revoke_session(text, text, text, text) from app_rw;
