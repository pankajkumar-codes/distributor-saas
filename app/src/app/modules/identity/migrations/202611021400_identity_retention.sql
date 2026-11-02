-- What retention.purge_operational() may delete from identity (LLD-1 §12, LLD-2 §11,
-- LLD-6 §6.2; D-041): sessions after revocation or absolute expiry, verification codes
-- after use or expiry, pending sign-ups, and invitations after they close. The function's
-- conditions refuse anything still usable; these policies match only while a retention
-- function has set retention.active. Nothing here reaches users, memberships, businesses,
-- support grants or the audit tables.

grant usage on schema identity to retention_owner;
grant select, delete on identity.sessions, identity.verification_codes,
    identity.pending_signups, identity.invitations to retention_owner;

create policy retention_purge_select on identity.sessions for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on identity.sessions for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_select on identity.verification_codes for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on identity.verification_codes for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_select on identity.pending_signups for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on identity.pending_signups for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_select on identity.invitations for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on identity.invitations for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
