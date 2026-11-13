-- R1-M3 slice 4: what a user decided about a held row (LLD-7 §2.1, §5). Insert-only: the
-- latest row for an import row wins, and nothing is updated or deleted, so the history of
-- decisions stays. A note is required (it is the reason, and it is audited). Forward-only
-- and additive. `set_aside` leaves the row out of the return; `accepted` uses the row as the
-- file states it, and is offered only where refdata allows it for that hold reason.

alter table imports.import_rows add constraint import_rows_id_business_key unique (id, business_id);

create table imports.row_resolutions (
    id uuid primary key,
    business_id uuid not null,
    row_id uuid not null,
    kind varchar(20) not null check (kind in ('set_aside', 'accepted')),
    note text not null check (length(btrim(note)) > 0 and length(note) <= 500),
    created_by uuid not null,
    created_at timestamptz not null default now(),
    foreign key (row_id, business_id) references imports.import_rows (id, business_id)
);
create index row_resolutions_by_row on imports.row_resolutions (row_id, created_at desc);

alter table imports.row_resolutions enable row level security;
alter table imports.row_resolutions force row level security;
create policy tenant_rw on imports.row_resolutions to app_rw
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '')
    with check (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy tenant_read_ro on imports.row_resolutions for select to app_ro
    using (business_id = nullif(current_setting('app.tenant_id', true), '')::uuid
               and coalesce(current_setting('app.support_grant_id', true), '') = '');
create policy support_read on imports.row_resolutions for select to app_rw, app_ro
    using (platform.support_grant_active(business_id));

grant select, insert on imports.row_resolutions to app_rw;
grant select on imports.row_resolutions to app_ro;
