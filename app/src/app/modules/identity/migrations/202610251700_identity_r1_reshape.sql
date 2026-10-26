-- destructive: approved by CEO 2026-10-24 (LLD-1 §3.3 RM41-1: drops policies, the memberships unique constraint and its role and status checks; no data)
-- destructive: approved by CEO 2026-10-25 (also replaces the invitations role check; runs after the empty-table guard)
--
-- Identity reshape for Release 1 (LLD-1 §3.2-3.5, L1-1). One transaction, in this order:
--   1. refuse unless tenants and memberships are empty;
--   2. users, then tenants -> businesses;
--   3. memberships -> business_id and user_id, the four R1 roles;
--   4. sessions, pending_signups, verification_codes, support_grants;
--   5. helper functions, the legacy functions on the new columns, the owner-row trigger;
--   6. policies and grants for app_rw, app_ro and identity_auth.
-- support_read policies come with platform.support_grant_active (S0a c2), which must
-- sort after this file. The legacy audit copy (§3.6) waits for platform.audit_log.

-- 1. ------------------------------------------------------------------------------
do $$ begin
    if exists (select 1 from identity.memberships) or exists (select 1 from identity.tenants) then
        raise exception 'identity reshape needs empty tenants and memberships tables; see LLD-1 §3.3';
    end if;
end $$;

-- 2. ------------------------------------------------------------------------------
create table identity.users (
    id uuid primary key,
    cognito_sub text not null unique,
    email text not null,                       -- trimmed and lower-cased
    name text,
    is_support boolean not null default false, -- set only by a migration or ops script
    totp_enabled_at timestamptz,
    created_at timestamptz not null default now()
);
create unique index users_email_uq on identity.users (email);

alter table identity.tenants rename to businesses;
alter table identity.businesses
    add column status text not null default 'active' check (status in ('active', 'closing', 'closed')),
    add column created_by uuid not null references identity.users(id),
    add column closed_at timestamptz,
    alter column name drop not null;

-- 3. ------------------------------------------------------------------------------
alter table identity.memberships rename column tenant_id to business_id;
alter table identity.memberships
    add column user_id uuid not null references identity.users(id),
    add column deactivated_at timestamptz,
    add column deactivated_by uuid references identity.users(id),
    add column deactivation_reason text,
    add column updated_at timestamptz not null default now(),
    alter column user_sub drop not null,
    drop constraint memberships_role_check,
    drop constraint memberships_status_check,
    drop constraint memberships_tenant_id_user_sub_key,
    add constraint memberships_role_check check (role in ('owner', 'admin', 'billing', 'ca')),
    add constraint memberships_status_check check (status in ('active', 'deactivated')),
    add constraint memberships_business_id_user_id_key unique (business_id, user_id);
create index memberships_active_user on identity.memberships (user_id) where status = 'active';

alter table identity.invitations
    drop constraint invitations_role_check,
    add constraint invitations_role_check check (role in ('owner', 'admin', 'billing', 'ca'));

-- 4. ------------------------------------------------------------------------------
create table identity.sessions (
    id uuid primary key,
    user_id uuid not null references identity.users(id),
    key_kind text not null check (key_kind in ('origin_jti', 'event_id', 'sid')),
    key_value text not null,
    auth_time timestamptz not null,
    created_at timestamptz not null default now(),
    last_activity_at timestamptz not null default now(),
    absolute_expires_at timestamptz not null,
    revoked_at timestamptz,
    revoke_reason text check (revoke_reason in
        ('signout', 'password_change', 'password_reset', 'signout_all', 'closure', 'support')),
    unique (key_kind, key_value)
);
create index sessions_live_user on identity.sessions (user_id) where revoked_at is null;

create table identity.pending_signups (
    email text primary key,
    created_at timestamptz not null default now(),
    last_code_at timestamptz not null
);

