-- identity schema. Applied by the migrator Lambda as the master user.
create schema if not exists identity;

create table identity.tenants (
    id uuid primary key,
    name varchar(200) not null,
    created_at timestamptz not null default now()
);

create table identity.memberships (
    id uuid primary key,
    tenant_id uuid not null references identity.tenants(id),
    user_sub varchar(128) not null,
    role varchar(20) not null check (role in ('owner','admin','sales','inventory','finance','viewer')),
    status varchar(20) not null default 'active' check (status in ('active','disabled')),
    created_at timestamptz not null default now(),
    unique (tenant_id, user_sub)
);
create index on identity.memberships (user_sub);

create table identity.audit_events (
    id uuid primary key,
    tenant_id uuid not null references identity.tenants(id),
    actor_sub varchar(128) not null,
    action varchar(80) not null,
    entity_type varchar(80) not null,
    entity_id varchar(80) not null,
    details json not null default '{}',
    at timestamptz not null default now()
);
create index on identity.audit_events (tenant_id, at desc);

-- The service's own login, authenticated with IAM tokens instead of a password.
do $$ begin
    if not exists (select from pg_roles where rolname = 'svc_identity') then
        create role svc_identity login;
    end if;
end $$;
grant rds_iam to svc_identity;
grant usage on schema identity to svc_identity;
grant select, insert, update on identity.tenants, identity.memberships to svc_identity;
-- Audit is append-only for the service.
grant select, insert on identity.audit_events to svc_identity;
