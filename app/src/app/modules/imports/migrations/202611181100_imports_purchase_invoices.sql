-- R2-M2: purchase invoices. A business uploads a supplier's invoice (a PDF or a photo of a paper bill), we
-- read what we can, and the business confirms or corrects it on a review screen. Nothing here reaches the
-- catalog or stock: R2-M3 builds those from the confirmed lines. Forward-only and additive: new tables only.
--
-- - purchase_files: one row per presigned POST. It moves (received, read, rejected) like imports.uploads and holds
--   no cell values. A file with the same checksum as one already read is turned away, so a retry stages nothing twice.
-- - purchase_drafts and purchase_draft_lines: what the reader found, exactly as read, as text. Insert-only. A file
--   that cannot be read (a photo, a scan) gets one blank draft that names every field as unclear, so the business
--   types it in against the stored file.
-- - purchase_reviews and purchase_review_lines: the business's decision, once per draft: confirmed (with the final
--   values, each line pointing back to the draft line it came from, or to none when typed in) or discarded.
--   Insert-only: a confirmed purchase is never edited in place (CLAUDE.md 9).
-- - A confirmed purchase is unique per business, supplier GSTIN, financial year and number (case and spaces
--   folded; needs CA check, as for imports.documents).

create table imports.purchase_files (
    id uuid primary key,
    business_id uuid not null,
    s3_key text not null,
    file_name text not null check (file_name <> '' and length(file_name) <= 255),
    size_bytes bigint not null check (size_bytes > 0),
    kind text not null check (kind in ('pdf', 'image')),
    status text not null default 'pending' check (status in ('pending', 'received', 'read', 'rejected')),
    reject_reason text check (reject_reason is null or status = 'rejected'),
    checksum_sha256 char(64) check (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (id, business_id)
);
create index purchase_files_by_business on imports.purchase_files (business_id, created_at desc);
-- one live file per checksum: a rejected copy does not block a retry
create unique index purchase_files_one_per_checksum on imports.purchase_files (business_id, checksum_sha256)
    where status = 'read';

create table imports.purchase_drafts (
    id uuid primary key,
    business_id uuid not null,
    file_id uuid not null,
    ordinal int not null check (ordinal > 0),
    reader_id text not null,
    pages int[] not null,
    doc_type text,
    supplier_gstin text,
    doc_number text,
    doc_date text,
    invoice_total text,
    unclear text[] not null default '{}',
    created_at timestamptz not null default now(),
    unique (id, business_id),
    unique (file_id, ordinal),
    foreign key (file_id, business_id) references imports.purchase_files (id, business_id)
);
create index purchase_drafts_by_file on imports.purchase_drafts (business_id, file_id);

create table imports.purchase_draft_lines (
    id uuid primary key,
    business_id uuid not null,
    draft_id uuid not null,
    line_no int not null check (line_no > 0),
    page int not null check (page > 0),
    hsn text, quantity text, unit text, taxable_value text, gst_rate text,
    igst text, cgst text, sgst text, cess text,
    unclear text[] not null default '{}',
    unique (id, business_id),
    unique (draft_id, line_no),
    foreign key (draft_id, business_id) references imports.purchase_drafts (id, business_id)
);

create table imports.purchase_reviews (
    id uuid primary key,
    business_id uuid not null,
    draft_id uuid not null,
    decision text not null check (decision in ('confirmed', 'discarded')),
    supplier_gstin char(15),
    supplier_name varchar(120),
    doc_number varchar(40),
    doc_key varchar(40),
    fy char(7) check (fy ~ '^[0-9]{4}-[0-9]{2}$'),
    doc_date date,
    invoice_total numeric check (invoice_total is null or invoice_total >= 0),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    check (decision = 'discarded'
           or (supplier_gstin is not null and doc_number is not null and doc_key is not null
               and fy is not null and doc_date is not null)),
    unique (id, business_id),
    unique (business_id, draft_id),
    foreign key (draft_id, business_id) references imports.purchase_drafts (id, business_id)
);
create unique index purchase_reviews_one_confirmed on imports.purchase_reviews
    (business_id, supplier_gstin, fy, doc_key) where decision = 'confirmed';

create table imports.purchase_review_lines (
    id uuid primary key,
    business_id uuid not null,
    review_id uuid not null,
    line_no int not null check (line_no > 0),
    draft_line_id uuid,
    product_id uuid not null,  -- the catalog product this line was received into (no foreign key across modules)
    created_product boolean not null,
    product_name varchar(120) not null check (product_name <> ''),
    hsn varchar(8) not null,
    unit varchar(40),
    quantity numeric not null check (quantity > 0),
    taxable_value numeric not null check (taxable_value >= 0),
    gst_rate numeric not null check (gst_rate >= 0),
    igst numeric not null default 0 check (igst >= 0),
    cgst numeric not null default 0 check (cgst >= 0),
    sgst numeric not null default 0 check (sgst >= 0),
    cess numeric not null default 0 check (cess >= 0),
    unique (review_id, line_no),
    foreign key (review_id, business_id) references imports.purchase_reviews (id, business_id),
    foreign key (draft_line_id, business_id) references imports.purchase_draft_lines (id, business_id)
);
create index purchase_review_lines_by_review on imports.purchase_review_lines (business_id, review_id);

alter table imports.purchase_files enable row level security;
alter table imports.purchase_files force row level security;
create policy tenant_rw on imports.purchase_files to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.purchase_files for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.purchase_files for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.purchase_files to app_rw;
grant select on imports.purchase_files to app_ro;

alter table imports.purchase_drafts enable row level security;
alter table imports.purchase_drafts force row level security;
create policy tenant_rw on imports.purchase_drafts to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.purchase_drafts for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.purchase_drafts for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.purchase_drafts to app_rw;
grant select on imports.purchase_drafts to app_ro;

alter table imports.purchase_draft_lines enable row level security;
alter table imports.purchase_draft_lines force row level security;
create policy tenant_rw on imports.purchase_draft_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.purchase_draft_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.purchase_draft_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.purchase_draft_lines to app_rw;
grant select on imports.purchase_draft_lines to app_ro;

alter table imports.purchase_reviews enable row level security;
alter table imports.purchase_reviews force row level security;
create policy tenant_rw on imports.purchase_reviews to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.purchase_reviews for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.purchase_reviews for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.purchase_reviews to app_rw;
grant select on imports.purchase_reviews to app_ro;

alter table imports.purchase_review_lines enable row level security;
alter table imports.purchase_review_lines force row level security;
create policy tenant_rw on imports.purchase_review_lines to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.purchase_review_lines for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.purchase_review_lines for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));
grant select, insert on imports.purchase_review_lines to app_rw;
grant select on imports.purchase_review_lines to app_ro;

-- the files move; everything else is insert-only

create trigger purchase_drafts_insert_only before update or delete on imports.purchase_drafts
    for each row execute function imports.refuse_change();
create trigger purchase_drafts_no_truncate before truncate on imports.purchase_drafts
    for each statement execute function imports.refuse_change();

create trigger purchase_draft_lines_insert_only before update or delete on imports.purchase_draft_lines
    for each row execute function imports.refuse_change();
create trigger purchase_draft_lines_no_truncate before truncate on imports.purchase_draft_lines
    for each statement execute function imports.refuse_change();

create trigger purchase_reviews_insert_only before update or delete on imports.purchase_reviews
    for each row execute function imports.refuse_change();
create trigger purchase_reviews_no_truncate before truncate on imports.purchase_reviews
    for each statement execute function imports.refuse_change();

create trigger purchase_review_lines_insert_only before update or delete on imports.purchase_review_lines
    for each row execute function imports.refuse_change();
create trigger purchase_review_lines_no_truncate before truncate on imports.purchase_review_lines
    for each statement execute function imports.refuse_change();

grant update (status, reject_reason, checksum_sha256, updated_at) on imports.purchase_files to app_rw;
