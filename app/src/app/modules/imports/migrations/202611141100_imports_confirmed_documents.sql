-- R1-M7 slice 2: confirmed documents and lines from uploaded files, and the user's "I have none this month"
-- (LLD-7 §2.2, plan team/engineering/r1-m7-gstr1-build.md decision 1). Forward-only and additive: new
-- tables only, nothing existing is altered.
--
-- - documents and document_lines are insert-only: app_rw has SELECT and INSERT only, and a trigger refuses
--   UPDATE, DELETE and TRUNCATE for every role (a confirmed document is never edited in place, CLAUDE.md 9).
--   A change a user accepts later is a new line that supersedes the old one.
-- - A document is a seller GSTIN, kind, the financial year of its date and its number, case and spaces
--   folded (document-fields.md, Rule 46(b); needs CA check). The return it belongs to is set once at confirm
--   (HLD 5.4); a debit note has none because the builder has no section for it yet.
-- - Amounts are exact `numeric`: values are kept as typed in the file and never rounded here.
-- - period_confirmations: the user said there are no sales of a section in a calendar month.

create function imports.refuse_change() returns trigger
    language plpgsql as $$
begin
    raise exception 'imports confirmed documents are insert-only' using errcode = '55000';
end $$;
revoke all on function imports.refuse_change() from public;

create table imports.documents (
    id uuid primary key,
    business_id uuid not null,
    gstin char(15) not null,
    source text not null check (source in ('own_upload', 'marketplace')),
    marketplace text,
    doc_kind text not null check (doc_kind in ('invoice', 'credit_note', 'debit_note')),
    doc_number varchar(40) not null,
    doc_key varchar(40) not null,
    fy char(7) not null check (fy ~ '^[0-9]{4}-[0-9]{2}$'),
    doc_date date not null,
    original_doc_number varchar(40),
    original_doc_date date,
    original_not_in_app boolean not null default false,
    supply_class text check (supply_class in ('B2B', 'B2CL', 'B2CS', 'CDNR', 'CDNUR')),
    counterparty_gstin char(15),
    pos_state_code char(2) not null,
    is_inter_state boolean not null,
    doc_total numeric,
    return_instance_id uuid,
    return_period char(7),
    first_run_id uuid not null,
    created_by uuid not null,
    created_at timestamptz not null default now(),
    check ((doc_kind = 'debit_note') = (supply_class is null)),
    check ((doc_kind = 'debit_note') = (return_instance_id is null)),
    unique (id, business_id)
);
create unique index documents_identity_uq on imports.documents (business_id, gstin, doc_kind, fy, doc_key);
create index documents_instance on imports.documents (business_id, return_instance_id);

alter table imports.documents enable row level security;
alter table imports.documents force row level security;
create policy tenant_rw on imports.documents to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.documents for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.documents for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on imports.documents to app_rw;
grant select on imports.documents to app_ro;
create trigger documents_insert_only before update or delete on imports.documents
    for each row execute function imports.refuse_change();
create trigger documents_no_truncate before truncate on imports.documents
    for each statement execute function imports.refuse_change();

create table imports.document_lines (
    id uuid primary key,
    business_id uuid not null,
    document_id uuid not null,
    source_row_id uuid not null,
    line_key char(64) not null,
    line_pos int not null check (line_pos > 0),
    hsn varchar(8) not null,
    hsn_from text not null check (hsn_from in ('file', 'fixed')),
    unit varchar(40),
    quantity numeric,
    rate numeric not null,
    taxable_value numeric not null,
    igst numeric not null,
    cgst numeric not null,
    sgst numeric not null,
    cess numeric not null,
    supersedes uuid references imports.document_lines (id),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    foreign key (document_id, business_id) references imports.documents (id, business_id)
);
create index document_lines_document on imports.document_lines (business_id, document_id);
create index document_lines_key on imports.document_lines (business_id, line_key);
create unique index document_lines_one_successor on imports.document_lines (supersedes) where supersedes is not null;

alter table imports.document_lines enable row level security;
alter table imports.document_lines force row level security;
create policy tenant_rw on imports.document_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.document_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.document_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on imports.document_lines to app_rw;
grant select on imports.document_lines to app_ro;
create trigger document_lines_insert_only before update or delete on imports.document_lines
    for each row execute function imports.refuse_change();
create trigger document_lines_no_truncate before truncate on imports.document_lines
    for each statement execute function imports.refuse_change();

create table imports.period_confirmations (
    id uuid primary key,
    business_id uuid not null,
    section text not null check (section in ('amazon', 'flipkart', 'meesho', 'own_invoices_excel', 'own_invoices_pdf')),
    month date not null check (extract(day from month) = 1),
    created_by uuid not null,
    created_at timestamptz not null default now()
);
create unique index period_confirmations_one on imports.period_confirmations (business_id, section, month);

alter table imports.period_confirmations enable row level security;
alter table imports.period_confirmations force row level security;
create policy tenant_rw on imports.period_confirmations to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.period_confirmations for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.period_confirmations for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on imports.period_confirmations to app_rw;
grant select on imports.period_confirmations to app_ro;
create trigger period_confirmations_insert_only before update or delete on imports.period_confirmations
    for each row execute function imports.refuse_change();
create trigger period_confirmations_no_truncate before truncate on imports.period_confirmations
    for each statement execute function imports.refuse_change();
