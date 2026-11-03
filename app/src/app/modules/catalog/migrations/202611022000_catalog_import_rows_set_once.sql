-- S3-c3 (#69 review, Staff): an import row's outcome and errors are written at most
-- once, by the apply. The column grants already keep parsed, status, diff, product_id and
-- compared_version as previewed; this makes "set once" the database's rule too, so no
-- later code path can rewrite what a preview or an apply recorded. Its own SQLSTATE, so it
-- never reads as an RLS refusal.
create function catalog.guard_import_row_once() returns trigger
    language plpgsql security invoker set search_path = pg_catalog, catalog, pg_temp as $$
begin
    if old.outcome is not null and new.outcome is distinct from old.outcome then
        raise exception 'an import row''s outcome is set once' using errcode = 'CIR01';
    end if;
    if old.errors is not null and new.errors is distinct from old.errors then
        raise exception 'an import row''s errors are set once' using errcode = 'CIR01';
    end if;
    return new;
end $$;
revoke all on function catalog.guard_import_row_once() from public;
create trigger import_rows_set_once before update on catalog.import_rows
    for each row execute function catalog.guard_import_row_once();
