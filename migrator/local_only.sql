-- Local and CI databases only. migrator.local applies this after the ledger; the
-- migrator Lambda never does, and scripts/build_lambda.sh doesn't package this file,
-- so none of it exists in AWS.
--
-- dev_ensure_user stands in for S1 sign-up while callers are named by X-Debug-User:
-- it returns the identity.users id for a sub, creating the row on first use with a
-- placeholder email (invitations match the caller's verified email instead). The API
-- calls it only when PLATFORM_ENV is local or test (app.modules.identity.api).

create or replace function identity.dev_ensure_user(sub text) returns uuid
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    uid uuid;
begin
    select id into uid from identity.users where cognito_sub = sub;
    if uid is null then
        insert into identity.users (id, cognito_sub, email)
        values (gen_random_uuid(), sub, lower(sub) || '@debug.invalid')
        on conflict (cognito_sub) do nothing
        returning id into uid;
        if uid is null then
            select id into uid from identity.users where cognito_sub = sub;
        end if;
    end if;
    return uid;
end $$;
alter function identity.dev_ensure_user(text) owner to identity_auth;
revoke all on function identity.dev_ensure_user(text) from public;
grant execute on function identity.dev_ensure_user(text) to app_rw;

-- dev_ensure_session stands in for S1 sign-in the same way: a live session keyed
-- ('sid', 'debug:' || sub) for an X-Debug-User caller, so the principal resolver runs
-- identity.auth_resolve unchanged. A revoked or lapsed debug session is reopened.
create or replace function identity.dev_ensure_session(sub text) returns void
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
begin
    insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, absolute_expires_at)
    values (gen_random_uuid(), identity.dev_ensure_user(sub), 'sid', 'debug:' || sub, now(), now() + interval '30 days')
    on conflict (key_kind, key_value) do update
        set revoked_at = null, revoke_reason = null, last_activity_at = now(),
            absolute_expires_at = greatest(identity.sessions.absolute_expires_at, now() + interval '1 day');
end $$;
alter function identity.dev_ensure_session(text) owner to identity_auth;
revoke all on function identity.dev_ensure_session(text) from public;
grant execute on function identity.dev_ensure_session(text) to app_rw;
