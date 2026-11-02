-- retention.purge_operational() reads its periods and its on/off switch from refdata
-- (D-041). Its owner, retention_owner, reads refdata.values and nothing else here.
grant usage on schema refdata to retention_owner;
grant select on refdata.values to retention_owner;
