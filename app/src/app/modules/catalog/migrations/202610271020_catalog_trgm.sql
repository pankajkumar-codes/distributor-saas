-- Trigram search on product names (LLD-3 L3-10, §14 step 2). Its own file, so that if
-- RDS PostgreSQL 16 refuses pg_trgm the L3-10 fallback (ILIKE on the business's rows)
-- drops only this file. pg_trgm is a trusted extension, so the database owner can
-- create it; whether the RDS migrator may is Staff 2's open item in LLD-3 §15.

create extension if not exists pg_trgm;
create index products_name_trgm on catalog.products using gin (name gin_trgm_ops);
