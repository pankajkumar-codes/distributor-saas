-- R1-M7 slice 3: filing.v_supply_lines, LLD-5 §3 view contract v1 (a change is v_supply_lines_v2).
-- Additive: one view. It unions what sales publishes for a finalized document and what imports publishes
-- for a confirmed uploaded one; the builder routes by supply_class and never reads either module's tables.
-- security_invoker, so the caller's RLS applies to both sources. A practice document never appears
-- (sales.v_filing_lines excludes it). Credit notes carry positive amounts with doc_kind 'credit_note'.
create view filing.v_supply_lines with (security_invoker = true) as
select source_kind, source_id, source_ref, gstin, return_instance_id, return_period, doc_date, doc_number,
       doc_kind, supply_class, counterparty_gstin, counterparty_name, pos_state_code, rate, hsn, uqc, quantity,
       taxable_value, igst, cgst, sgst, cess, null::char(15) as operator_gstin, null::text as marketplace,
       original_doc_number, original_doc_date, doc_value, business_id
from sales.v_filing_lines
union all
select source_kind, source_id, source_ref, gstin, return_instance_id, return_period, doc_date, doc_number,
       doc_kind, supply_class, counterparty_gstin, counterparty_name, pos_state_code, rate, hsn, uqc, quantity,
       taxable_value, igst, cgst, sgst, cess, null::char(15), null::text,
       original_doc_number, original_doc_date, doc_value, business_id
from imports.v_filing_lines;
grant select on filing.v_supply_lines to app_rw, app_ro;
