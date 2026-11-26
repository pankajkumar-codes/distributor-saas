-- #457 (Pankaj, 2026-11-26): live invoice numbers are INV/YY-MM/NNNNNN, a series per month of the invoice date that
-- restarts at 1 each month (CGST Rule 46(b): "in one or multiple series ... unique for a financial year"). The series
-- key gains the month; '' is the FY-wide series (practice numbers, and the earlier gstin_kind_fy scope), so every
-- existing row keeps its meaning. Additive: a new column with a default, and the unique key widened by one column.
alter table sales.number_series
    add column month text not null default '' check (month = '' or month ~ '^[0-9]{4}-[0-9]{2}$');

alter table sales.number_series drop constraint number_series_business_id_gstin_kind_fy_key;
alter table sales.number_series
    add constraint number_series_scope_uq unique (business_id, gstin, kind, fy, month);  -- THE numbering scope (D-010)
