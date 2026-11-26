-- Demo only, and only when you start it with `./demo.sh --finalize` (or `.\demo.ps1 -Finalize`): turn on finalize and live
-- numbering in the demo's own throwaway database, so an invoice can be issued and a business owner can turn on live
-- numbers (INV/YY-MM/NNNNNN) in Settings > Invoice numbering (#477; Pankaj approved live numbering in the demo only,
-- 2026-11-26, D-119). Never run this against any other database, and never copy it into staging or production config:
-- there both switches stay off until Pankaj approves them. A new refdata.loads row makes the running API reload.
update refdata.values set value = 'true' where key in ('sales.finalize.enabled', 'sales.finalize.live');
insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)
values (gen_random_uuid(), 'demo-finalize', '{}', 0, 0, 2);
