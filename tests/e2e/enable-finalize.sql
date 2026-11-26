-- Test setup only (CI's e2e job and a local run against a throwaway database): turn on finalize and live numbering
-- so tests/e2e/test_notes_security_e2e.py can issue invoices, credit and debit notes and turn a test business live.
-- Never run this against any other database: there both switches stay off until Pankaj approves them (D-121).
-- A new refdata.loads row makes the running API rebuild its refdata snapshot.
update refdata.values set value = 'true' where key in ('sales.finalize.enabled', 'sales.finalize.live');
insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)
values (gen_random_uuid(), 'e2e', '{}', 0, 0, 2);
