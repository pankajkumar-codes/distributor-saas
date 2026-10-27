-- LLD-2 part A follow-up (EM after #39 and #41):
-- 1. invitations.business_name, the business's display name when the invite was sent
--    (business.interface.display_name), refreshed on resend and shown by the preview.
-- 2. An insert guard beside the update guard (Staff 2 on #39): an invitation starts pending,
--    with nothing accepted or cancelled.
-- 3. T-013's owner-row trigger raises its own SQLSTATE, IDO01, instead of 42501, which RLS
--    raises too, so the API maps only the trigger's refusal to owner_rule (Staff on #39).

-- 1. ------------------------------------------------------------------------------
alter table identity.invitations add column business_name varchar(200);
grant update (business_name) on identity.invitations to app_rw;

-- The preview prefers the snapshot; invites sent before this file fall back to the
-- business row. Same signature, so a replace; identity_auth owns it and needs CREATE on
-- the schema to replace it, lent here and taken back.
grant create on schema identity to identity_auth;
set role identity_auth;
create or replace function identity.auth_invitation_preview(p_token_hash text)
returns table (business_name text, role text, inviter_name text, expires_at timestamptz)
language sql stable security definer set search_path = pg_catalog, identity, pg_temp as $$
    select coalesce(i.business_name, b.name)::text, i.role::text, inviter.name, i.expires_at
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
reset role;
revoke create on schema identity from identity_auth;

-- 2. ------------------------------------------------------------------------------
-- The update rules of 202610261500, with business_name joining the link and expiry as
-- things that change only while pending.
create or replace function identity.guard_invitation_update() returns trigger
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
    if (new.token_hash, new.expires_at, new.last_sent_at, new.business_name)
           is distinct from (old.token_hash, old.expires_at, old.last_sent_at, old.business_name)
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

create function identity.guard_invitation_insert() returns trigger
    language plpgsql set search_path = pg_catalog, identity, pg_temp as $$
begin
    if new.status <> 'pending'
       or (new.accepted_by_user, new.accepted_at, new.cancelled_at, new.cancelled_by)
          is distinct from (null::uuid, null::timestamptz, null::timestamptz, null::uuid) then
        raise exception 'an invitation starts pending' using errcode = 'check_violation';
    end if;
    return new;
end $$;
revoke all on function identity.guard_invitation_insert() from public;
create trigger invitations_guard_insert before insert on identity.invitations
    for each row execute function identity.guard_invitation_insert();

-- 3. ------------------------------------------------------------------------------
-- 202610251700's guard, unchanged but for the SQLSTATE.
create or replace function identity.guard_owner_rows() returns trigger
language plpgsql security invoker set search_path = pg_catalog, identity, pg_temp as $$
begin
    if (old.role = 'owner' or new.role = 'owner')
       and not identity.caller_has_role(old.business_id, array['owner']) then
        raise exception 'only an owner can change an owner membership' using errcode = 'IDO01';
    end if;
    if new.business_id <> old.business_id or new.user_id <> old.user_id then
        raise exception 'a membership cannot move to another business or user' using errcode = 'IDO01';
    end if;
    new.updated_at := now();
    return new;
end $$;
