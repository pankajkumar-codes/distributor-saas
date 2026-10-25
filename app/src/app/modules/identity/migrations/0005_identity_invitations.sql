-- Invite a teammate by email (backlog E0-1, plan T-004). Additive only.

-- Members get a readable email and name; existing rows keep NULL.
alter table identity.memberships add column email varchar(254);
alter table identity.memberships add column display_name varchar(200);

create table identity.invitations (
    id uuid primary key,
    tenant_id uuid not null references identity.tenants(id),
    -- Stored lower-cased; matched against the invitee's verified Cognito email.
    email varchar(254) not null check (email = lower(email)),
    display_name varchar(200),
    role varchar(20) not null check (role in ('owner','admin','sales','inventory','finance','viewer')),
    status varchar(20) not null default 'pending' check (status in ('pending','accepted','revoked')),
    invited_by varchar(128) not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    -- 'pending', 'sent' or 'failed': whether the Cognito invite email went out.
    delivery varchar(20) not null default 'pending' check (delivery in ('pending','sent','failed')),
    accepted_by varchar(128),
    accepted_at timestamptz
);
-- At most one open invitation per person per tenant; expired ones are renewed by resend.
create unique index invitations_one_open on identity.invitations (tenant_id, email) where status = 'pending';
create index on identity.invitations (email) where status = 'pending';

grant select, insert on identity.invitations to svc_identity;
-- Who an invitation is for, where and as what never changes once written.
grant update (status, delivery, accepted_by, accepted_at, expires_at) on identity.invitations to svc_identity;
alter table identity.invitations enable row level security;

-- Members see their tenant's invitations; an invitee sees invitations sent to the
-- verified email the service put in app.user_email for this transaction.
create policy invitation_rows on identity.invitations for select to svc_identity
    using (
        identity.is_member(tenant_id)
        or email = nullif(current_setting('app.user_email', true), '')
    );
-- Same rule as adding a member: an owner invites anyone, an admin anyone but an owner.
create policy invitation_insert on identity.invitations for insert to svc_identity
    with check (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
    );
-- Revoke, resend and recording delivery.
create policy invitation_manage on identity.invitations for update to svc_identity
    using (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
    )
    with check (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
    );
-- The invitee may only accept a pending invitation to their own email, as themselves.
create policy invitation_accept on identity.invitations for update to svc_identity
    using (
        status = 'pending'
        and expires_at > now()
        and email = nullif(current_setting('app.user_email', true), '')
    )
    with check (
        status = 'accepted'
        and accepted_by = current_setting('app.user_sub', true)
        and email = nullif(current_setting('app.user_email', true), '')
    );

-- An invitee who is not a member yet may read the name of a tenant that invited them,
-- so "Join Vashi Essentials?" can be shown before accepting.
create policy invited_tenants on identity.tenants for select to svc_identity
    using (
        exists (
            select 1 from identity.invitations i
            where i.tenant_id = tenants.id
              and i.status = 'pending'
              and i.email = nullif(current_setting('app.user_email', true), '')
        )
    );

-- Accepting an invitation inserts the invitee's own membership. Migration 0003 lets
-- only owners/admins (or a new tenant's first owner) insert memberships, so add a
-- third case: the caller themselves, with exactly the role of an invitation addressed
-- to their verified email. 'accepted' by the same caller is allowed too, because the
-- accept flush may write the invitation's new status before the membership row.
drop policy add_member on identity.memberships;
create policy add_member on identity.memberships for insert to svc_identity
    with check (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
        or (identity.has_no_members(tenant_id)
            and user_sub = current_setting('app.user_sub', true)
            and role = 'owner')
        or (user_sub = current_setting('app.user_sub', true)
            and exists (
                select 1 from identity.invitations i
                where i.tenant_id = memberships.tenant_id
                  and i.email = nullif(current_setting('app.user_email', true), '')
                  and i.role = memberships.role
                  and ((i.status = 'pending' and i.expires_at > now())
                       or (i.status = 'accepted' and i.accepted_by = current_setting('app.user_sub', true)))
            ))
    );
