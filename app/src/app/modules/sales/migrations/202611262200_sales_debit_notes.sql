-- Debit notes (#456 part 3, #462; CGST s.34(3) and Rule 53(1A)). Additive only.
--
-- - A debit note is its own insert-only document linked to the invoice it adds to, like a credit note, in its own
--   series (DN/YY-MM/NNNNNN when live, D-114; practice PR-DN-, never the invoices' or credit notes' series).
-- - By amount (value charged too low) the draft line keeps the added taxable value; by quantity (more goods sent than
--   invoiced) it keeps the quantity, as a goods-returned credit note does.
-- - A live debit note is a supply line: Table 9B with note type D, or netted into B2CS, adding (GST CA expert v2 §3,
--   GSTR-1 FAQ 17 and 19). v_filing_lines keeps its columns (view contract v1) and gains the source kind.
alter table sales.documents drop constraint documents_kind_check;
alter table sales.documents
    add constraint documents_kind_check check (kind in ('invoice', 'credit_note', 'debit_note'));
alter table sales.drafts drop constraint drafts_kind_check;
alter table sales.drafts add constraint drafts_kind_check check (kind in ('invoice', 'credit_note', 'debit_note'));
alter table sales.number_series drop constraint number_series_kind_check;
alter table sales.number_series
    add constraint number_series_kind_check check (kind in ('invoice', 'credit_note', 'debit_note', 'practice',
                                                            'practice_credit_note', 'practice_debit_note'));

alter table sales.draft_lines add column debit_taxable numeric(18, 2) check (debit_taxable > 0);  -- debit note by value

create or replace view sales.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.kind when 'invoice' then 'own_invoice' when 'debit_note' then 'own_debit_note' else 'own_credit_note' end
           as source_kind,
       d.kind as doc_kind, d.doc_number as source_ref, d.doc_number, d.doc_date, d.gstin, d.fy,
       d.doc_total as doc_value,
       o.doc_number as original_doc_number, o.doc_date as original_doc_date,
       d.return_instance_id, d.return_period, d.supply_class,
       d.counterparty_gstin, d.counterparty_name, d.pos_state_code, d.is_inter_state, d.utgst,
       l.line_no, l.hsn, l.uqc, l.quantity, l.rate, l.taxable as taxable_value,
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
