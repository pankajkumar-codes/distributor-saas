-- Demo only, and only when you start it with `./demo.sh --finalize` (or `.\demo.ps1 -Finalize`): turn on the finalize switch
-- in the demo's own throwaway database so an invoice can be finalized and shown a number. Those numbers are PRACTICE only:
-- invoice numbering stays off for real until the CA confirms the scope (D-010, D-044, CA-1). Never run this against any other
-- database, and never copy it into staging or production config. A new refdata.loads row makes the running API reload.
update refdata.values set value = 'true' where key = 'sales.finalize.enabled';
insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)
values (gen_random_uuid(), 'demo-finalize', '{}', 0, 0, 1);
