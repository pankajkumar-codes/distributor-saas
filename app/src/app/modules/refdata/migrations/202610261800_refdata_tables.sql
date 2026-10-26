-- refdata: dated, cited reference data (LLD-0 §6, L0-3). Global, not per business:
-- every business reads the same rows, and only the migrator writes them, by loading
-- the YAML under refdata/ after the SQL migrations (migrator/migrator/refdata.py).
-- Rows are never edited or deleted in place; a new value is a new row with a later
-- valid_from, and the loader closes the previous one by setting its valid_to.
--
-- Global tables carry no row-level security (LLD-0 §4.5): app_rw and app_ro get
-- SELECT and nothing else, so neither can change a row whatever it sets.
--
-- Two columns beyond LLD-0 §6.2: values.kind (tax | product), which the status rule
-- and require_confirmed need [RM4-9], and loads.rows_updated, the metadata-only
-- changes (last_checked, status, source, note) §6.3 says a load records. state_codes
-- carries valid_from/valid_to because codes change with an effective date
-- (team/gst/gstin.md §3).

create extension if not exists btree_gist;  -- build-readiness 2.2
create schema if not exists refdata;
grant usage on schema refdata to app_rw, app_ro;

create table refdata.values (
    key text not null,
    value text not null,
    type text not null check (type in ('integer', 'decimal', 'text', 'boolean', 'pattern', 'enum')),
    kind text not null check (kind in ('tax', 'product')),
    valid_from date not null,
    valid_to date,
    source_url text not null,
    source_title text not null,
    last_checked date not null,
    status text not null check (
        (kind = 'product' and status in ('provisional', 'po_confirmed'))
        or (kind = 'tax' and status in ('provisional', 'expert_confirmed', 'ca_confirmed'))
    ),
    note text,
    loaded_from text not null,
    primary key (key, valid_from),
    check (valid_to is null or valid_to > valid_from),
    exclude using gist (key with =, daterange(valid_from, coalesce(valid_to, 'infinity'), '[)') with &&)
);

create table refdata.state_codes (
    code char(2) not null check (code ~ '^[0-9]{2}$'),
    name text not null,
    valid_from date not null,
    valid_to date,
    source_url text not null,
    source_title text not null,
    last_checked date not null,
    status text not null check (status in ('provisional', 'expert_confirmed', 'ca_confirmed')),
    note text,
    loaded_from text not null,
    primary key (code, valid_from),
    check (valid_to is null or valid_to > valid_from),
    exclude using gist (code with =, daterange(valid_from, coalesce(valid_to, 'infinity'), '[)') with &&)
);

create table refdata.templates (
    key text not null,
    version text not null,
    sha256 char(64) not null,
    file_name text not null,
    source_url text not null,
    last_checked date not null,
    status text not null check (status in ('provisional', 'expert_confirmed', 'ca_confirmed')),
    primary key (key, version)
);

create table refdata.loads (
    id uuid primary key,
    git_sha text not null,
    files jsonb not null,
    rows_inserted integer not null,
    rows_closed integer not null,
    rows_updated integer not null,
    at timestamptz not null default now()
);
create index loads_at on refdata.loads (at desc);

grant select on refdata.values, refdata.state_codes, refdata.templates, refdata.loads to app_rw, app_ro;
