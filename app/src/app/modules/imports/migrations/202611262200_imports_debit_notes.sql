-- Uploaded debit notes reach GSTR-1 (#462). Additive: two views replaced with the same columns.
--
-- - A debit note confirmed from now on gets a supply class like a credit note (CDNR to a registered buyer, CDNUR when
--   its invoice was B2CL, otherwise netted into B2CS) and the return covering its date (GSTR-1 FAQ 17, GST CA expert
--   v2 §3), so it is a supply line here, with source kind own_debit_note. Table 9B gives it note type D.
-- - A debit note confirmed before this has no class and no return. It stays out of the supply lines and is still
--   counted in v_unsummed_documents, so its return keeps saying it is not included. No existing row changes.
-- - The table's checks tied "debit note" to "no class, no return". Now a class and a return come and go together, and
--   every other kind still has both.
alter table imports.documents drop constraint documents_check;
alter table imports.documents drop constraint documents_check1;
alter table imports.documents add constraint documents_class_check
    check (doc_kind = 'debit_note' or supply_class is not null);
alter table imports.documents add constraint documents_return_check
    check ((supply_class is null) = (return_instance_id is null));
create or replace view imports.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.doc_kind when 'invoice' then 'own_invoice' when 'debit_note' then 'own_debit_note'
           else 'own_credit_note' end as source_kind,
       d.doc_kind, r.filename || ' row ' || ir.row_number as source_ref, d.doc_number, d.doc_date, d.gstin, d.fy,
       coalesce(d.doc_total, t.lines_total) as doc_value,
       d.original_doc_number, d.original_doc_date, d.original_not_in_app,
       d.return_instance_id, d.return_period, d.supply_class,
       d.counterparty_gstin, null::text as counterparty_name, d.pos_state_code, d.is_inter_state,
       l.id as line_id, l.line_pos as line_no, l.hsn,
       coalesce(nullif(upper(btrim(l.unit)), ''), 'NA') as uqc,
       coalesce(l.quantity, 0) as quantity, l.rate, l.taxable_value, l.igst, l.cgst, l.sgst, l.cess
from imports.documents d
join imports.document_lines l on l.document_id = d.id and l.business_id = d.business_id
join imports.import_rows ir on ir.id = l.source_row_id and ir.business_id = l.business_id
join imports.import_runs r on r.id = ir.run_id and r.business_id = ir.business_id
cross join lateral (
    select sum(x.taxable_value + x.igst + x.cgst + x.sgst + x.cess) as lines_total
    from imports.document_lines x
    where x.document_id = d.id and x.business_id = d.business_id
      and not exists (select 1 from imports.document_lines s where s.supersedes = x.id)
) t
where d.source = 'own_upload'
  and (d.doc_kind in ('invoice', 'credit_note') or (d.doc_kind = 'debit_note' and d.supply_class is not null))
  and not exists (select 1 from imports.document_lines s where s.supersedes = l.id);

create or replace view imports.v_unsummed_documents with (security_invoker = true) as
select d.business_id, d.id as document_id, d.gstin, d.source, d.doc_kind, d.doc_number, d.doc_date
from imports.documents d
where d.source <> 'own_upload' or (d.doc_kind = 'debit_note' and d.supply_class is null);
