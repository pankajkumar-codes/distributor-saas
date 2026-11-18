-- One active session per user: a session counts as "live" only if it was used in the last
-- auth.session_live_minutes (30), not in the last 24 hours (R1 retest item 6).
--
-- Why: a demo seed or a browser closed without signing out left a session row that stayed live
-- for a day, so the owner's own next sign-in was asked "One session is already active". The
-- 24-hour idle rule still governs whether a session works; this only decides whether a new
-- sign-in has to ask. When it does not ask, sessions that are unrevoked but past the window are
-- ended (reason 'replaced') in the same transaction, so there is never a second usable session
-- behind the new one.

create or replace function identity.auth_open_session_once(
    p_id uuid, p_user_id uuid, p_key_kind text, p_key_value text, p_auth_time timestamptz, p_max_days int
) returns boolean
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
begin
    perform 1 from identity.users where id = p_user_id for update;
    if exists (
        select 1 from identity.sessions s
        where s.user_id = p_user_id and s.revoked_at is null
          and s.absolute_expires_at > now()
          and s.last_activity_at >= now() - interval '30 minutes'   -- refdata auth.session_live_minutes
    ) then
        return false;
    end if;
    update identity.sessions s set revoked_at = now(), revoke_reason = 'replaced'
    where s.user_id = p_user_id and s.revoked_at is null;
    insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, absolute_expires_at)
    values (p_id, p_user_id, p_key_kind, p_key_value, p_auth_time, now() + make_interval(days => p_max_days));
    return true;
end $$;
-- Owner, grants and the signature are unchanged from 202611190900.
