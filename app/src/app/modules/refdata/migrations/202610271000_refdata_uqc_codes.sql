-- refdata.uqc_codes: the units (UQC) a product may use (LLD-3 §4), loaded from
-- refdata/uqc_codes.yaml like state_codes, with the same dates, source and
-- confirmation columns. Global, no row-level security; app_rw and app_ro read only.

create table refdata.uqc_codes (
    code char(3) not null check (code ~ '^[A-Z]{3}$'),
    official_description text not null,   -- exactly as published (e-way bill master list)
    display_name text not null,            -- our label for the product screen
    einvoice_listed boolean not null,      -- on the e-invoice master list too (BOX isn't)
    valid_from date not null,
    valid_to date,
    source_url text not null,
    source_title text not null,
    last_checked date not null,
    status text not null check (status in ('provisional', 'expert_confirmed', 'ca_confirmed')),
    note text,
    confirmed_by text,
    confirmed_on date,
    loaded_from text not null,
    primary key (code, valid_from),
    check (valid_to is null or valid_to > valid_from),
    check (
        (status = 'provisional' and confirmed_by is null and confirmed_on is null)
        or (status <> 'provisional' and length(btrim(confirmed_by)) > 0 and confirmed_on is not null)
    ),
    exclude using gist (code with =, daterange(valid_from, coalesce(valid_to, 'infinity'), '[)') with &&)
);

grant select on refdata.uqc_codes to app_rw, app_ro;
