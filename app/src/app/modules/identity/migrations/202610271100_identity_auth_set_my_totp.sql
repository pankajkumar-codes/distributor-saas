-- users.totp_enabled_at for the bound caller (LLD-1 §5.9). app_rw may update only
-- users.name, so TOTP enrolment sets and clears the timestamp through this function. It
-- takes no user: it reads the unit of work's app.user_sub and app.user_id, as
-- auth_revoke_my_sessions does.

-- True if the bound user's row was updated; false if nothing is bound.
create function identity.auth_set_my_totp(p_on boolean)
returns boolean
language sql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
    with done as (
        update identity.users
        set totp_enabled_at = case when p_on then coalesce(totp_enabled_at, now()) end
        where cognito_sub = nullif(current_setting('app.user_sub', true), '')
          and id = nullif(current_setting('app.user_id', true), '')::uuid
        returning 1
    )
    select exists (select 1 from done)
$$;
-- The RDS master may hand a function only to a role with CREATE on its schema; the
-- right is lent for this statement and taken back (as in 202610261000).
grant create on schema identity to identity_auth;
alter function identity.auth_set_my_totp(boolean) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.auth_set_my_totp(boolean) from public;
grant execute on function identity.auth_set_my_totp(boolean) to app_rw;
