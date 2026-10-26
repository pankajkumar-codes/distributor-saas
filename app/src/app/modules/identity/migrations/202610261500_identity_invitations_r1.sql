-- Invitations for Release 1 (LLD-2 §2.1, §2.2, §2.4, §4.4; L2-1, L2-2, L2-3).
--
-- LLD-2 §13 approved a destructive header for this file; it turned out not to need one.
-- #12's policies are rewritten in place with ALTER POLICY rather than dropped, and the
-- two invitee policies outside invitations (biz_invited, m_accept) are closed to
-- false, so nothing here drops a policy, a column or data.
--   1. refuse unless invitations is empty (token_hash is not null, as in LLD-1 §3.3);
--   2. tenant_id -> business_id, the R1 invite roles and statuses, the new columns;
--   3. memberships.role_changed_at / role_changed_by;
--   4. policies: managed by an owner or admin inside the business; read and accepted by
--      the invitee only through identity_auth's functions below;
--   5. identity.member_profiles, auth_invitation_preview, auth_accept_invitation.

-- 1. ------------------------------------------------------------------------------
do $$ begin
    if exists (select 1 from identity.invitations) then
        raise exception 'invitations reshape needs an empty invitations table; see LLD-2 §2.1';
    end if;
end $$;

-- 2. ------------------------------------------------------------------------------
alter table identity.invitations rename column tenant_id to business_id;
alter table identity.invitations
    drop constraint invitations_role_check,
    add constraint invitations_role_check check (role in ('admin', 'billing', 'ca')),
    drop constraint invitations_status_check,
    add constraint invitations_status_check check (status in ('pending', 'accepted', 'cancelled', 'expired')),
    -- #12's Cognito subs: no longer written, dropped with a later CEO-approved change.
    alter column invited_by drop not null,
    add column token_hash char(64) not null,          -- sha256 hex of the link's 32 random bytes
    add column invited_by_user uuid not null references identity.users(id),
    add column accepted_by_user uuid references identity.users(id),
    add column cancelled_at timestamptz,
    add column cancelled_by uuid references identity.users(id),
    add column last_sent_at timestamptz;
create unique index invitations_token on identity.invitations (token_hash);

-- 3. ------------------------------------------------------------------------------
alter table identity.memberships
    add column role_changed_at timestamptz,
    add column role_changed_by uuid references identity.users(id);

-- 4. ------------------------------------------------------------------------------
-- `tenant` and `me` as in LLD-1 §3.4. app_rw: one rule for read, insert and update, and
-- none of it under a support grant (c3's exclusion, kept).
alter policy inv_tenant on identity.invitations
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));
alter policy inv_insert on identity.invitations
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));
alter policy inv_manage on identity.invitations
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']))
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
                and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));
create policy inv_ro on identity.invitations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and coalesce(current_setting('app.support_grant_id', true), '') = ''
           and identity.caller_has_role(business_id, array['owner', 'admin']));
-- The invitee's two policies become identity_auth's (accept by token, §4.4).
alter policy inv_invitee on identity.invitations rename to inv_auth_select;
alter policy inv_auth_select on identity.invitations to identity_auth using (true);
alter policy inv_accept on identity.invitations rename to inv_auth_update;
alter policy inv_auth_update on identity.invitations to identity_auth using (true) with check (true);

-- The stock-era invitee paths read app.user_email, which the client could supply. The
-- definer functions below replace them.
alter policy biz_invited on identity.businesses using (false);
alter policy m_accept on identity.memberships with check (false);

-- identity_auth writes a membership only through auth_accept_invitation [RM42-2].
create policy m_auth_insert on identity.memberships for insert to identity_auth with check (true);
create policy m_auth_update on identity.memberships for update to identity_auth using (true) with check (true);
-- ... and its one audit row.
create policy audit_auth_insert on platform.audit_log for insert to identity_auth
    with check (action = 'member.accept' and business_id is not null and support_grant_id is null);

-- 0005 and 202610251700 granted UPDATE on the legacy columns (delivery, accepted_by, ...)
-- to svc_identity and app_rw; they go, and app_rw gets back only what resend, cancel and
-- the lapse write use. Which status moves are allowed is the trigger's job (section 6).
revoke update on identity.invitations from svc_identity, app_rw;
grant update (status, expires_at, token_hash, last_sent_at, cancelled_at, cancelled_by)
    on identity.invitations to app_rw;
grant select on identity.invitations to app_ro;
grant select, update (status, accepted_by_user, accepted_at) on identity.invitations to identity_auth;
grant insert, update on identity.memberships to identity_auth;
grant usage on schema platform to identity_auth;
grant insert on platform.audit_log to identity_auth;

-- 5. ------------------------------------------------------------------------------
-- Names and emails of the current business's members, for an active member of it
-- (L2-3). Any membership status, so a deactivated member still shows a name; nothing
-- for users who share another business with the caller.
create function identity.member_profiles(p_user_ids uuid[])
returns table (user_id uuid, email text, name text)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select u.id, u.email, u.name
    from identity.users u
    where u.id = any (p_user_ids)
      and identity.is_active_member(nullif(current_setting('app.tenant_id', true), '')::uuid)
      and exists (
          select 1 from identity.memberships m
          where m.user_id = u.id
            and m.business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
      )
$$;

-- What the invite page shows (§4.4): only for a pending, unexpired invite whose email is
-- the signed-in user's. Every other case is no row, so a token can't be probed.
create function identity.auth_invitation_preview(p_token_hash text)
returns table (business_name text, role text, inviter_name text, expires_at timestamptz)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select b.name::text, i.role::text, inviter.name, i.expires_at
    from identity.invitations i
    join identity.businesses b on b.id = i.business_id
    join identity.users me on me.id = nullif(current_setting('app.user_id', true), '')::uuid
    join identity.users inviter on inviter.id = i.invited_by_user
    where i.token_hash = p_token_hash
      and i.status = 'pending'
      and i.expires_at > now()
      and i.email = me.email
      and not me.is_support
      and b.status = 'active'
