-- #429, D-108: the item description the reader found on a purchase invoice line, shown as the product name for the
-- business to check before it confirms. Text as read, at most 100 characters (the reader's cap); null when the PDF
-- had no description column, or for a photo or scan (nothing is read). Forward-only and additive: no existing row
-- changes, and the table stays insert-only (its triggers and grants cover the new column).
alter table imports.purchase_draft_lines
    add column description text check (description is null or (description <> '' and length(description) <= 100));
