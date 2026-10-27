-- business, S1-d2 (LLD-1 §4, §9, L1-14): the filing-profile view filing reads, and the
-- database backstop for the GSTIN lock.

-- v_filing_profile (HLD §3, LLD-1 §9): one row per frequency interval of each GSTIN.
-- Rows sharing an effective_from keep only the latest chosen_at, the same tie rule as
-- business.interface.filing_frequency_on; valid_to is the next interval's start
-- (exclusive), null for the one still running. security_invoker, so the caller's
-- tenant policy on filing_frequency_history applies.
create view business.v_filing_profile with (security_invoker = true) as
select h.business_id,
       h.gstin,
       left(h.gstin, 2)::char(2) as state_code,
       h.frequency,
       h.effective_from,
       lead(h.effective_from) over (partition by h.business_id, h.gstin order by h.effective_from) as valid_to
from (
    select distinct on (business_id, gstin, effective_from) business_id, gstin, frequency, effective_from
    from business.filing_frequency_history
    order by business_id, gstin, effective_from, chosen_at desc, id desc
) h;
grant select on business.v_filing_profile to app_rw, app_ro;

-- L1-14: once the first live document is finalized (lock_gstin), the registration is
-- fixed and the lock can't be lifted. The API refuses first with 409 gstin_locked; this
-- catches any other writer. Its own SQLSTATE so it never reads as an RLS refusal.
create function business.guard_profile_lock() returns trigger
    language plpgsql security invoker set search_path = pg_catalog, business, pg_temp as $$
begin
    if old.gstin_locked_at is not null
       and (new.registration_kind, new.gstin, new.enrolment_number, new.state_code, new.gstin_locked_at)
           is distinct from (old.registration_kind, old.gstin, old.enrolment_number, old.state_code, old.gstin_locked_at) then
        raise exception 'the GSTIN is locked once a live document is finalized' using errcode = 'BGL01';
    end if;
    return new;
end $$;
revoke all on function business.guard_profile_lock() from public;
create trigger profiles_guard_lock before update on business.profiles
    for each row execute function business.guard_profile_lock();