create table identity.verification_codes (
    id uuid primary key,
    purpose text not null check (purpose in ('signup', 'reset')),
    email text not null,
    code_hmac bytea not null,
    tries smallint not null default 0,
    max_tries smallint not null,
    expires_at timestamptz not null,
    claimed_at timestamptz,
    consumed_at timestamptz,
    voided_at timestamptz,
    created_at timestamptz not null default now()
);
create unique index codes_one_live on identity.verification_codes (purpose, email)
    where consumed_at is null and voided_at is null;

create table identity.support_grants (
    id uuid primary key,
    business_id uuid not null references identity.businesses(id),
    granted_by uuid not null references identity.users(id),
    starts_at timestamptz not null default now(),
    expires_at timestamptz not null,
    revoked_at timestamptz,
    revoked_by uuid references identity.users(id),
    created_at timestamptz not null default now()
);

-- 5. ------------------------------------------------------------------------------
-- identity_auth owns the definer helpers and reads identity tables through its own
-- policies below (users_auth, biz_auth, m_auth, sg_auth), so helpers never recurse
-- into the policies that call them.
grant usage on schema identity to identity_auth;

create function identity.is_active_member(b uuid) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select exists (
        select 1 from identity.memberships m join identity.businesses x on x.id = m.business_id
        where m.business_id = b
          and m.user_id = nullif(current_setting('app.user_id', true), '')::uuid
          and m.status = 'active'
          and x.status <> 'closed'
    )
$$;

create function identity.caller_has_role(b uuid, roles text[]) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select exists (
        select 1 from identity.memberships
        where business_id = b
          and user_id = nullif(current_setting('app.user_id', true), '')::uuid
          and status = 'active'
          and role = any (roles)
    )
$$;

-- The creator's own first owner row of a business that has no member yet (§5.10).
create function identity.is_bootstrap_owner(b uuid, u uuid, r text) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select u = nullif(current_setting('app.user_id', true), '')::uuid
       and r = 'owner'
       and exists (select 1 from identity.businesses where id = b and created_by = u)
       and not exists (select 1 from identity.memberships where business_id = b)
$$;

alter function identity.is_active_member(uuid) owner to identity_auth;
alter function identity.caller_has_role(uuid, text[]) owner to identity_auth;
alter function identity.is_bootstrap_owner(uuid, uuid, text) owner to identity_auth;
revoke all on function identity.is_active_member(uuid), identity.caller_has_role(uuid, text[]),
    identity.is_bootstrap_owner(uuid, uuid, text) from public;
grant execute on function identity.is_active_member(uuid), identity.caller_has_role(uuid, text[]),
    identity.is_bootstrap_owner(uuid, uuid, text) to app_rw, app_ro;

-- Legacy functions (0002-0004). New code doesn't call them; other services' grants
-- (tenant_auth) still name is_member and caller_role. Their bodies name columns, so
-- they are rewritten on the new ones, with pg_temp last on the search path.
create or replace function identity.is_member(t uuid) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select exists (
        select 1 from identity.memberships
        where business_id = t
          and user_id = nullif(current_setting('app.user_id', true), '')::uuid
          and status = 'active'
    )
$$;

create or replace function identity.caller_role(t uuid) returns text
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select role from identity.memberships
    where business_id = t
      and user_id = nullif(current_setting('app.user_id', true), '')::uuid
      and status = 'active'
$$;

create or replace function identity.has_role(t uuid, roles text[]) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select exists (
        select 1 from identity.memberships
        where business_id = t
          and user_id = nullif(current_setting('app.user_id', true), '')::uuid
          and status = 'active'
          and role = any (roles)
    )
$$;

create or replace function identity.has_no_members(t uuid) returns boolean
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select not exists (select 1 from identity.memberships where business_id = t)
$$;

alter function identity.is_member(uuid) owner to identity_auth;
alter function identity.caller_role(uuid) owner to identity_auth;
alter function identity.has_role(uuid, text[]) owner to identity_auth;
alter function identity.has_no_members(uuid) owner to identity_auth;

