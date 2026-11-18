-- R2-M6: imports.v_purchase_lines, the confirmed purchase invoices' lines in one published view, for the monthly
-- sales-and-purchases files (filing reads it; it never reads the tables). Only confirmed reviews appear: a draft the
-- business has not confirmed, or has set aside, is never here. Each row says which file, which pages and which read
-- line it came from (`draft_line_id` and `source_page` are null for a line the business typed in).
-- security_invoker, so the caller's RLS applies. Amounts are exact numeric as the business confirmed them.
create view imports.v_purchase_lines with (security_invoker = true) as
select r.business_id, r.id as review_id, r.supplier_gstin, r.supplier_name, r.doc_number, r.doc_date, r.fy,
       r.invoice_total, f.id as file_id, f.file_name, d.pages as source_pages, d.reader_id,
       l.id as line_id, l.line_no, l.draft_line_id, dl.page as source_page, dl.line_no as source_line_no,
       l.product_id, l.product_name, l.hsn, l.unit, l.quantity, l.taxable_value, l.gst_rate,
       l.igst, l.cgst, l.sgst, l.cess
from imports.purchase_reviews r
join imports.purchase_review_lines l on l.review_id = r.id and l.business_id = r.business_id
join imports.purchase_drafts d on d.id = r.draft_id and d.business_id = r.business_id
join imports.purchase_files f on f.id = d.file_id and f.business_id = d.business_id
left join imports.purchase_draft_lines dl on dl.id = l.draft_line_id and dl.business_id = l.business_id
where r.decision = 'confirmed';
grant select on imports.v_purchase_lines to app_rw, app_ro;
