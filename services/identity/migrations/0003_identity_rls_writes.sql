-- Close the identity write gaps QA logged (team/qa.md QA-DEF-001, 002, 003, 005, 006).
-- 0002 let svc_identity insert any membership or audit row (WITH CHECK (true)), let a
-- user update their own membership row, and its FOR-ALL read policies also let any
-- member insert audit rows and update the tenant. The API blocks all of these today; after this
-- migration the database does too, so a missed API check cannot grant access.
-- Forward-only: drops and recreates policies, no data change.

-- Caller (app.user_sub) is an active member of tenant t with one of the given roles.
create function identity.has_role(t uuid, roles text[]) returns boolean
language sql stable security definer set search_path = identity, pg_temp as $$
    select exists (
        select 1 from identity.memberships
        where tenant_id = t
          and user_sub = current_setting('app.user_sub', true)
          and status = 'active'
          and role = any (roles)
    )
$$;

-- Tenant t has no membership rows yet (a tenant being created in this transaction).
create function identity.has_no_members(t uuid) returns boolean
language sql stable security definer set search_path = identity, pg_temp as $$
    select not exists (select 1 from identity.memberships where tenant_id = t)
$$;

revoke all on function identity.has_role(uuid, text[]) from public;
revoke all on function identity.has_no_members(uuid) from public;
grant execute on function identity.has_role(uuid, text[]) to svc_identity;
grant execute on function identity.has_no_members(uuid) to svc_identity;

-- Memberships. Reading is unchanged: members see their tenant, and a user always sees
-- their own row. Writing follows the PO roles matrix: owner manages everyone, admin
-- manages everyone except owners and cannot make anyone an owner.
drop policy member_rows on identity.memberships;
drop policy add_member on identity.memberships;

create policy member_rows on identity.memberships for select to svc_identity
    using (identity.is_member(tenant_id) or user_sub = current_setting('app.user_sub', true));

create policy add_member on identity.memberships for insert to svc_identity
    with check (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
        -- First owner of a brand-new tenant: only themselves, only as owner.
        or (identity.has_no_members(tenant_id)
            and user_sub = current_setting('app.user_sub', true)
            and role = 'owner')
    );

-- USING admits every row of the tenant for owner/admin, so SELECT ... FOR UPDATE (which
-- RLS filters through the UPDATE policy) still sees owners and the API can answer 403
-- rather than 404. The "admin cannot touch an owner" rule needs the old row, which a
-- policy cannot see, so the trigger below enforces it.
create policy manage_member on identity.memberships for update to svc_identity
    using (identity.has_role(tenant_id, array['owner', 'admin']))
    with check (
        identity.has_role(tenant_id, array['owner'])
        or (identity.has_role(tenant_id, array['admin']) and role <> 'owner')
    );

create function identity.guard_owner_rows() returns trigger
language plpgsql security definer set search_path = identity, pg_temp as $$
begin
    if (old.role = 'owner' or new.role = 'owner')
       and not identity.has_role(old.tenant_id, array['owner']) then
        raise exception 'only an owner can change an owner membership'
            using errcode = 'insufficient_privilege';
    end if;
    if new.tenant_id <> old.tenant_id or new.user_sub <> old.user_sub then
        raise exception 'a membership cannot move to another tenant or user'
            using errcode = 'insufficient_privilege';
    end if;
    return new;
end $$;
revoke all on function identity.guard_owner_rows() from public;
create trigger guard_owner_rows before update on identity.memberships
    for each row execute function identity.guard_owner_rows();

-- Audit: only into a tenant the caller belongs to (or is creating), and only as themselves.
-- member_audit had no FOR clause, so it applied to INSERT too (its USING doubled as the
-- check) and let any member write any actor's events; it becomes read-only.
drop policy member_audit on identity.audit_events;
create policy member_audit on identity.audit_events for select to svc_identity
    using (identity.is_member(tenant_id));
drop policy write_audit on identity.audit_events;
create policy write_audit on identity.audit_events for insert to svc_identity
    with check (
        actor_sub = current_setting('app.user_sub', true)
        and (identity.is_member(tenant_id) or identity.has_no_members(tenant_id))
    );

-- Tenants: member_tenants also had no FOR clause, so any member (even a viewer) could
-- rename the tenant. Reading stays member-wide; updating needs owner or admin
-- (profile.edit in docs/PERMISSIONS.md). Creating a tenant stays open (create_tenant).
drop policy member_tenants on identity.tenants;
create policy member_tenants on identity.tenants for select to svc_identity
    using (identity.is_member(id));
create policy edit_tenant on identity.tenants for update to svc_identity
    using (identity.has_role(id, array['owner', 'admin']))
    with check (identity.has_role(id, array['owner', 'admin']));
