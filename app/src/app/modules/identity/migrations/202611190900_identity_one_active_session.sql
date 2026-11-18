-- One active session per user (R1 retest item 5).
--
-- A sign-in from a second browser must not silently start a second session. Two functions,
-- both run under a row lock on the user so two sign-ins at once are decided one at a time:
--
--   auth_open_session_once   opens the session only if the user has no live one. Live means as
--                            auth_resolve reads it: not revoked, active in the last 24 hours
--                            (refdata auth.idle_hours) and before its absolute expiry. If there
--                            is one it opens nothing and answers false; the caller then asks
--                            the person, and the new tokens work only for that question
--                            because auth_resolve finds no session row for them.
--   auth_replace_session     the person said yes: ends the user's live sessions with reason
--                            'replaced' and opens the new one. The sub is checked against the
--                            user, so a token can only replace its own user's sessions.
--
-- Sign-up keeps auth_open_session: a new account has no other session.

alter table identity.sessions drop constraint sessions_revoke_reason_check;
alter table identity.sessions add constraint sessions_revoke_reason_check check (revoke_reason in
    ('signout', 'password_change', 'password_reset', 'signout_all', 'closure', 'support', 'replaced'));

create function identity.auth_open_session_once(
    p_id uuid, p_user_id uuid, p_key_kind text, p_key_value text, p_auth_time timestamptz, p_max_days int
) returns boolean
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
begin
    perform 1 from identity.users where id = p_user_id for update;
    if exists (
        select 1 from identity.sessions s
        where s.user_id = p_user_id and s.revoked_at is null
          and s.absolute_expires_at > now()
          and s.last_activity_at >= now() - interval '24 hours'   -- refdata auth.idle_hours
    ) then
        return false;
    end if;
    insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, absolute_expires_at)
    values (p_id, p_user_id, p_key_kind, p_key_value, p_auth_time, now() + make_interval(days => p_max_days));
    return true;
end $$;

-- One row (user_id, revoked, opened) when the new session is open: `revoked` is how many live sessions
-- it ended, and `opened` is false on a retry of the same confirmation. No row when the sub is unknown or the key's
-- session was already ended, which the caller treats as session_invalid.
create function identity.auth_replace_session(
    p_id uuid, p_sub text, p_key_kind text, p_key_value text, p_auth_time timestamptz, p_max_days int
) returns table (user_id uuid, revoked int, opened boolean)
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    uid uuid;
    existing identity.sessions%rowtype;
    ended int;
begin
    select u.id into uid from identity.users u where u.cognito_sub = p_sub for update;
    if uid is null then
        return;
    end if;
    select * into existing from identity.sessions s where s.key_kind = p_key_kind and s.key_value = p_key_value;
    if found then
        if existing.user_id = uid and existing.revoked_at is null then
            return query select uid, 0, false;
        end if;
        return;
    end if;
    update identity.sessions s set revoked_at = now(), revoke_reason = 'replaced'
    where s.user_id = uid and s.revoked_at is null;
    get diagnostics ended = row_count;
    insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, absolute_expires_at)
    values (p_id, uid, p_key_kind, p_key_value, p_auth_time, now() + make_interval(days => p_max_days));
    return query select uid, ended, true;
end $$;

-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for these statements and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_open_session_once(uuid, uuid, text, text, timestamptz, int) owner to identity_auth;
alter function identity.auth_replace_session(uuid, text, text, text, timestamptz, int) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_open_session_once(uuid, uuid, text, text, timestamptz, int),
    identity.auth_replace_session(uuid, text, text, text, timestamptz, int) from public;
grant execute on function identity.auth_open_session_once(uuid, uuid, text, text, timestamptz, int),
    identity.auth_replace_session(uuid, text, text, text, timestamptz, int) to app_rw;
