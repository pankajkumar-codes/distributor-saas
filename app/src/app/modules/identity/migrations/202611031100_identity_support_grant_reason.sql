-- S2-c: the owner's support-grant routes (LLD-2 §6.1).
--
-- The grant's optional reason, shown in the owner's grant list and the audit row. Only a
-- new nullable column with a length check: no row changes. app_rw already has select,
-- insert and update on the table, and sg_tenant keeps writes to the owner.
alter table identity.support_grants
    add column reason text check (reason is null or char_length(reason) between 1 and 500);

-- The grant list and "one active grant at a time" both read a business's grants newest first.
create index support_grants_business_starts on identity.support_grants (business_id, starts_at desc);
