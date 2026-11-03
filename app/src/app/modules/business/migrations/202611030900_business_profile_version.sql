-- PATCH /profile takes If-Match (LLD-3 L3-9's rule, applied to the business details):
-- without a version, two people editing the company form at once silently overwrite
-- each other. Additive: every existing row starts at version 1.
alter table business.profiles add column version int not null default 1 check (version > 0);
