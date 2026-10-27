-- refdata: who confirmed a row and when (D-038). A status other than provisional
-- (expert_confirmed, ca_confirmed, po_confirmed) must name the person or role who
-- confirmed it and the date, so the step that lets require_confirmed pass is
-- auditable from the row itself, not only from git history. A provisional row names
-- nobody. The loader checks the same rule with a readable message; these constraints
-- hold it for anything else that writes.
--
-- Additive: two nullable columns per table. Every loaded row is provisional today, so
-- the constraints hold on existing data.

alter table refdata.values add column confirmed_by text, add column confirmed_on date;
alter table refdata.values add constraint values_confirmation check (
    (status = 'provisional' and confirmed_by is null and confirmed_on is null)
    or (status <> 'provisional' and length(btrim(confirmed_by)) > 0 and confirmed_on is not null)
);

alter table refdata.state_codes add column confirmed_by text, add column confirmed_on date;
alter table refdata.state_codes add constraint state_codes_confirmation check (
    (status = 'provisional' and confirmed_by is null and confirmed_on is null)
    or (status <> 'provisional' and length(btrim(confirmed_by)) > 0 and confirmed_on is not null)
);

alter table refdata.templates add column confirmed_by text, add column confirmed_on date;
alter table refdata.templates add constraint templates_confirmation check (
    (status = 'provisional' and confirmed_by is null and confirmed_on is null)
    or (status <> 'provisional' and length(btrim(confirmed_by)) > 0 and confirmed_on is not null)
);
