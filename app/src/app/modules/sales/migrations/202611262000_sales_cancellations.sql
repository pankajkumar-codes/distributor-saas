-- Cancelling an issued invoice (#456 part 2, GST CA expert answer v1 §1-3, §8). Additive only.
--
-- - Cancel is portal practice, not a legal procedure: allowed only while the invoice's return (GSTR-1 or IFF) is
--   open, never once a credit note exists, never twice. The invoice row is never touched (it stays insert-only);
--   the cancellation is its own insert-only row beside it, with the reason and the seller's declaration.
-- - The number stays used (rule 46(b)). A cancelled live invoice leaves Tables 4 to 12 (v_filing_lines drops it) and
--   is counted in Table 13 as issued and cancelled (v_cancelled_documents).

create table sales.document_cancellations (
    id uuid primary key,
    business_id uuid not null,
    document_id uuid not null unique,
    reason text not null check (reason in ('raised_in_error', 'duplicate', 'did_not_happen')),
    -- "The goods on this invoice were not removed or delivered" (§3). A duplicate needs none: the other invoice covers it.
    declared_not_delivered boolean not null,
    duplicate_of text check (duplicate_of is null or btrim(duplicate_of) <> ''),
    cancelled_by uuid not null,
    cancelled_at timestamptz not null default now(),
    check (reason = 'duplicate' or declared_not_delivered),
    foreign key (document_id, business_id) references sales.documents (id, business_id)
);

create trigger document_cancellations_insert_only before update or delete on sales.document_cancellations
    for each row execute function sales.refuse_change();
create trigger document_cancellations_no_truncate before truncate on sales.document_cancellations
    for each statement execute function sales.refuse_change();

alter table sales.document_cancellations enable row level security;
alter table sales.document_cancellations force row level security;
create policy tenant_rw on sales.document_cancellations to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.document_cancellations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.document_cancellations for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on sales.document_cancellations to app_rw;
grant select on sales.document_cancellations to app_ro;

-- Same columns as before (view contract v1); a cancelled invoice is no longer a supply line.
create or replace view sales.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.kind when 'invoice' then 'own_invoice' else 'own_credit_note' end as source_kind,
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

-- What Table 13 counts as cancelled: one row per cancelled live document, in the return it was assigned to.
create view sales.v_cancelled_documents with (security_invoker = true) as
select d.business_id, d.gstin, d.return_instance_id, d.kind as doc_kind, d.doc_number, c.cancelled_at
from sales.document_cancellations c
join sales.documents d on d.id = c.document_id and d.business_id = c.business_id
where not d.is_practice;
grant select on sales.v_cancelled_documents to app_rw, app_ro;