$$;

-- Accept (§4.4, L2-2): the token and the signed-in user's own email. Locks the invite,
-- re-checks it, then inserts the membership or reactivates a deactivated one with the
-- invited role, marks the invite accepted and writes member.accept. Returns the business
-- id, or null for every refusal alike. A retry by the user who accepted returns the same
-- business id and writes nothing (AC2-8). IDs come from Python (uuid7).
create function identity.auth_accept_invitation(p_token_hash text, p_membership_id uuid, p_audit_id uuid)
returns uuid
language plpgsql volatile security definer set search_path = pg_catalog, identity, pg_temp as $$
declare
    me uuid := nullif(current_setting('app.user_id', true), '')::uuid;
    me_email text;
    me_support boolean;
    inv identity.invitations%rowtype;
    existing identity.memberships%rowtype;
begin
    select email, is_support into me_email, me_support from identity.users where id = me;
    if not found or me_support then
        return null;
    end if;
    select * into inv from identity.invitations where token_hash = p_token_hash for update;
    if not found or inv.email <> me_email then
        return null;
    end if;
    if inv.status = 'accepted' and inv.accepted_by_user = me then
        return inv.business_id;
    end if;
    if inv.status <> 'pending' or inv.expires_at <= now()
       or not exists (select 1 from identity.businesses where id = inv.business_id and status = 'active') then
        return null;
    end if;

    select * into existing from identity.memberships
    where business_id = inv.business_id and user_id = me for update;
    if not found then
        insert into identity.memberships (id, business_id, user_id, role)
        values (p_membership_id, inv.business_id, me, inv.role);
    elsif existing.status = 'deactivated' then
        update identity.memberships
        set status = 'active', role = inv.role,
            deactivated_at = null, deactivated_by = null, deactivation_reason = null
        where id = existing.id;
    end if;
    -- An already active member (invited before they joined some other way) keeps their row.

    update identity.invitations
    set status = 'accepted', accepted_by_user = me, accepted_at = now()
    where id = inv.id;
    insert into platform.audit_log (id, business_id, user_id, action, target_kind, target_id, data, request_id)
    values (p_audit_id, inv.business_id, me, 'member.accept', 'invitation', inv.id,
            jsonb_build_object('role', inv.role),
            coalesce(nullif(current_setting('app.request_id', true), ''), 'unknown'));
    return inv.business_id;
end $$;

-- The RDS master hands a function to a role only with CREATE on its schema; lent here
-- and taken back, as 202610251659 and 202610261000 do.
grant create on schema identity to identity_auth;
alter function identity.member_profiles(uuid[]) owner to identity_auth;
alter function identity.auth_invitation_preview(text) owner to identity_auth;
alter function identity.auth_accept_invitation(text, uuid, uuid) owner to identity_auth;
revoke create on schema identity from identity_auth;
revoke all on function identity.member_profiles(uuid[]), identity.auth_invitation_preview(text),
    identity.auth_accept_invitation(text, uuid, uuid) from public;
grant execute on function identity.member_profiles(uuid[]) to app_rw, app_ro;
grant execute on function identity.auth_invitation_preview(text),
    identity.auth_accept_invitation(text, uuid, uuid) to app_rw;

-- 6. ------------------------------------------------------------------------------
-- Status moves, whoever writes (Staff 2 on #39). Only identity_auth, inside
-- auth_accept_invitation, can accept; nothing leaves accepted, cancelled or expired;
-- a lapse needs a past expires_at; the link and expiry change only while pending.
create function identity.guard_invitation_update() returns trigger
    language plpgsql set search_path = pg_catalog, identity, pg_temp as $$
begin
    if (new.business_id, new.email, new.role) is distinct from (old.business_id, old.email, old.role) then
        raise exception 'invitation business, email and role are fixed' using errcode = 'check_violation';
    end if;
    if new.status is distinct from old.status then
        if old.status <> 'pending'
           or (new.status = 'accepted' and (current_user <> 'identity_auth' or new.accepted_by_user is null))
           or (new.status = 'cancelled' and (new.cancelled_at is null or new.cancelled_by is null))
           or (new.status = 'expired' and old.expires_at > now())
           or new.status not in ('accepted', 'cancelled', 'expired') then
            raise exception 'invitation cannot move from % to %', old.status, new.status
                using errcode = 'check_violation';
        end if;
    end if;
    if (new.token_hash, new.expires_at, new.last_sent_at)
           is distinct from (old.token_hash, old.expires_at, old.last_sent_at)
       and (old.status <> 'pending' or new.status <> 'pending') then
        raise exception 'only a pending invitation can be resent' using errcode = 'check_violation';
    end if;
    if (new.accepted_by_user, new.accepted_at) is distinct from (old.accepted_by_user, old.accepted_at)
       and not (old.status = 'pending' and new.status = 'accepted') then
        raise exception 'acceptance is set only by accepting' using errcode = 'check_violation';
    end if;
    if (new.cancelled_at, new.cancelled_by) is distinct from (old.cancelled_at, old.cancelled_by)
       and not (old.status = 'pending' and new.status = 'cancelled') then
        raise exception 'cancellation is set only by cancelling' using errcode = 'check_violation';
    end if;
    return new;
end $$;
revoke all on function identity.guard_invitation_update() from public;
create trigger invitations_guard before update on identity.invitations
    for each row execute function identity.guard_invitation_update();
