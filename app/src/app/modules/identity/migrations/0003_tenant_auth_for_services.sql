-- Lets the other services check "is the caller an active member of this tenant, and
-- with which role" without any grant on identity tables (T-001, ADR 0001 section 1).
-- They call two security-definer functions that only ever answer for the caller set
-- in app.user_sub, so a service cannot list or read other users' memberships.

create function identity.caller_role(t uuid) returns text
language sql stable security definer set search_path = identity as $$
    select role from identity.memberships
    where tenant_id = t
      and user_sub = current_setting('app.user_sub', true)
      and status = 'active'
$$;
revoke all on function identity.caller_role(uuid) from public;
grant execute on function identity.caller_role(uuid) to svc_identity;

-- One group role carries the access; each service login is a member of it.
do $$ begin
    if not exists (select from pg_roles where rolname = 'tenant_auth') then
        create role tenant_auth nologin;
    end if;
end $$;
grant usage on schema identity to tenant_auth;
grant execute on function identity.is_member(uuid), identity.caller_role(uuid) to tenant_auth;

-- Service logins (svc_<service>, see infra/modules/service) are created here when
-- missing, so they exist before any service's own migrations reference them.
do $$
declare svc text;
begin
    foreach svc in array array['svc_commerce', 'svc_imports', 'svc_reports', 'svc_documents'] loop
        if not exists (select from pg_roles where rolname = svc) then
            execute 'create role ' || quote_ident(svc) || ' login';
        end if;
        execute 'grant rds_iam to ' || quote_ident(svc);
        execute 'grant tenant_auth to ' || quote_ident(svc);
    end loop;
end $$;
