-- S3-c2 (#69 review): the apply records why a row it left stale was refused, when the
-- reason is the row's own rate failing refdata's check again at confirm. Only errors and
-- outcome are ever updated on an import row; the parsed values stay as previewed.
grant update (errors) on catalog.import_rows to app_rw;
