-- support_read on the imports tables (LLD-0 §4.2, L0v3-3): a support user reads, never
-- writes, a business's runs and rows under a named, active grant. Follows #14, which
-- shipped before platform.support_grant_active existed (identity's 202610261000 file).
-- The tenant policies already exclude a support session, and no write policy names one,
-- so an update by a support session matches no rows and an insert is refused.

create policy support_read on imports.import_runs for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
create policy support_read on imports.import_rows for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