-- T-013's owner-row rule on app.user_id: only an owner changes an owner row, and a
-- membership never moves to another business or user. Invoker rights: it only calls
-- caller_has_role, which the writer can execute.
create or replace function identity.guard_owner_rows() returns trigger
language plpgsql security invoker set search_path = pg_catalog, identity, pg_temp as $$
begin
    if (old.role = 'owner' or new.role = 'owner')
       and not identity.caller_has_role(old.business_id, array['owner']) then
        raise exception 'only an owner can change an owner membership'
            using errcode = 'insufficient_privilege';
    end if;
    if new.business_id <> old.business_id or new.user_id <> old.user_id then
        raise exception 'a membership cannot move to another business or user'
            using errcode = 'insufficient_privilege';
    end if;
    new.updated_at := now();
    return new;
end $$;

-- 6. ------------------------------------------------------------------------------
-- Every svc_identity policy goes; the API connects as app_rw (LLD-0 §4.1).
drop policy member_tenants on identity.businesses;
drop policy create_tenant on identity.businesses;
drop policy edit_tenant on identity.businesses;
drop policy invited_tenants on identity.businesses;
drop policy member_rows on identity.memberships;
drop policy add_member on identity.memberships;
drop policy manage_member on identity.memberships;
drop policy member_audit on identity.audit_events;
drop policy write_audit on identity.audit_events;
drop policy invitation_rows on identity.invitations;
drop policy invitation_insert on identity.invitations;
drop policy invitation_manage on identity.invitations;
drop policy invitation_accept on identity.invitations;

-- No UPDATE on businesses in S1 [RM41-3]; the svc_identity bridge would otherwise
-- lend it to app_rw.
revoke update on identity.businesses from svc_identity;

alter table identity.users enable row level security;
alter table identity.sessions enable row level security;
alter table identity.pending_signups enable row level security;
alter table identity.verification_codes enable row level security;
alter table identity.support_grants enable row level security;
alter table identity.businesses force row level security;
alter table identity.memberships force row level security;
alter table identity.audit_events force row level security;
alter table identity.invitations force row level security;
alter table identity.users force row level security;
alter table identity.sessions force row level security;
alter table identity.pending_signups force row level security;
alter table identity.verification_codes force row level security;
alter table identity.support_grants force row level security;

-- users
create policy users_self on identity.users for select to app_rw
    using (id = nullif(current_setting('app.user_id', true), '')::uuid);
create policy users_self_update on identity.users for update to app_rw
    using (id = nullif(current_setting('app.user_id', true), '')::uuid)
    with check (id = nullif(current_setting('app.user_id', true), '')::uuid);
create policy users_self_ro on identity.users for select to app_ro
    using (id = nullif(current_setting('app.user_id', true), '')::uuid);
create policy users_auth on identity.users to identity_auth using (true) with check (true);

-- businesses
create policy biz_tenant on identity.businesses for select to app_rw
    using (id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy biz_create on identity.businesses for insert to app_rw
    with check (id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and created_by = nullif(current_setting('app.user_id', true), '')::uuid);
create policy biz_member_ro on identity.businesses for select to app_ro
    using (id = nullif(current_setting('app.tenant_id', true), '')::uuid or identity.is_active_member(id));
create policy biz_auth on identity.businesses for select to identity_auth using (true);
-- Until LLD-2 reshapes invitations: an invitee may read the name of a business that
-- invited their verified email ("Join Vashi Essentials?").
create policy biz_invited on identity.businesses for select to app_rw
    using (exists (
        select 1 from identity.invitations i
        where i.tenant_id = businesses.id
          and i.status = 'pending'
          and i.email = nullif(current_setting('app.user_email', true), '')
    ));

-- memberships
create policy m_tenant on identity.memberships for select to app_rw, app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy m_self on identity.memberships for select to app_rw, app_ro
    using (user_id = nullif(current_setting('app.user_id', true), '')::uuid);
-- LLD-1 §3.4's rule, plus the existing T-013 rule that only an owner adds an owner.
create policy m_insert on identity.memberships for insert to app_rw
    with check (
        business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and ((identity.caller_has_role(business_id, array['owner', 'admin'])
              and (role <> 'owner' or identity.caller_has_role(business_id, array['owner'])))
             or identity.is_bootstrap_owner(business_id, user_id, role))
    );
-- Until LLD-2: the invitee's own row, with the role of an invitation to their verified
-- email ("accepted" by them too, since the accept may flush the invitation first).
create policy m_accept on identity.memberships for insert to app_rw
    with check (
        user_id = nullif(current_setting('app.user_id', true), '')::uuid
        and exists (
            select 1 from identity.invitations i
            where i.tenant_id = memberships.business_id
              and i.email = nullif(current_setting('app.user_email', true), '')
              and i.role = memberships.role
              and ((i.status = 'pending' and i.expires_at > now())
                   or (i.status = 'accepted' and i.accepted_by = current_setting('app.user_sub', true)))
        )
    );
create policy m_update on identity.memberships for update to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.caller_has_role(business_id, array['owner', 'admin']))
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and identity.caller_has_role(business_id, array['owner', 'admin']));
create policy m_auth on identity.memberships for select to identity_auth using (true);

