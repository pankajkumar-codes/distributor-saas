-- Planted for AC-13: every structural rule in migrator/migrator/checks.py fails here.

create table sales.no_rls (id uuid primary key);

create table sales.half_rls (id uuid primary key);
alter table sales.half_rls enable row level security;

create table sales.unforced (id uuid primary key);
alter table sales.unforced enable row level security;
alter table sales.unforced force row level security;
alter table sales.unforced no force row level security;

create view sales.v_definer as select id from sales.no_rls;

create function sales.today_due() returns date language sql as $$ select current_date $$;
