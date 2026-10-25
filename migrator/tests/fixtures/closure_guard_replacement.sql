-- Shape of LLD-6 §10 migration 2 (`…_identity_closure.sql`), for build-readiness 2.5.
-- Illustrative only: the real file is written with the closure build and uses
-- LLD-1's reshaped tables. What matters here is the statement kinds it uses.

-- T-013 guard exception: deactivating an owner is allowed once the business is
-- closed in the same transaction. Replaces the function body; the trigger stays.
create or replace function identity.guard_owner_rows() returns trigger
language plpgsql security definer set search_path = identity as $$
begin
    -- an admin cannot change an owner row; nothing here is dropped or deleted
    if (old.role = 'owner' or new.role = 'owner')
       and not identity.has_role(old.business_id, array['owner']) then
        raise exception 'only an owner can change an owner membership; drop table is not allowed'
            using errcode = 'insufficient_privilege';
    end if;
    if old.role = 'owner' and old.status = 'active' and new.status <> 'active'
       and (select status from identity.businesses where id = old.business_id) <> 'closed'
       and identity.active_owner_count(old.business_id) = 1 then
        raise exception 'the last active owner cannot be deactivated'
            using errcode = 'insufficient_privilege';
    end if;
    return new;
end $$;
revoke all on function identity.guard_owner_rows() from public;

create or replace function identity.close_business(business_id uuid, actor uuid, reason text)
returns jsonb language plpgsql security definer set search_path = identity as $$
begin
    update identity.businesses set status = 'closed', closed_at = now() where id = business_id;
    update identity.memberships set status = 'deactivated' where memberships.business_id = close_business.business_id;
    delete from identity.pending_rows;  -- inside a body: runs only when called, not scanned
    return jsonb_build_object('closed', true);
end $$;
revoke all on function identity.close_business(uuid, uuid, text) from public;
grant update (status, closed_at) on identity.businesses to identity_auth;
