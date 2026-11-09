-- retention.purge_drafts() (LLD-6 §6.2 row purge_drafts; LLD-4 §2.1: drafts are not GST
-- records). Deletes drafts still open after refdata `sales.draft_keep_days` days without
-- a save, and their lines with them. It follows purge_operational's pattern (LLD-0 §4.4,
-- D-041): owned by retention_owner, SECURITY DEFINER with a fixed search_path, EXECUTE
-- only to app_retention, retention.active on while it runs, refdata
-- `retention.purge_drafts.enabled` shipped false, no refdata row = keep everything, at most
-- max_rows drafts per call with `more`, dry_run counts without deleting, one
-- retention_runs row per call that runs, and no percent sign in this file.
--
-- Only drafts with status 'open' can go: a finalized draft is the input to a posted
-- document, and drafts_only_while_open (SDR01) would refuse it anyway. "Open longer than N
-- days" is read as N days since the last save (updated_at), so a draft someone is still
-- working on is never deleted under them; the delete re-checks both conditions on the row
-- it removes, so a save that lands between the pick and the delete keeps the draft.
--
-- retention_owner gets SELECT and DELETE on sales.drafts and SELECT on sales.draft_lines
-- (to count them). Lines go by the existing ON DELETE CASCADE, which runs as the table
-- owner; retention_owner needs no DELETE on lines, and nothing at all on number_series or
-- any document, stock or GST table.

grant usage on schema sales to retention_owner;
grant select, delete on sales.drafts to retention_owner;
grant select on sales.draft_lines to retention_owner;
create policy retention_purge_select on sales.drafts for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_delete on sales.drafts for delete to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_select on sales.draft_lines for select to retention_owner
    using (current_setting('retention.active', true) = 'on');

-- The daily scan, across businesses, oldest first.
create index drafts_open_stale on sales.drafts (updated_at) where status = 'open';

create function retention.purge_drafts(dry_run boolean default true, max_rows int default 5000)
returns jsonb
language plpgsql volatile security definer set search_path = pg_catalog, pg_temp as $$
declare
    lim int := least(greatest(coalesce(max_rows, 5000), 1), 5000);
    today date := (now() at time zone 'Asia/Kolkata')::date;
    raw text;
    keep int;
    cutoff timestamptz;
    n_drafts int := 0;
    n_lines int := 0;
    cutoffs jsonb;
    counts jsonb;
    more boolean := false;
    result jsonb;
begin
    perform set_config('retention.active', 'on', true);

    select v.value into raw from refdata.values v
    where v.key = 'retention.purge_drafts.enabled'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if coalesce(raw, 'false') <> 'true' and not dry_run then
        perform set_config('retention.active', 'off', true);
        return jsonb_build_object('rule', 'purge_drafts', 'skipped', 'disabled');
    end if;

    raw := null;
    select v.value into raw from refdata.values v
    where v.key = 'sales.draft_keep_days'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if raw is null then  -- no decided period: keep everything
        cutoffs := jsonb_build_object('drafts', null, 'draft_lines', null);
        counts := jsonb_build_object('drafts', null, 'draft_lines', null);
    else
        keep := raw::int;
        if keep < 0 then
            raise exception using message = 'refdata sales.draft_keep_days is negative';
        end if;
        cutoff := now() - make_interval(days => keep);
        if dry_run then
            select count(*), coalesce(sum(x.lines), 0) into n_drafts, n_lines
            from (select (select count(*) from sales.draft_lines l
                          where l.draft_id = d.id and l.business_id = d.business_id) as lines
                  from sales.drafts d
                  where d.status = 'open' and d.updated_at < cutoff
                  order by d.updated_at
                  limit lim) x;
        else
            -- RETURNING runs before the cascade, so each draft's lines are still there to count.
            with gone as (
                delete from sales.drafts d
                where d.id in (select p.id from sales.drafts p
                               where p.status = 'open' and p.updated_at < cutoff
                               order by p.updated_at
                               limit lim)
                  and d.status = 'open' and d.updated_at < cutoff
                returning (select count(*) from sales.draft_lines l
                           where l.draft_id = d.id and l.business_id = d.business_id) as lines
            )
            select count(*), coalesce(sum(lines), 0) into n_drafts, n_lines from gone;
        end if;
        cutoffs := jsonb_build_object('drafts', cutoff, 'draft_lines', cutoff);
        counts := jsonb_build_object('drafts', n_drafts, 'draft_lines', n_lines);
        more := n_drafts >= lim;
    end if;

    insert into platform.retention_runs (rule, dry_run, cutoffs, counts, more)
    values ('purge_drafts', dry_run, cutoffs, counts, more);
    result := jsonb_build_object('rule', 'purge_drafts', 'dry_run', dry_run,
                                 'cutoffs', cutoffs, 'counts', counts, 'more', more);
    perform set_config('retention.active', 'off', true);
    return result;
end
$$;

-- As in purge_operational: CREATE on the schema is lent for the owner change only.
grant create on schema retention to retention_owner;
alter function retention.purge_drafts(boolean, int) owner to retention_owner;
revoke create on schema retention from retention_owner;
revoke all on function retention.purge_drafts(boolean, int) from public;
grant execute on function retention.purge_drafts(boolean, int) to app_retention;
