-- R2-M1 (CEO 2026-11-18, D-095): business type becomes an optional multi-select that never blocks anything.
-- New array column beside the old single value; the old column is no longer read or written and goes in a later
-- migration (a drop needs the destructive-migration approval). Backfill is one-to-one: distributor -> distributor,
-- retail -> retailer; an empty array means "not chosen", which is every R1 business. RLS and grants on
-- business.profiles stay as they are.
alter table business.profiles
    add column business_types text[] not null default '{}'
        check (business_types <@ array['retailer', 'wholesaler', 'distributor', 'manufacturer', 'online_seller',
                                       'service_provider', 'other']::text[]);

update business.profiles
   set business_types = case business_type when 'distributor' then array['distributor'] else array['retailer'] end
 where business_type is not null;
