-- A credit or debit note by amount has no quantity (#480). Its lines are stored with quantity NULL, and
-- v_filing_lines passed that through, so the GSTR-1 HSN summary (filing/gstr1/sections.py _hsn) failed on
-- None and the whole return could not be built. The view contract (v1) says quantity is a number, and
-- imports.v_filing_lines already reports a missing quantity as 0. This does the same for own documents:
-- a value-only note moves the HSN row's value, not its quantity. Same columns, same rows, same types.
create or replace view sales.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.kind when 'invoice' then 'own_invoice' when 'debit_note' then 'own_debit_note' else 'own_credit_note' end
           as source_kind,
       d.kind as doc_kind, d.doc_number as source_ref, d.doc_number, d.doc_date, d.gstin, d.fy,
       d.doc_total as doc_value,
       o.doc_number as original_doc_number, o.doc_date as original_doc_date,
       d.return_instance_id, d.return_period, d.supply_class,
       d.counterparty_gstin, d.counterparty_name, d.pos_state_code, d.is_inter_state, d.utgst,
       l.line_no, l.hsn, l.uqc, coalesce(l.quantity, 0)::numeric(18, 3) as quantity, l.rate,
       l.taxable as taxable_value,
       coalesce((select t.amount from sales.document_line_taxes t where t.line_id = l.id and t.component = 'IGST'), 0)
           as igst,
       coalesce((select t.amount from sales.document_line_taxes t where t.line_id = l.id and t.component = 'CGST'), 0)
           as cgst,
       coalesce((select sum(t.amount) from sales.document_line_taxes t
                 where t.line_id = l.id and t.component in ('SGST', 'UTGST')), 0) as sgst,
       0::numeric(18, 2) as cess
from sales.documents d
join sales.document_lines l on l.document_id = d.id and l.business_id = d.business_id
left join sales.documents o on o.id = d.original_document_id and o.business_id = d.business_id
where not d.is_practice
  and not exists (select 1 from sales.document_cancellations c where c.document_id = d.id and c.business_id = d.business_id);
