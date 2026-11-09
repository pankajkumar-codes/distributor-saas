-- sales documents, S5 finalize F1 (LLD-4 §2.3, §4, §10; HLD §5.2): the insert-only
-- snapshot a finalize writes, the draft's move to 'finalized', and the filing view.
--
-- - documents, document_lines, document_line_taxes and pos_overrides are insert-only:
--   app_rw has SELECT and INSERT only, and a trigger refuses UPDATE and DELETE for every
--   role, the owner included (a finalized invoice is never edited in place, CLAUDE.md 9).
-- - The number's uniqueness (L4-2's default scope, per GSTIN + kind + FY,
--   case-insensitive) is enforced here for live documents. The scope the code uses is read
--   from refdata `sales.numbering_scope` (provisional, D-010); this index is the default's
--   backstop, and a different scope would come with its own migration.
-- - status may move open -> finalized only, only with the draft's document already
--   written, and the existing SDR01 guard keeps it frozen afterwards.
-- - v_filing_lines never shows a practice document (TD-7, LLD-4 §10).
--
-- Finalize itself is off until refdata `sales.finalize.enabled` is true (CEO, 2026-11-09).

create table sales.documents (
    id uuid primary key,
    business_id uuid not null,
    draft_id uuid not null unique,  -- one document per draft (BH-5)
    kind text not null check (kind in ('invoice', 'credit_note')),
    is_practice boolean not null,
    series_id uuid not null references sales.number_series (id),
    doc_number varchar(16) not null,
    doc_date date not null,
    fy char(7) not null check (fy ~ '^[0-9]{4}-[0-9]{2}$'),
    gstin char(15) not null,
    supplier_state_code char(2) not null,
    customer_id uuid,  -- null for a cash sale
    counterparty_gstin char(15),
    counterparty_name text,
    pos_state_code char(2) not null,
    is_inter_state boolean not null,
    supply_class text not null check (supply_class in ('B2B', 'B2CL', 'B2CS', 'CDNR', 'CDNUR')),
    reverse_charge char(1) not null default 'N' check (reverse_charge in ('N', 'Y')),
    return_instance_id uuid,  -- set once at a live finalize (F2); null for practice
    return_period char(7),
    credit_days int not null default 0 check (credit_days >= 0),
    due_date date,
    original_document_id uuid,
    reason_code text,
    override_reason text,
    gross_total numeric(18, 2) not null,
    line_discount_total numeric(18, 2) not null,
    invoice_discount numeric(18, 2) not null,
    charges_total numeric(18, 2) not null,
    taxable_total numeric(18, 2) not null,
    cgst_total numeric(18, 2) not null,
    sgst_total numeric(18, 2) not null,  -- also carries UTGST
    utgst boolean not null,
    igst_total numeric(18, 2) not null,
    cess_total numeric(18, 2) not null default 0,
    round_off numeric(18, 2) not null default 0,
    doc_total numeric(18, 2) not null,
    amount_in_words text not null,
    print jsonb not null,  -- seller, buyer, ship-to, branding, eway, charge labels; no money
    rounding_mode text not null,
    method_version text not null,
    finalized_at timestamptz not null default now(),
    finalized_by uuid not null,
    unique (id, business_id),
    foreign key (draft_id, business_id) references sales.drafts (id, business_id)
);
create unique index documents_number_uq on sales.documents (business_id, gstin, fy, kind, lower(doc_number))
    where not is_practice;
create unique index documents_practice_number_uq on sales.documents (series_id, lower(doc_number))
    where is_practice;
create index documents_business_date on sales.documents (business_id, doc_date desc, id desc);

create table sales.document_lines (
    id uuid primary key,
    business_id uuid not null,
    document_id uuid not null,
    line_no int not null check (line_no > 0),
    product_id uuid,
    original_line_id uuid,
    code text,
    name text not null,
    hsn varchar(8) not null,
    uqc varchar(3) not null,
    quantity numeric(18, 3),
    unit_price numeric(18, 2),
    gross numeric(18, 2) not null,
    line_discount numeric(18, 2) not null,
    discount_share numeric(18, 2) not null,
    charge_share numeric(18, 2) not null,
    taxable numeric(18, 2) not null,
    rate numeric(5, 2) not null,
    rate_confirmed boolean not null,  -- as shown at finalize (BH-2 warning)
    foreign key (document_id, business_id) references sales.documents (id, business_id),
    unique (document_id, line_no),
    unique (id, business_id)
);

