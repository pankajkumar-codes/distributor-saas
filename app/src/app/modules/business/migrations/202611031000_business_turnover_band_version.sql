-- Turnover bands get a version for If-Match (Settings shows this year's and last year's
-- band, each editable; team/design/mock-note-last-fy-band.md, CEO 2026-11-03). Additive:
-- existing rows start at 1. app_rw already has UPDATE on the table.
alter table business.turnover_bands add column version int not null default 1;
