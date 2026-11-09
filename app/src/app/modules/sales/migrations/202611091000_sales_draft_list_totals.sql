-- S5-a: the draft list shows each draft's total and whether it is ready to finalize
-- without recomputing every row (LLD-4 §9 GET /drafts).
--
-- Written at every create and save from the computation the response already carries:
-- the total and the number of blocks as of that save, and when and by which method they
-- were computed. A cache for the list only, never authoritative: finalize recomputes
-- (LLD-4 §4 step 3), and a draft saved before this migration has nulls until its next
-- save. Additive; no row changes. app_rw gets update on the four columns only.
alter table sales.drafts
    add column total numeric(18,2),
    add column block_count int check (block_count >= 0),
    add column computed_at timestamptz,
    add column computed_method text;

grant update (total, block_count, computed_at, computed_method) on sales.drafts to app_rw;

-- The list pages newest first by (updated_at, id), both descending, for its cursor.
create index drafts_business_open_page on sales.drafts (business_id, updated_at desc, id desc)
    where status = 'open';
