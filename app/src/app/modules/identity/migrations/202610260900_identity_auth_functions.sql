-- Sign-up codes, users and sessions (LLD-1 §3.5, §5.1, §5.2, §5.6). app_rw has no grant on
-- sessions, pending_signups or verification_codes (AC-9); it reaches them only through
-- these SECURITY DEFINER functions, owned by identity_auth and executable by app_rw only.
-- IDs come from Python (uuid7, LLD-0 L0-8). Emails are normalised here as well as in the
-- app, so a caller can't open a second account with a case or whitespace variant (AC-5).

create function identity.auth_user_by_email(p_email text) returns uuid
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select id from identity.users where email = lower(btrim(p_email))
$$;

-- Voids any live code for this email and purpose and stores the new one. A sign-up
-- also upserts the pending sign-up (purged 24 h after created_at by retention).
create function identity.auth_issue_code(
    p_id uuid, p_purpose text, p_email text, p_hmac bytea, p_ttl interval, p_max_tries int
) returns void
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    e text := lower(btrim(p_email));
begin
    if p_purpose = 'signup' then
        insert into identity.pending_signups (email, last_code_at) values (e, now())
        on conflict (email) do update set last_code_at = now();
    end if;
    update identity.verification_codes set voided_at = now()
    where purpose = p_purpose and email = e and consumed_at is null and voided_at is null;
    insert into identity.verification_codes (id, purpose, email, code_hmac, max_tries, expires_at)
    values (p_id, p_purpose, e, p_hmac, p_max_tries, now() + p_ttl);
end $$;

-- Counts one try on the live code and returns its id if the code is right, else null.
-- The caller commits this in its own transaction whatever the answer, so a counted
-- wrong try survives a later failure (AC-3). Null covers every refusal alike: no live
-- code, expired, claimed by another verify in the last 60 s (AC-4), wrong (the try
-- that reaches max_tries voids it), or a sign-up for an email that already has an
-- account (RM3-7) / a reset for one that has none.
create function identity.auth_check_code(p_purpose text, p_email text, p_hmac bytea) returns uuid
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    e text := lower(btrim(p_email));
    c identity.verification_codes%rowtype;
    has_user boolean;
begin
    select * into c from identity.verification_codes
    where purpose = p_purpose and email = e and consumed_at is null and voided_at is null
    for update;
    if not found then
        return null;
    end if;
    update identity.verification_codes set tries = tries + 1 where id = c.id;
    if c.expires_at <= now() or (c.claimed_at is not null and c.claimed_at > now() - interval '60 seconds') then
        return null;
    end if;
    if c.code_hmac <> p_hmac then
        if c.tries + 1 >= c.max_tries then
            update identity.verification_codes set voided_at = now() where id = c.id;
        end if;
        return null;
    end if;
    has_user := exists (select 1 from identity.users where email = e);
    if has_user <> (p_purpose = 'reset') then
        return null;
    end if;
    update identity.verification_codes set claimed_at = now() where id = c.id;
    return c.id;
end $$;

-- True once, for a code claimed by auth_check_code and not yet consumed or voided.
create function identity.auth_consume_code(p_code_id uuid) returns boolean
language sql security definer set search_path = pg_catalog, identity, pg_temp as $$
    with done as (
        update identity.verification_codes set consumed_at = now()
        where id = p_code_id and claimed_at is not null and consumed_at is null and voided_at is null
        returning 1
    )
    select exists (select 1 from done)
$$;

create function identity.auth_create_user(p_id uuid, p_sub text, p_email text) returns void
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    e text := lower(btrim(p_email));
begin
    insert into identity.users (id, cognito_sub, email) values (p_id, p_sub, e);
    delete from identity.pending_signups where email = e;
end $$;

create function identity.auth_open_session(
    p_id uuid, p_user_id uuid, p_key_kind text, p_key_value text, p_auth_time timestamptz, p_max_days int
) returns void
language sql security definer set search_path = pg_catalog, identity, pg_temp as $$
    insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, absolute_expires_at)
    values (p_id, p_user_id, p_key_kind, p_key_value, p_auth_time, now() + make_interval(days => p_max_days))
$$;

grant delete on identity.pending_signups to identity_auth;

alter function identity.auth_user_by_email(text) owner to identity_auth;
alter function identity.auth_issue_code(uuid, text, text, bytea, interval, int) owner to identity_auth;
alter function identity.auth_check_code(text, text, bytea) owner to identity_auth;
alter function identity.auth_consume_code(uuid) owner to identity_auth;
alter function identity.auth_create_user(uuid, text, text) owner to identity_auth;
alter function identity.auth_open_session(uuid, uuid, text, text, timestamptz, int) owner to identity_auth;
revoke all on function identity.auth_user_by_email(text),
    identity.auth_issue_code(uuid, text, text, bytea, interval, int),
    identity.auth_check_code(text, text, bytea),
    identity.auth_consume_code(uuid),
    identity.auth_create_user(uuid, text, text),
    identity.auth_open_session(uuid, uuid, text, text, timestamptz, int) from public;
grant execute on function identity.auth_user_by_email(text),
    identity.auth_issue_code(uuid, text, text, bytea, interval, int),
    identity.auth_check_code(text, text, bytea),
    identity.auth_consume_code(uuid),
    identity.auth_create_user(uuid, text, text),
    identity.auth_open_session(uuid, uuid, text, text, timestamptz, int) to app_rw;
