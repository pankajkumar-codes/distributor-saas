-- Cluster-wide roles of the approved design (LLD-0 §4.1 [RM4-6], build-readiness 2.8).
-- Runs as the master user on every migrator run, before and after the ledger files, so it
-- must stay idempotent: roles are only created when missing, and every other statement
-- is naturally repeatable. It is not a ledger file and is not checksummed.
--
-- Login roles authenticate with IAM on RDS (rds_iam); NOLOGIN roles only own objects or
-- are reached with SET ROLE. None of them may bypass RLS (QA role guards, build-readiness 2.6).
-- The owner of platform.support_grant_active is identity_auth (proposed in build-readiness
-- 2.8, to be confirmed in the S0a PR), so it needs no role of its own here.

do $$
declare
    r record;
begin
    for r in
        select * from (values
            ('app_owner', false),        -- owns every schema, table, view and function (LLD-0 §4.1)
            ('app_rw', true),            -- API and worker Lambdas
            ('app_ro', false),           -- SET LOCAL ROLE in read-only units of work (L0-7)
            ('app_retention', true),     -- daily retention job only
            ('retention_owner', false),  -- owns retention.* definer functions (RM4-1)
            ('platform_ops', false),     -- owns outbox/jobs definer functions (RM4-2; LLD-5, LLD-6 reuse it)
            ('identity_auth', false),    -- owns identity.auth_* definer functions (LLD-1 L1-3)
            ('share_ops', false)         -- owns sales.open_share (LLD-4 L4-7)
        ) as t(name, login)
    loop
        if not exists (select from pg_roles where rolname = r.name) then
            execute format('create role %I', r.name);
        end if;
        execute format(
            'alter role %I %s nosuperuser nocreatedb nocreaterole noreplication nobypassrls',
            r.name, case when r.login then 'login' else 'nologin' end);
    end loop;

    -- The migrator reaches app_owner with SET ROLE but doesn't hold its rights by default.
    execute format('grant app_owner to %I with set true, inherit false', current_user);
    execute format('grant create on database %I to app_owner', current_database());

    grant app_ro to app_rw;

    -- RDS provides rds_iam; plain PostgreSQL (CI, local) does not.
    if exists (select from pg_roles where rolname = 'rds_iam') then
        grant rds_iam to app_rw, app_retention;
    end if;

    -- Bridge to the legacy identity roles (L0-5). The grandfathered files create them,
    -- so on a fresh database they appear only after the ledger; hence the second run.
    for r in select rolname from pg_roles where rolname in ('svc_identity', 'tenant_auth') loop
        execute format('grant %I to app_rw with inherit true', r.rolname);
    end loop;
end $$;
