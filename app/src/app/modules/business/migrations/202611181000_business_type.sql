-- R2-M1 (BRD v1.4, ON-7 switched on): the business says what kind of business it is.
-- Distributor or retail; null means not chosen, which is every business created in R1
-- (a filing-only seller has no value to give). Additive and nullable: no row is touched,
-- RLS and grants on business.profiles stay as they are. A change goes through PATCH /profile,
-- which bumps the version and writes the audit row like any other profile field.
alter table business.profiles
    add column business_type text check (business_type in ('distributor', 'retail'));
