"""Own-invoice PDFs through the upload pipeline on PostgreSQL (R1-M6 slice 2b). Skipped unless PG_ADMIN_URL is set.
Synthetic PDFs only."""

import sys

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_readers

from .conftest import PG_ADMIN_URL, scalar
from .fixtures import own_excel as xl
from .fixtures.pdf import bomb, invoice_page, pdf
from .test_own_excel_postgres import XLSX, book
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import get, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
APP_PDF = "application/pdf"
TWO_LINES = (("6109", "2", "PCS", "200.00", "18", "18.00", "18.00", ""),
             ("6110", "1", "NOS", "100.00", "18", "9.00", "9.00", ""))


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


def page(number="INV-1", **kw):
    return invoice_page(number, seller=GSTIN, **kw)


def rows(pg):
    return pg.owner.connect().execute(
        text("select row_number, status, hold_reason from imports.import_rows order by row_number")).all()


def settle(shop_, name, data):  # noqa: F811
    upload_id, _ = upload(shop_, "own_invoices_pdf", name, data, APP_PDF)
    run_jobs(shop_)
    return state(shop_, upload_id)


def test_a_pdf_is_read_staged_and_held_where_a_detail_is_unclear(shop):  # noqa: F811
    pg, _, _ = shop
    no_hsn = page("INV-3", lines=(("", "1", "PCS", "100.00", "18", "9.00", "9.00", ""),))
    out = settle(shop, "inv.pdf", pdf([page("INV-1", lines=TWO_LINES), page("INV-2"), no_hsn]))
    assert (out["status"], out["reject_reason"]) == ("parsed", None)
    assert [(r.status, r.hold_reason) for r in rows(pg)] == [
        ("new", None), ("new", None), ("new", None), ("held", "pdf_unclear")]
    run = pg.owner.connect().execute(
        text("select marketplace, report_type, profile_id, profile_verified from imports.import_runs")).one()
    assert tuple(run) == ("own_invoices", "invoices_pdf", "own_invoices/invoices_pdf@1", False)


def test_the_hold_wording_comes_from_refdata_and_the_row_cannot_be_accepted(shop):  # noqa: F811
    pg, biz, _ = shop
    settle(shop, "inv.pdf", pdf([page("INV-3", lines=(("", "1", "PCS", "100.00", "18", "9.00", "9.00", ""),))]))
    run_id = scalar(pg.owner, "select id from imports.import_runs")
    (row,) = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held").json()["rows"]
    assert row["reason_label"] == "Check this against your invoice"
    assert [a["action"] for a in row["allowed_actions"]] == ["set_aside"]  # accept is off for this reason
    assert row["values"]["Unclear fields"] == "hsn"  # the field names only, never a value from the file


def test_a_scan_with_no_text_is_refused_whole_in_plain_words(shop):  # noqa: F811
    pg, biz, _ = shop
    out = settle(shop, "scan.pdf", pdf([[]]))
    assert (out["status"], out["reject_reason"]) == ("rejected", "no_text_layer")
    assert "scan" in out["reject_message"] and scalar(pg.owner, "select count(*) from imports.import_runs") == 0
    mixed = settle(shop, "mixed.pdf", pdf([page("INV-1"), []]))
    assert mixed["reject_reason"] == "no_text_layer"


def test_another_sellers_pdf_and_an_ambiguous_one_are_refused(shop):  # noqa: F811
    pg, _, _ = shop
    other = invoice_page("INV-1", seller=xl.OTHER)
    assert settle(shop, "other.pdf", pdf([other]))["reject_reason"] == "wrong_gstin"
    two = page("INV-1", header_extra=[(40, 560, "Invoice No: INV-2")])
    assert settle(shop, "two.pdf", pdf([two]))["reject_reason"] == "pdf_ambiguous"
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_a_file_that_is_not_a_pdf_or_is_broken_is_refused(shop):  # noqa: F811
    assert settle(shop, "x.pdf", b"hello")["reject_reason"] == "not_a_pdf"
    assert settle(shop, "y.pdf", b"%PDF-1.4\nnot really")["reject_reason"] == "read_failed"


@pytest.mark.skipif(sys.platform != "linux", reason="the memory limit is enforced on Linux")
def test_a_decompression_bomb_is_refused_and_the_queue_moves_on(shop):  # noqa: F811
    pg, _, _ = shop
    out = settle(shop, "bomb.pdf", bomb(700 * 1024 * 1024))
    assert (out["status"], out["reject_reason"]) == ("rejected", "read_failed")
    ok = settle(shop, "ok.pdf", pdf([page("INV-1")]))
    assert ok["status"] == "parsed"
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 1


def test_the_same_pdf_twice_makes_no_new_run_or_rows(shop):  # noqa: F811
    pg, _, _ = shop
    data = pdf([page("INV-1")])
    settle(shop, "a.pdf", data)
    first = len(rows(pg))
    settle(shop, "b.pdf", data)
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 1 and len(rows(pg)) == first


def test_the_same_document_in_an_excel_and_a_pdf_are_two_runs_not_one_that_changed(shop):  # noqa: F811
    pg, _, _ = shop
    upload(shop, "own_invoices_excel", "invoices.xlsx", book([xl.line("INV-1", gstin=GSTIN)]), XLSX)
    run_jobs(shop)
    settle(shop, "inv.pdf", pdf([page("INV-1")]))
    assert scalar(pg.owner, "select count(distinct report_type) from imports.import_runs") == 2
    assert {r.status for r in rows(pg)} == {"new"}
