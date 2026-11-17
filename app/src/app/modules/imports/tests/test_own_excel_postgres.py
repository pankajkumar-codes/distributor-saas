"""The own-invoice Excel reader through the upload pipeline on PostgreSQL (R1-M5 slice 1). Skipped unless
PG_ADMIN_URL is set."""

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_readers

from .conftest import PG_ADMIN_URL, scalar
from .fixtures import own_excel as fx
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


def book(rows=None, **kw):
    rows = rows if rows is not None else [fx.line("INV-1", gstin=GSTIN), fx.inter("INV-2", gstin=GSTIN),
                                          fx.line("INV-3", gstin=GSTIN, hsn="")]
    return fx.workbook(rows, **kw)


def rows_of(pg):
    return pg.owner.connect().execute(
        text("select row_number, status, hold_reason from imports.import_rows order by row_number")).all()


def test_a_workbook_is_staged_with_the_hold_and_an_unverified_note(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "own_invoices_excel", "invoices.xlsx", book(), XLSX)
    assert run_jobs(shop) == ["done"]
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("parsed", None)
    assert [(r.status, r.hold_reason) for r in rows_of(pg)] == [("new", None), ("new", None), ("held", "blank_hsn")]
    run = pg.owner.connect().execute(text("select profile_id, profile_verified from imports.import_runs")).one()
    assert (run.profile_id, run.profile_verified) == ("own_invoices/invoices@1", False)


def test_the_state_list_and_the_number_pattern_come_from_refdata(shop):  # noqa: F811
    pg, _, _ = shop
    rows = [fx.line("INV-1", gstin=GSTIN, state="Atlantis"),
            fx.line("INV/2026-27/000000001", gstin=GSTIN),
            fx.line("CN-1", gstin=GSTIN, kind="Credit note")]
    upload(shop, "own_invoices_excel", "invoices.xlsx", book(rows), XLSX)
    run_jobs(shop)
    assert [(r.status, r.hold_reason) for r in rows_of(pg)] == [
        ("held", "unknown_state"), ("held", "number_format"), ("held", "missing_original")]


def test_a_csv_with_the_template_headers_is_read_too(shop):  # noqa: F811
    pg, _, _ = shop
    upload(shop, "own_invoices_excel", "invoices.csv", fx.csv_bytes([fx.line("INV-1", gstin=GSTIN)]))
    assert run_jobs(shop) == ["done"]
    assert [r.status for r in rows_of(pg)] == ["new"]


def test_another_or_blank_gstin_rejects_the_file_whole(shop):  # noqa: F811
    pg, _, _ = shop
    for name, rows, reason in (("other.xlsx", [fx.line("INV-1", gstin=GSTIN), fx.line("INV-2", gstin=fx.OTHER)],
                                "wrong_gstin"),
                               ("blank.xlsx", [fx.line("INV-1", gstin="")], "gstin_missing")):
        upload_id, _ = upload(shop, "own_invoices_excel", name, book(rows), XLSX)
        run_jobs(shop)
        out = state(shop, upload_id)
        assert (out["status"], out["reject_reason"]) == ("rejected", reason)
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_the_same_file_twice_makes_no_new_run_or_rows(shop):  # noqa: F811
    pg, _, _ = shop
    z = book()  # built once: a rebuilt workbook has different bytes, so a different checksum
    one, _ = upload(shop, "own_invoices_excel", "a.xlsx", z, XLSX)
    two, _ = upload(shop, "own_invoices_excel", "b.xlsx", z, XLSX)
    assert run_jobs(shop) == ["done", "done"]
    assert state(shop, one)["run_id"] == state(shop, two)["run_id"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 1
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 3


def test_a_corrected_or_reordered_invoice_after_confirm_shows_as_changed_never_a_silent_second_copy(shop):  # noqa: F811
    pg, _, _ = shop
    first = [fx.line("INV-1", gstin=GSTIN, hsn="6109"), fx.line("INV-1", gstin=GSTIN, hsn="6110")]
    upload(shop, "own_invoices_excel", "a.xlsx", book(first), XLSX)
    run_jobs(shop)
    with pg.owner.connect() as c:  # confirm is not exposed yet (R1-M7); mark the first run confirmed as the owner
        c.execute(text("update imports.import_runs set status = 'confirmed', confirmed_by = uploaded_by,"
                       " confirmed_at = now()"))
    corrected = [fx.line("INV-1", gstin=GSTIN, hsn="6109", taxable="300", cgst="27", sgst="27"), first[1]]
    reordered = [first[1], first[0]]
    for name, rows in (("b.xlsx", corrected), ("c.xlsx", reordered)):
        upload(shop, "own_invoices_excel", name, book(rows), XLSX)
    run_jobs(shop)
    by_file = {}
    for r in pg.owner.connect().execute(text(
            "select u.file_name, w.row_number, w.status from imports.import_rows w "
            "join imports.import_runs ru on ru.id = w.run_id join imports.uploads u on u.id = ru.upload_id "
            "where ru.status = 'staged' order by 1, 2")):
        by_file.setdefault(r.file_name, []).append(r.status)
    assert by_file["b.xlsx"] == ["changed", "already_imported"]  # only the corrected line differs
    assert by_file["c.xlsx"] == ["changed", "changed"]  # swapped lines are other content under the same keys
    assert not any("new" in v for v in by_file.values())


def test_a_workbook_without_the_invoices_sheet_or_headers_is_not_a_layout(shop):  # noqa: F811
    upload_id, _ = upload(shop, "own_invoices_excel", "x.xlsx", book(headers=fx.HEADERS[1:]), XLSX)
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] == "unknown_layout"


def test_no_log_or_audit_row_carries_a_cell_value(shop, caplog):  # noqa: F811
    pg, _, _ = shop
    marker = "ZZ-SECRET-7"
    with caplog.at_level("DEBUG"):
        upload(shop, "own_invoices_excel", "a.xlsx",
               book([fx.line(marker, gstin=GSTIN, buyer="29DEMOC9999C1Z1")]), XLSX)
        run_jobs(shop)
    assert marker not in caplog.text and "29DEMOC9999C1Z1" not in caplog.text
    audit = pg.owner.connect().execute(text("select data::text from platform.audit_log")).scalars().all()
    assert all(marker not in a and "29DEMOC9999C1Z1" not in a for a in audit)
