-- Search index fixes from the S3-a review (#52 should-fix 1, Staff 2 (4)).
--
-- Customer GSTIN prefix search (`c.gstin like 'ABC%'`): a plain btree serves LIKE only
-- under the C collation, so the prefix needs a pattern opclass (gstin is char(15), hence
-- bpchar_pattern_ops), as products_code_prefix does for codes [RM43-9].
create index customers_gstin_prefix on catalog.customers (business_id, gstin bpchar_pattern_ops)
    where gstin is not null and status <> 'deleted';

-- Product barcode search (`lower(p.barcode) = :exact`) runs over active and archived
-- products, but products_barcode_uq covers active ones only, so archived barcodes were
-- a scan of the business's rows.
create index products_barcode_lookup on catalog.products (business_id, lower(barcode))
    where barcode is not null and status <> 'deleted';

-- Product name search (`p.name ilike '%q%'`) is served by products_name_trgm
-- (202610271020_catalog_trgm.sql; Staff 2's S0a proof 2.3 b). Its fallback, if RDS ever
-- refuses pg_trgm, is the business-scoped scan L3-10 accepts at R1 volumes.
