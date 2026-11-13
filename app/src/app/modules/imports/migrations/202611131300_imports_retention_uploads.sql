-- retention.purge_uploads() (LLD-6 §6.2; R1-M3, TD-18): the database side of an upload's life.
--
-- Two things, and neither touches S3. (1) A `pending` upload (a presigned post was handed
-- out, the file never completed) older than refdata `imports.upload.pending_minutes` becomes
-- `expired`. (2) An upload older than refdata `imports.upload.keep_days` gets `raw_deleted_at`
-- set, so the page stops offering the raw file. The object itself is removed by the bucket's
-- own lifecycle rule for the `uploads/` area (infra/modules/storage `upload_retention_days`,
-- 90): the retention Lambda has no S3 permission and this rule gives it none. The two 90s must
-- move together; the rows, runs and decisions stay.
--
-- Follows purge_drafts (LLD-0 §4.4, D-041): owned by retention_owner, SECURITY DEFINER with a
-- fixed search_path, EXECUTE only to app_retention, retention.active on while it runs, refdata
-- `retention.purge_uploads.enabled` shipped false (a dry run still counts), no refdata row for
-- a period means keep everything, at most max_rows per step per call with `more`, one
-- retention_runs row per call that runs, and no percent sign in this file.
--
-- retention_owner may read only the columns that pick a row, (id, business_id, status,
-- created_at, raw_deleted_at), and change only (status, raw_deleted_at, updated_at) on
-- imports.uploads. Never a file name, a checksum or a row of what the file said, and nothing
-- on import_runs, import_rows or row_resolutions.

grant usage on schema imports to retention_owner;
grant select (id, business_id, status, created_at, raw_deleted_at) on imports.uploads to retention_owner;
grant update (status, raw_deleted_at, updated_at) on imports.uploads to retention_owner;
create policy retention_purge_select on imports.uploads for select to retention_owner
    using (current_setting('retention.active', true) = 'on');
create policy retention_purge_update on imports.uploads for update to retention_owner
    using (current_setting('retention.active', true) = 'on')
    with check (current_setting('retention.active', true) = 'on');

create function retention.purge_uploads(dry_run boolean default true, max_rows int default 5000)
returns jsonb
language plpgsql volatile security definer set search_path = pg_catalog, pg_temp as $$
declare
    lim int := least(greatest(coalesce(max_rows, 5000), 1), 5000);
    today date := (now() at time zone 'Asia/Kolkata')::date;
    raw text;
    pending_minutes int;
    keep_days int;
    pending_cutoff timestamptz;
    raw_cutoff timestamptz;
    n_expired int := null;
    n_raw int := null;
    cutoffs jsonb;
    counts jsonb;
    more boolean := false;
    result jsonb;
begin
    perform set_config('retention.active', 'on', true);

    select v.value into raw from refdata.values v
    where v.key = 'retention.purge_uploads.enabled'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if coalesce(raw, 'false') <> 'true' and not dry_run then
        perform set_config('retention.active', 'off', true);
        return jsonb_build_object('rule', 'purge_uploads', 'skipped', 'disabled');
    end if;

    raw := null;
    select v.value into raw from refdata.values v
    where v.key = 'imports.upload.pending_minutes'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if raw is not null then
        pending_minutes := raw::int;
        if pending_minutes < 1 then
            raise exception using message = 'refdata imports.upload.pending_minutes must be at least 1';
        end if;
        pending_cutoff := now() - make_interval(mins => pending_minutes);
        if dry_run then
            select count(*) into n_expired from (
                select 1 from imports.uploads u
                where u.status = 'pending' and u.created_at < pending_cutoff
                limit lim) x;
        else
            with gone as (
                update imports.uploads u set status = 'expired', updated_at = now()
                where u.id in (select p.id from imports.uploads p
                               where p.status = 'pending' and p.created_at < pending_cutoff
                               order by p.created_at limit lim)
                  and u.status = 'pending' and u.created_at < pending_cutoff
                returning 1
            )
            select count(*) into n_expired from gone;
        end if;
    end if;

    raw := null;
    select v.value into raw from refdata.values v
    where v.key = 'imports.upload.keep_days'
      and v.valid_from <= today and (v.valid_to is null or v.valid_to > today);
    if raw is not null then
        keep_days := raw::int;
        if keep_days < 1 then
            raise exception using message = 'refdata imports.upload.keep_days must be at least 1';
        end if;
        raw_cutoff := now() - make_interval(days => keep_days);
        if dry_run then
            select count(*) into n_raw from (
                select 1 from imports.uploads u
                where u.raw_deleted_at is null and u.created_at < raw_cutoff
                limit lim) x;
        else
            with gone as (
                update imports.uploads u set raw_deleted_at = now(), updated_at = now()
                where u.id in (select p.id from imports.uploads p
                               where p.raw_deleted_at is null and p.created_at < raw_cutoff
                               order by p.created_at limit lim)
                  and u.raw_deleted_at is null and u.created_at < raw_cutoff
                returning 1
            )
            select count(*) into n_raw from gone;
        end if;
    end if;

    cutoffs := jsonb_build_object('uploads_expired', pending_cutoff, 'raw_marked', raw_cutoff);
    counts := jsonb_build_object('uploads_expired', n_expired, 'raw_marked', n_raw);
    more := coalesce(n_expired, 0) >= lim or coalesce(n_raw, 0) >= lim;

    insert into platform.retention_runs (rule, dry_run, cutoffs, counts, more)
    values ('purge_uploads', dry_run, cutoffs, counts, more);
    result := jsonb_build_object('rule', 'purge_uploads', 'dry_run', dry_run,
                                 'cutoffs', cutoffs, 'counts', counts, 'more', more);
    perform set_config('retention.active', 'off', true);
    return result;
end
$$;

-- As in purge_drafts: CREATE on the schema is lent for the owner change only.
grant create on schema retention to retention_owner;
alter function retention.purge_uploads(boolean, int) owner to retention_owner;
revoke create on schema retention from retention_owner;
revoke all on function retention.purge_uploads(boolean, int) from public;
grant execute on function retention.purge_uploads(boolean, int) to app_retention;
