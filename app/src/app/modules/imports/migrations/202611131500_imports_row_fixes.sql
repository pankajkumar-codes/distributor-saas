-- R1-M4 slice 4b: a user's value fix on a held row (platform-reader-spec section 1, rule "missing things
-- become held rows"): enter the HSN of a row that has none, or pick the state of a row whose state is
-- missing. Still insert-only, still one decision per row, still needs a note. The decision keeps the field
-- and the value the user chose; the row as the file said it is never changed. Forward-only and additive.
alter table imports.row_resolutions drop constraint row_resolutions_kind_check;
alter table imports.row_resolutions
    add constraint row_resolutions_kind_check check (kind in ('set_aside', 'accepted', 'fixed')),
    add column fix_field varchar(10) check (fix_field in ('hsn', 'state')),
    add column fix_value varchar(20) check (length(btrim(fix_value)) > 0),
    add constraint row_resolutions_fix_with_fixed check
        ((kind = 'fixed') = (fix_field is not null and fix_value is not null));
