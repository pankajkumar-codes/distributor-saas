-- R1-M7 slice 3: what GST Filing reads from confirmed uploaded invoices (LLD-5 §3, plan decision 2).
-- Additive: one view, nothing existing is altered. security_invoker, so the caller's RLS applies.
--
-- - One row per current document line. A line that a later line supersedes is not shown.
-- - Own uploads only, and invoices and credit notes only. A debit note has no supply class yet (needs CA
--   check) and a marketplace document waits for its treatment answers (OPEN_QUESTIONS), so neither is a
--   supply line; filing counts the debit notes so the return can say they are not in it.
-- - source_ref is the file name and row the line came from, so every section row drills down to the file.
-- - uqc is the file's unit text as typed, upper-cased; blank is 'NA'. There is no mapping to the portal's
--   UQC list yet (needs CA / GST expert check, flagged in every build).
-- - doc_value is the document's total as the file gave it; when the file had none, the lines' sum.
create view imports.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.doc_kind when 'invoice' then 'own_invoice' else 'own_credit_note' end as source_kind,
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
where d.source = 'own_upload' and d.doc_kind in ('invoice', 'credit_note')
  and not exists (select 1 from imports.document_lines s where s.supersedes = l.id);
grant select on imports.v_filing_lines to app_rw, app_ro;

-- Confirmed documents that are not supply lines yet, so a return can say what it leaves out: debit notes
-- (no supply class, needs CA check) and marketplace documents (treatment not confirmed). Counts only; no
-- amounts and no counterparty.
create view imports.v_unsummed_documents with (security_invoker = true) as
select d.business_id, d.id as document_id, d.gstin, d.source, d.doc_kind, d.doc_number, d.doc_date
from imports.documents d
where d.source <> 'own_upload' or d.doc_kind = 'debit_note';
grant select on imports.v_unsummed_documents to app_rw, app_ro;
