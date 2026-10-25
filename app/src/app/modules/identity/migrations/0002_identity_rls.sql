-- Defense in depth: even if a query forgets its tenant filter, the database only
-- returns rows for tenants where the calling user (app.user_sub) is an active member.
alter table identity.memberships enable row level security;
alter table identity.audit_events enable row level security;
alter table identity.tenants enable row level security;

create function identity.is_member(t uuid) returns boolean
language sql stable security definer set search_path = identity as $$
    select exists (
        select 1 from identity.memberships
        where tenant_id = t
          and user_sub = current_setting('app.user_sub', true)
          and status = 'active'
    )
$$;
revoke all on function identity.is_member(uuid) from public;
grant execute on function identity.is_member(uuid) to svc_identity;

create policy member_rows on identity.memberships to svc_identity
    using (identity.is_member(tenant_id) or user_sub = current_setting('app.user_sub', true));

-- A brand-new tenant has no members yet; its creator inserts the first (owner) row.
create policy add_member on identity.memberships for insert to svc_identity
    with check (true);

create policy member_audit on identity.audit_events to svc_identity
    using (identity.is_member(tenant_id));
create policy write_audit on identity.audit_events for insert to svc_identity
    with check (true);

create policy member_tenants on identity.tenants to svc_identity
    using (identity.is_member(id));
create policy create_tenant on identity.tenants for insert to svc_identity
    with check (true);