-- sessions, pending sign-ups, codes: only identity_auth's functions (S1) touch them.
create policy sessions_auth on identity.sessions to identity_auth using (true) with check (true);
create policy pending_signups_auth on identity.pending_signups to identity_auth using (true) with check (true);
create policy codes_auth on identity.verification_codes to identity_auth using (true) with check (true);

-- support grants (LLD-2 adds the owner-only write rule)
create policy sg_tenant on identity.support_grants to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy sg_ro on identity.support_grants for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy sg_auth on identity.support_grants for select to identity_auth using (true);

-- legacy audit: read by tenant. The insert policy stays until the routes move to
-- platform's audit.record (S1-a2), then goes with the c3 copy (LLD-0 §3.6).
create policy ae_tenant on identity.audit_events for select to app_rw
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy ae_ro on identity.audit_events for select to app_ro
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy ae_insert on identity.audit_events for insert to app_rw
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and actor_sub = current_setting('app.user_sub', true));

-- invitations, until LLD-2 rewrites them: managed inside the business by an owner, or
-- an admin for any role but owner; read and accepted by the invitee's verified email.
create policy inv_tenant on identity.invitations for select to app_rw
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
create policy inv_invitee on identity.invitations for select to app_rw
    using (email = nullif(current_setting('app.user_email', true), ''));
create policy inv_insert on identity.invitations for insert to app_rw
    with check (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    );
create policy inv_manage on identity.invitations for update to app_rw
    using (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    )
    with check (
        tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
        and (identity.caller_has_role(tenant_id, array['owner'])
             or (identity.caller_has_role(tenant_id, array['admin']) and role <> 'owner'))
    );
create policy inv_accept on identity.invitations for update to app_rw
    using (status = 'pending' and expires_at > now()
           and email = nullif(current_setting('app.user_email', true), ''))
    with check (status = 'accepted'
                and accepted_by = current_setting('app.user_sub', true)
                and email = nullif(current_setting('app.user_email', true), ''));

-- Grants. No DELETE anywhere.
grant usage on schema identity to app_rw, app_ro;
grant select, insert on identity.businesses to app_rw;
grant select, insert, update on identity.memberships, identity.support_grants to app_rw;
grant select, update (name) on identity.users to app_rw;
grant select, insert on identity.audit_events to app_rw;
grant select, insert on identity.invitations to app_rw;
grant update (status, delivery, accepted_by, accepted_at, expires_at) on identity.invitations to app_rw;
grant select on identity.users, identity.businesses, identity.memberships, identity.support_grants,
    identity.audit_events to app_ro;
grant select, insert, update on identity.users, identity.sessions, identity.pending_signups,
    identity.verification_codes to identity_auth;
grant select on identity.businesses, identity.memberships, identity.support_grants to identity_auth;