create table sales.document_line_taxes (
    line_id uuid not null,
    business_id uuid not null,
    component text not null check (component in ('CGST', 'SGST', 'UTGST', 'IGST')),
    rate numeric(5, 2) not null,
    amount numeric(18, 2) not null,
    primary key (line_id, component),
    foreign key (line_id, business_id) references sales.document_lines (id, business_id)
);

create table sales.pos_overrides (  -- G16: the trail beside the audit log
    document_id uuid primary key,
    business_id uuid not null,
    computed_pos char(2) not null,
    chosen_pos char(2) not null,
    reason text not null check (btrim(reason) <> ''),
    foreign key (document_id, business_id) references sales.documents (id, business_id)
);

-- Insert-only, whoever asks.
create function sales.refuse_change() returns trigger
language plpgsql security invoker set search_path = pg_catalog, pg_temp as $$
begin
    raise exception '% is insert-only', tg_table_name using errcode = 'SDC01';
end
$$;
revoke all on function sales.refuse_change() from public;
create trigger documents_insert_only before update or delete on sales.documents
    for each row execute function sales.refuse_change();
create trigger document_lines_insert_only before update or delete on sales.document_lines
    for each row execute function sales.refuse_change();
create trigger document_line_taxes_insert_only before update or delete on sales.document_line_taxes
    for each row execute function sales.refuse_change();
create trigger pos_overrides_insert_only before update or delete on sales.pos_overrides
    for each row execute function sales.refuse_change();
create trigger documents_no_truncate before truncate on sales.documents
    for each statement execute function sales.refuse_change();

-- Tenant policies, the drafts' pattern.
alter table sales.documents enable row level security;
alter table sales.documents force row level security;
create policy tenant_rw on sales.documents to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.documents for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.documents for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table sales.document_lines enable row level security;
alter table sales.document_lines force row level security;
create policy tenant_rw on sales.document_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.document_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.document_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table sales.document_line_taxes enable row level security;
alter table sales.document_line_taxes force row level security;
create policy tenant_rw on sales.document_line_taxes to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.document_line_taxes for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.document_line_taxes for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

alter table sales.pos_overrides enable row level security;
alter table sales.pos_overrides force row level security;
create policy tenant_rw on sales.pos_overrides to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on sales.pos_overrides for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on sales.pos_overrides for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on sales.documents, sales.document_lines, sales.document_line_taxes, sales.pos_overrides
    to app_rw;
grant select on sales.documents, sales.document_lines, sales.document_line_taxes, sales.pos_overrides to app_ro;

-- The draft's status: app_rw may now write it, but only open -> finalized, and only once
-- the draft's document exists (finalize writes the document first). SDR01 already refuses
-- any change to a draft that is no longer open.
grant update (status) on sales.drafts to app_rw;

create function sales.guard_draft_finalize() returns trigger
language plpgsql security invoker set search_path = pg_catalog, sales, pg_temp as $$
begin
    if new.status is distinct from old.status then
        if not (old.status = 'open' and new.status = 'finalized') then
            raise exception 'draft % cannot move from % to %', old.id, old.status, new.status using errcode = 'SDR02';
        end if;
        if not exists (select 1 from sales.documents d where d.draft_id = new.id and d.business_id = new.business_id)
        then
            raise exception 'draft % has no document and cannot be finalized', new.id using errcode = 'SDR02';
        end if;
    end if;
    return new;
end
$$;
revoke all on function sales.guard_draft_finalize() from public;
create trigger drafts_finalize_only_with_document before update on sales.drafts
    for each row execute function sales.guard_draft_finalize();

-- LLD-4 §10: what GST Filing reads (filing.v_supply_lines selects from it, view contract
-- v1, LLD-5 §3). One row per document line, never a practice document. security_invoker,
-- so the caller's RLS applies.
create view sales.v_filing_lines with (security_invoker = true) as
select d.business_id, d.id as source_id, d.id as document_id,
       case d.kind when 'invoice' then 'own_invoice' else 'own_credit_note' end as source_kind,
       d.kind as doc_kind, d.doc_number as source_ref, d.doc_number, d.doc_date, d.gstin, d.fy,
       d.doc_total as doc_value,  -- LLD-5 erratum S6-1, D-043: Table 4A/5/9B value columns
       o.doc_number as original_doc_number, o.doc_date as original_doc_date,  -- credit notes (9B)
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
where not d.is_practice;
grant select on sales.v_filing_lines to app_rw, app_ro;
