-- R2-M6: sales.v_practice_documents, the practice documents (never filed) in one published view, so the monthly
-- Excel can list them on a sheet of their own, clearly apart from what is filed. Header totals only: no lines, no
-- customer name. security_invoker, so the caller's RLS applies.
create view sales.v_practice_documents with (security_invoker = true) as
select d.business_id, d.id as document_id, d.kind as doc_kind, d.doc_number, d.doc_date, d.gstin,
       d.counterparty_gstin, d.taxable_total, d.igst_total, d.cgst_total, d.sgst_total, d.cess_total, d.doc_total
from sales.documents d
where d.is_practice;
grant select on sales.v_practice_documents to app_rw, app_ro;
