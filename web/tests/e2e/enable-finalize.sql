-- Test setup only (the web-e2e job and a local run): turn the finalize switch on, and lift the per-address code caps, as the backend tests do, so the R2
-- happy path can issue a practice invoice. A new refdata.loads row makes the running API rebuild its refdata snapshot.
-- Production changes this only by a dated refdata row after the CEO and CA decide (D-010, D-044).
update refdata.values set value = 'true' where key = 'sales.finalize.enabled';
-- Every spec signs up a fresh account from one address, so the per-address hourly caps on codes (20) would be spent
-- by the suite itself as specs are added. Raised here only; the product values are unchanged.
update refdata.values set value = '1000' where key in ('auth.code_requests_per_ip_per_hour', 'auth.code_checks_per_ip_per_hour');
insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)
values (gen_random_uuid(), 'e2e', '{}', 0, 0, 1);
