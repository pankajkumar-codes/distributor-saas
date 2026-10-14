-- Design sketch for ADR 0001 (docs/adr/0001-commerce-data-model.md).
-- NOT a migration: the migrator only reads services/*/migrations/. This file exists so
-- tests/test_schema_sketch.py can prove the ADR's invariants on real PostgreSQL before
-- the owner approves the model. Requires the identity migrations (identity.is_member).
-- Only the tables that carry the hard invariants are sketched; the rest of the ADR's
-- tables follow the same conventions.

create schema if not exists commerce;

do $$ begin
    if not exists (select from pg_roles where rolname = 'svc_commerce') then
        create role svc_commerce login;
    end if;
end $$;
grant rds_iam to svc_commerce;
grant usage on schema commerce to svc_commerce;
grant usage on schema identity to svc_commerce;
grant execute on function identity.is_member(uuid) to svc_commerce;

create table commerce.locations (
    id uuid primary key,
    tenant_id uuid not null,
    name varchar(200) not null,
    unique (tenant_id, id)
);

create table commerce.products (
    id uuid primary key,
    tenant_id uuid not null,
    sku varchar(80) not null,
    name varchar(300) not null,
    unit varchar(20) not null,
    hsn_code varchar(16),
    unique (tenant_id, id),
    unique (tenant_id, sku)
);

create table commerce.number_series (
    id uuid primary key,
    tenant_id uuid not null,
    doc_type varchar(30) not null,
    financial_year varchar(9) not null,
    -- Which of these define the legal scope is decision D-010.
    legal_entity_id uuid,
    gst_registration_id uuid,
    location_id uuid,
    prefix varchar(20) not null default '',
    padding smallint not null default 5 check (padding between 1 and 12),
    next_value bigint not null default 1 check (next_value >= 1),
    unique (tenant_id, id)
);

create table commerce.sales_documents (
    id uuid primary key,
    tenant_id uuid not null,
    doc_type varchar(20) not null check (doc_type in ('invoice', 'credit_note', 'debit_note')),
    status varchar(12) not null default 'draft'
        check (status in ('draft', 'discarded', 'finalized', 'cancelled')),
    series_id uuid,
    sequence_no bigint,
    document_number varchar(40),
    document_date date not null,
    currency char(3) not null default 'INR' check (currency = 'INR'),
    rounding_mode varchar(20) not null check (rounding_mode in ('ROUND_HALF_UP', 'ROUND_HALF_EVEN')),
    rounding_level varchar(10) not null check (rounding_level in ('line', 'document')),
    total_amount numeric(18,2) not null default 0,
    created_by varchar(128) not null,
    finalized_at timestamptz,
    finalized_by varchar(128),
    cancelled_at timestamptz,
    cancelled_by varchar(128),
    cancel_reason varchar(500),
    unique (tenant_id, id),
    unique (tenant_id, series_id, sequence_no),
    foreign key (tenant_id, series_id) references commerce.number_series (tenant_id, id),
    -- A finalized or cancelled document always has its number; a draft never does.
    check ((status in ('finalized', 'cancelled')) = (sequence_no is not null and document_number is not null and finalized_at is not null)),
    check ((status = 'cancelled') = (cancelled_at is not null))
);

create table commerce.sales_lines (
    id uuid primary key,
    tenant_id uuid not null,
    document_id uuid not null,
    line_no int not null check (line_no > 0),
    product_id uuid not null,
    -- Snapshot: later product edits never change a finalized line.
    product_sku varchar(80) not null,
    product_name varchar(300) not null,
    hsn_code varchar(16),
    quantity numeric(18,3) not null check (quantity > 0),
    unit_price numeric(18,4) not null check (unit_price >= 0),
    discount_amount numeric(18,2) not null default 0 check (discount_amount >= 0),
    taxable_value numeric(18,2) not null,
    unique (tenant_id, id),
    unique (tenant_id, document_id, line_no),
    foreign key (tenant_id, document_id) references commerce.sales_documents (tenant_id, id),
    foreign key (tenant_id, product_id) references commerce.products (tenant_id, id)
);

create table commerce.sales_line_taxes (
    id uuid primary key,
    tenant_id uuid not null,
    line_id uuid not null,
    component varchar(20) not null,
    rate numeric(7,4) not null check (rate >= 0),
    amount numeric(18,2) not null,
    tax_rule_ref varchar(80),
    unique (tenant_id, line_id, component),
    foreign key (tenant_id, line_id) references commerce.sales_lines (tenant_id, id)
);

-- Finalized documents and their lines are immutable. The only permitted change is
-- finalized -> cancelled, touching nothing but the cancellation fields.
create function commerce.guard_sales_document() returns trigger
language plpgsql as $$
begin
    if old.status in ('finalized', 'discarded', 'cancelled') then
        if old.status = 'finalized' and new.status = 'cancelled'
           and (to_jsonb(new) - array['status','cancelled_at','cancelled_by','cancel_reason'])
             = (to_jsonb(old) - array['status','cancelled_at','cancelled_by','cancel_reason']) then
            return new;
        end if;
        raise exception 'sales document % is % and cannot be changed', old.id, old.status
            using errcode = 'check_violation';
    end if;
    return new;
end $$;
create trigger guard_sales_document before update on commerce.sales_documents
    for each row execute function commerce.guard_sales_document();

create function commerce.guard_sales_children() returns trigger
language plpgsql as $$
declare
    doc_status text;
begin
    if tg_table_name = 'sales_lines' then
        select status into doc_status from commerce.sales_documents
         where tenant_id = coalesce(new.tenant_id, old.tenant_id)
           and id = coalesce(new.document_id, old.document_id);
    else
        select d.status into doc_status
          from commerce.sales_lines l join commerce.sales_documents d
            on d.tenant_id = l.tenant_id and d.id = l.document_id
         where l.tenant_id = coalesce(new.tenant_id, old.tenant_id)
           and l.id = coalesce(new.line_id, old.line_id);
    end if;
    if doc_status <> 'draft' then
        raise exception 'lines of a % document cannot be changed', doc_status
            using errcode = 'check_violation';
    end if;
    return coalesce(new, old);
end $$;
create trigger guard_sales_lines before insert or update or delete on commerce.sales_lines
    for each row execute function commerce.guard_sales_children();
create trigger guard_sales_line_taxes before insert or update or delete on commerce.sales_line_taxes
    for each row execute function commerce.guard_sales_children();

-- Stock: append-only ledger, idempotent on its source, plus a lockable running balance.
create table commerce.stock_movements (
    id uuid primary key,
    tenant_id uuid not null,
    product_id uuid not null,
    location_id uuid not null,
    stock_state varchar(12) not null default 'sellable'
        check (stock_state in ('sellable', 'quarantine', 'damaged')),
    movement_type varchar(24) not null check (movement_type in (
        'opening', 'purchase_receipt', 'purchase_return', 'sale_reserve', 'sale_release',
        'sale_issue', 'sale_return_receive', 'restock', 'write_off', 'adjustment',
        'transfer_out', 'transfer_in', 'reversal')),
    on_hand_delta numeric(18,3) not null default 0,
    reserved_delta numeric(18,3) not null default 0,
    unit_cost numeric(18,4) check (unit_cost >= 0),
    occurred_at timestamptz not null,
    recorded_at timestamptz not null default now(),
    source_type varchar(40) not null,
    source_id varchar(120) not null,
    source_line_id varchar(120) not null default '',
    reverses_movement_id uuid unique,
    reason varchar(500),
    created_by varchar(128) not null,
    check (on_hand_delta <> 0 or reserved_delta <> 0),
    check ((movement_type = 'reversal') = (reverses_movement_id is not null)),
    check (movement_type not in ('adjustment', 'write_off') or reason is not null),
    unique (tenant_id, id),
    unique (tenant_id, source_type, source_id, source_line_id, movement_type),
    foreign key (tenant_id, product_id) references commerce.products (tenant_id, id),
    foreign key (tenant_id, location_id) references commerce.locations (tenant_id, id),
    foreign key (tenant_id, reverses_movement_id) references commerce.stock_movements (tenant_id, id)
);

create function commerce.reject_change() returns trigger
language plpgsql as $$
begin
    raise exception '% is append-only', tg_table_name using errcode = 'check_violation';
end $$;
create trigger stock_movements_append_only before update or delete on commerce.stock_movements
    for each row execute function commerce.reject_change();

create table commerce.stock_balances (
    tenant_id uuid not null,
    product_id uuid not null,
    location_id uuid not null,
    stock_state varchar(12) not null,
    on_hand numeric(18,3) not null default 0,
    reserved numeric(18,3) not null default 0 check (reserved >= 0),
    primary key (tenant_id, product_id, location_id, stock_state),
    foreign key (tenant_id, product_id) references commerce.products (tenant_id, id),
    foreign key (tenant_id, location_id) references commerce.locations (tenant_id, id)
);

-- Payments and append-only allocations.
create table commerce.payments (
    id uuid primary key,
    tenant_id uuid not null,
    direction varchar(10) not null check (direction in ('received', 'paid')),
    amount numeric(18,2) not null check (amount > 0),
    currency char(3) not null default 'INR' check (currency = 'INR'),
    payment_date date not null,
    external_ref varchar(120),
    created_by varchar(128) not null,
    unique (tenant_id, id)
);

create table commerce.payment_allocations (
    id uuid primary key,
    tenant_id uuid not null,
    payment_id uuid not null,
    sales_document_id uuid not null,
    amount numeric(18,2) not null check (amount <> 0),
    reverses_allocation_id uuid unique,
    created_by varchar(128) not null,
    created_at timestamptz not null default now(),
    check ((amount < 0) = (reverses_allocation_id is not null)),
    unique (tenant_id, id),
    foreign key (tenant_id, payment_id) references commerce.payments (tenant_id, id),
    foreign key (tenant_id, sales_document_id) references commerce.sales_documents (tenant_id, id),
    foreign key (tenant_id, reverses_allocation_id) references commerce.payment_allocations (tenant_id, id)
);
create trigger payment_allocations_append_only before update or delete on commerce.payment_allocations
    for each row execute function commerce.reject_change();

-- Idempotency and the transactional outbox.
create table commerce.idempotency_keys (
    tenant_id uuid not null,
    key varchar(200) not null,
    request_hash char(64) not null,
    response jsonb,
    created_at timestamptz not null default now(),
    primary key (tenant_id, key)
);

create table commerce.outbox_events (
    id uuid primary key,
    tenant_id uuid not null,
    event_type varchar(80) not null,
    payload jsonb not null,
    created_at timestamptz not null default now(),
    published_at timestamptz
);

-- Grants: no delete anywhere; ledgers are insert + select only.
grant select, insert on commerce.locations, commerce.products, commerce.number_series,
    commerce.sales_documents, commerce.sales_lines, commerce.sales_line_taxes,
    commerce.stock_movements, commerce.stock_balances, commerce.payments,
    commerce.payment_allocations, commerce.idempotency_keys, commerce.outbox_events
    to svc_commerce;
grant update on commerce.locations, commerce.products, commerce.number_series,
    commerce.sales_documents, commerce.sales_lines, commerce.sales_line_taxes,
    commerce.stock_balances, commerce.idempotency_keys, commerce.outbox_events
    to svc_commerce;
grant delete on commerce.sales_lines, commerce.sales_line_taxes to svc_commerce;  -- drafts only; trigger guards

-- Row-level security: the transaction's tenant, and only if the caller is a member.
do $$
declare t text;
begin
    foreach t in array array['locations','products','number_series','sales_documents',
        'sales_lines','sales_line_taxes','stock_movements','stock_balances','payments',
        'payment_allocations','idempotency_keys','outbox_events'] loop
        execute format('alter table commerce.%I enable row level security', t);
        execute format(
            'create policy tenant_rows on commerce.%I to svc_commerce
                using (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid
                       and identity.is_member(tenant_id))
                with check (tenant_id = nullif(current_setting(''app.tenant_id'', true), '''')::uuid
                       and identity.is_member(tenant_id))', t);
    end loop;
end $$;
