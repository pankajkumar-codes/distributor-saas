-- The audit log (LLD-0 §3.6) and rate counters (LLD-0 §3.9), for S1 auth (LLD-1).

-- Audit: insert-only for the app. Business rows belong to one business; user-level rows
-- (sign-in, TOTP changes) have no business and belong to one user.
create table platform.audit_log (
    id uuid primary key,
    business_id uuid,
    user_id uuid,
    support_grant_id uuid,
    action text not null,
    target_kind text not null,
    target_id uuid,
    reason text,
    data jsonb not null default '{}',
    request_id text not null,
    at timestamptz not null default now(),
    check (business_id is not null or user_id is not null)
);
create index audit_log_business_at on platform.audit_log (business_id, at desc);
create index audit_log_business_action_at on platform.audit_log (business_id, action, at desc);
create index audit_log_user_at on platform.audit_log (user_id, at desc) where business_id is null;

alter table platform.audit_log enable row level security;
alter table platform.audit_log force row level security;

-- Business rows: only inside that business's unit of work, and not under a support grant
-- [L0v3-3]. The support-view insert policy [L0v3-2] needs platform.support_grant_active,
-- which arrives with the identity reshape (S0a c); it is added there or with LLD-2.
create policy audit_business_select on platform.audit_log for select to app_rw, app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy audit_business_insert on platform.audit_log for insert to app_rw
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
                and support_grant_id is null);

-- User-level rows: the user's own, written as that user.
create policy audit_user_select on platform.audit_log for select to app_rw, app_ro
    using (business_id is null and user_id = nullif(current_setting('app.user_id', true), '')::uuid);
create policy audit_user_insert on platform.audit_log for insert to app_rw
    with check (business_id is null and support_grant_id is null
                and user_id = nullif(current_setting('app.user_id', true), '')::uuid);

grant usage on schema platform to app_ro;
grant select, insert on platform.audit_log to app_rw;
grant select on platform.audit_log to app_ro;

-- Rate counters: global, no RLS (listed as global for the migrations lint). Buckets are
-- HMACs, never a raw email or IP, so the table holds no tenant or personal data.
create table platform.rate_counters (
    bucket text not null,
    window_start timestamptz not null,
    count int not null,
    primary key (bucket, window_start)
);
grant select, insert, update on platform.rate_counters to app_rw;
