-- sales drafts, S4-b: the ex-works flag, narrower update grants, and finalized drafts frozen
-- (the second review of #78).
--
-- customer_collects is "ex-works, the customer collects the goods" (tax-computation case D,
-- S4-c's input). app_rw may update only the columns a user edits: not id, business_id, kind,
-- status or the audit columns' creation half. status moves to 'finalized' only in the
-- finalize slice, which will grant that itself. A draft that is not open can no longer be
-- changed or deleted, and neither can its lines, whatever the service does (the draft is
-- the input to a posted document once finalized).

-- #78's guard gets the same hardening as the other guards.
alter function sales.guard_series_forward() set search_path = pg_catalog, sales, pg_temp;
revoke all on function sales.guard_series_forward() from public;

alter table sales.drafts add column customer_collects boolean not null default false;

revoke update on sales.drafts from app_rw;
grant update (customer_id, cash_buyer, bill_to, ship_to, ship_to_third_party, customer_collects, doc_date,
              invoice_discount, charges, eway, pos_override, pos_override_reason, version, updated_at, updated_by)
    on sales.drafts to app_rw;
revoke update on sales.draft_lines from app_rw;  -- lines are replaced whole (delete and insert)

create function sales.guard_draft_open() returns trigger
language plpgsql security invoker set search_path = pg_catalog, sales, pg_temp as $$
begin
    if old.status <> 'open' then
        raise exception 'draft % is % and cannot be changed or deleted', old.id, old.status
            using errcode = 'SDR01';
    end if;
    return case tg_op when 'DELETE' then old else new end;
end
$$;
revoke all on function sales.guard_draft_open() from public;
create trigger drafts_only_while_open before update or delete on sales.drafts
    for each row execute function sales.guard_draft_open();

create function sales.guard_draft_lines_open() returns trigger
language plpgsql security invoker set search_path = pg_catalog, sales, pg_temp as $$
declare
    parent_status text;
begin
    select status into parent_status from sales.drafts
        where id = coalesce(new.draft_id, old.draft_id) and business_id = coalesce(new.business_id, old.business_id)
        for share;  -- so the draft can't be finalized while a line is being written
    if parent_status is not null and parent_status <> 'open' then
        raise exception 'the draft is % and its lines cannot be changed', parent_status using errcode = 'SDR01';
    end if;
    return case tg_op when 'DELETE' then old else new end;
end
$$;
revoke all on function sales.guard_draft_lines_open() from public;
create trigger draft_lines_only_while_open before insert or update or delete on sales.draft_lines
    for each row execute function sales.guard_draft_lines_open();
