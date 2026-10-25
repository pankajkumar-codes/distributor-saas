-- Shared idempotency keys for every module (LLD-0 §3.8, L0-2). One row per (scope, key):
-- scope is the business for /b/* routes and the user for /me routes. Public routes take no
-- key (RM4-8). Rows older than 24 h are purged by the retention job (not built yet).

create schema if not exists platform;
grant usage on schema platform to app_rw;

create table platform.idempotency_keys (
    scope uuid not null,
    key varchar(200) not null,
    request_hash char(64) not null,
    response jsonb,
    created_at timestamptz not null default now(),
    primary key (scope, key)
);
create index idempotency_keys_created_at on platform.idempotency_keys (created_at);

alter table platform.idempotency_keys enable row level security;
alter table platform.idempotency_keys force row level security;

-- A key is visible and writable only inside its own business or user's unit of work.
create policy idempotency_scope on platform.idempotency_keys to app_rw
    using (scope = nullif(current_setting('app.tenant_id', true), '')::uuid
           or scope = nullif(current_setting('app.user_id', true), '')::uuid)
    with check (scope = nullif(current_setting('app.tenant_id', true), '')::uuid
                or scope = nullif(current_setting('app.user_id', true), '')::uuid);

grant select, insert, update on platform.idempotency_keys to app_rw;
