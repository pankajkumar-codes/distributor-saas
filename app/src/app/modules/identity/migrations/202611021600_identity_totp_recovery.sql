-- S2-b: TOTP recovery by support (LLD-2 §6.3, L2-6, TD-4a; AC2-11, AC2-14, AC2-16).
--
-- 1. verification_codes takes a third purpose, totp_recovery. The check is dropped and
--    added again with the old two values plus the new one; no row changes.
-- 2. auth_check_code treats totp_recovery like reset: the code is only good for an email
--    that has an account. Same signature, replaced in place by its owner.
-- 3. Two definer functions, both acting for the bound support caller only (app.user_sub
--    and app.user_id, as auth_set_my_totp does), never for a user ID passed in:
--    - auth_issue_totp_recovery_code issues a code only for a non-support account with
--      TOTP on. It returns whether it did, and takes the same lock either way;
--    - auth_totp_recovery_complete consumes a claimed code, clears totp_enabled_at,
--      revokes the account's sessions ('support'), and writes the user-level audit row
--      auth.totp_removed_by_support. The row belongs to the account (user_id, so its
--      owner sees it) and names the support user in data.support_user_id.
-- 4. audit_auth_insert admits that one action, user-level, about its own user, written
--    by a live support user with TOTP on, and nothing else new (Staff 2 (4), #59 plan).
-- 5. AC2-14: a support user can't hold a membership, and a user with a membership can't
--    be made support. A support user who is also a member would reach business routes
--    as a member (no TOTP rule, no grant, no support.view row), so this is the fix for
--    Staff 2 (3)'s note 3 on #59, not a documentation item.

alter table identity.verification_codes
    drop constraint verification_codes_purpose_check,
    add constraint verification_codes_purpose_check check (purpose in ('signup', 'reset', 'totp_recovery'));

-- Only the owner may replace a function, and the owner needs CREATE on the schema to do
-- so: lent here and taken back, as in 202610271500.
grant create on schema identity to identity_auth;
set role identity_auth;

create or replace function identity.auth_check_code(p_purpose text, p_email text, p_hmac bytea) returns uuid
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
    if has_user <> (p_purpose in ('reset', 'totp_recovery')) then
        return null;
    end if;
    update identity.verification_codes set claimed_at = now() where id = c.id;
    return c.id;
end $$;

-- The bound caller, if it is a support user with TOTP on; else null.
create function identity.auth_support_caller() returns uuid
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select id from identity.users
    where cognito_sub = nullif(current_setting('app.user_sub', true), '')
      and id = nullif(current_setting('app.user_id', true), '')::uuid
      and is_support and totp_enabled_at is not null
$$;

-- True if a code was stored for `p_email`. Both branches take the same advisory lock
-- auth_issue_code takes, so neither the answer's timing nor a 500 tells them apart.
create function identity.auth_issue_totp_recovery_code(
    p_id uuid, p_email text, p_hmac bytea, p_ttl interval, p_max_tries int
) returns boolean
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    e text := lower(btrim(p_email));
    me uuid := identity.auth_support_caller();
begin
    if me is null then
        raise exception 'auth_issue_totp_recovery_code: the caller is not support with TOTP on'
            using errcode = '42501';
    end if;
    if not exists (select 1 from identity.users u
                   where u.email = e and u.totp_enabled_at is not null and not u.is_support) then
        perform pg_advisory_xact_lock(hashtextextended('totp_recovery:' || e, 0));
        return false;
    end if;
    perform identity.auth_issue_code(p_id, 'totp_recovery', e, p_hmac, p_ttl, p_max_tries);
    return true;
end $$;

-- After the provider removed the account's TOTP: one row (user_id, email) for the
-- account, or none if the code isn't claimed and live, the account has no TOTP any more
-- or is support, or its sub isn't `p_sub` (the provider user support just changed).
create function identity.auth_totp_recovery_complete(p_code_id uuid, p_sub text, p_audit_id uuid)
returns table (user_id uuid, email text)
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
#variable_conflict use_column
declare
    me uuid := identity.auth_support_caller();
    c identity.verification_codes%rowtype;
    target identity.users%rowtype;
begin
    if me is null then
        raise exception 'auth_totp_recovery_complete: the caller is not support with TOTP on'
            using errcode = '42501';
    end if;
    select * into c from identity.verification_codes v
    where v.id = p_code_id and v.purpose = 'totp_recovery'
      and v.claimed_at is not null and v.consumed_at is null and v.voided_at is null
    for update;
    if not found then
        return;
    end if;
    select * into target from identity.users u
    where u.email = c.email and u.cognito_sub = p_sub and not u.is_support and u.id <> me
    for update;
    if not found then
        return;
    end if;
    update identity.verification_codes set consumed_at = now() where id = c.id;
    -- TOTP already off here (a retry after this step committed once) still finishes: the
    -- provider has just removed it, and the code is spent either way.
    update identity.users set totp_enabled_at = null where id = target.id;
    update identity.sessions set revoked_at = now(), revoke_reason = 'support'
    where identity.sessions.user_id = target.id and revoked_at is null;
    insert into platform.audit_log (id, business_id, user_id, action, target_kind, target_id, data, request_id)
    values (p_audit_id, null, target.id, 'auth.totp_removed_by_support', 'user', target.id,
            jsonb_build_object('support_user_id', me::text),
            coalesce(nullif(current_setting('app.request_id', true), ''), 'unknown'));
    return query select target.id, target.email;
end $$;

-- AC2-14 (LLD-2 §6.2): support users never hold memberships, in either order. The guards
-- are definers owned by identity_auth, so they see every user and membership whoever
-- writes the row (app_rw sees only its own users row). They run after the row, so RLS
-- refuses a write it doesn't allow first, with its own error.
create function identity.guard_support_membership() returns trigger
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
begin
    if new.status = 'active' and exists (select 1 from identity.users where id = new.user_id and is_support) then
        raise exception 'a support user can''t be a member of a business' using errcode = 'IDS01';
    end if;
    return new;
end $$;
create function identity.guard_support_flag() returns trigger
language plpgsql security definer set search_path = pg_catalog, identity, pg_temp as $$
begin
    if new.is_support and not old.is_support
       and exists (select 1 from identity.memberships where user_id = new.id and status = 'active') then
        raise exception 'a member of a business can''t be made a support user' using errcode = 'IDS01';
    end if;
    return new;
end $$;
reset role;
revoke create on schema identity from identity_auth;

-- The new functions were created by identity_auth, so it owns them already.
revoke all on function identity.guard_support_membership() from public;
revoke all on function identity.guard_support_flag() from public;
revoke all on function identity.auth_support_caller() from public;
revoke all on function identity.auth_issue_totp_recovery_code(uuid, text, bytea, interval, int) from public;
revoke all on function identity.auth_totp_recovery_complete(uuid, text, uuid) from public;
grant execute on function identity.auth_issue_totp_recovery_code(uuid, text, bytea, interval, int) to app_rw;
grant execute on function identity.auth_totp_recovery_complete(uuid, text, uuid) to app_rw;

-- Narrow: member.accept as before, plus this one user-level action about its own user,
-- written while the bound caller is live support with TOTP on. Any other action, a
-- business row, a grant, or a row about someone else is refused.
alter policy audit_auth_insert on platform.audit_log
    with check (
        (action = 'member.accept' and business_id is not null and support_grant_id is null)
        or (action = 'auth.totp_removed_by_support'
            and business_id is null and support_grant_id is null
            and target_kind = 'user' and target_id = user_id
            and data ->> 'support_user_id' = identity.auth_support_caller()::text)
    );

create trigger memberships_no_support after insert or update of status, user_id on identity.memberships
    for each row execute function identity.guard_support_membership();

create trigger users_no_member_support after update of is_support on identity.users
    for each row execute function identity.guard_support_flag();
