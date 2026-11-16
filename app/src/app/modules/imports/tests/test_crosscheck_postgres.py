"""The Excel versus PDF cross-check on PostgreSQL (R1-M6 slice 3). Skipped unless PG_ADMIN_URL is set.
Synthetic files only."""

import pytest

from app.modules.imports import readers
from app.modules.imports.readers import register_readers

from .conftest import PG_ADMIN_URL, new_business
from .fixtures import own_excel as xl
from .fixtures.pdf import BUYER, invoice_page, pdf
from .test_own_excel_postgres import XLSX, book
from .test_parse_postgres import GSTIN
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
APP_PDF = "application/pdf"
NO_HSN = (("", "1", "PCS", "100.00", "18", "9.00", "9.00", ""),)


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


def excel(shop_, rows):  # noqa: F811
    upload(shop_, "own_invoices_excel", "invoices.xlsx", book(rows), XLSX)
    run_jobs(shop_)


def pdfs(shop_, *pages):  # noqa: F811
    upload(shop_, "own_invoices_pdf", "inv.pdf", pdf(list(pages)), APP_PDF)
    run_jobs(shop_)


def page(number="INV-1", **kw):
    return invoice_page(number, seller=GSTIN, **kw)


def check(shop_, sub="alice"):  # noqa: F811
    pg, biz, _ = shop_
    r = get(pg, f"/api/v1/b/{biz}/own-invoices/crosscheck", sub=sub)
    assert r.status_code == 200, r.text
    return r.json()


def test_nothing_uploaded_shows_no_note_and_compares_nothing(shop):  # noqa: F811
    out = check(shop)
    assert (out["show_validate_note"], out["compared"], out["matching"]) == (False, False, 0)


def test_an_excel_alone_shows_the_validate_note_and_is_not_compared(shop):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    out = check(shop)
    assert (out["show_validate_note"], out["compared"]) == (True, False)
    assert out["excel"] == {"live": True, "documents": 1, "unplaced_rows": 0}
    assert out["pdf"]["live"] is False and out["mismatches"] == []


def test_a_pdf_alone_does_not_show_the_note(shop):  # noqa: F811
    pdfs(shop, page("INV-1"))
    out = check(shop)
    assert (out["show_validate_note"], out["compared"]) == (False, False)


def test_the_same_invoice_in_both_matches_and_the_note_goes_away(shop):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1"))  # "West Bengal (19)" on the PDF, "West Bengal" in the Excel: the same state
    out = check(shop)
    assert (out["show_validate_note"], out["compared"], out["matching"]) == (False, True, 1)
    assert out["mismatches"] == [] and out["only_in_excel"] == [] and out["only_in_pdf"] == []


def test_every_kind_of_difference_is_listed_and_nothing_is_decided(shop):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER), xl.line("INV-2", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1", date="04-07-2026", total="300.00",
                    lines=(("6109", "2", "PCS", "250.00", "18", "22.50", "22.50", ""),
                           ("6110", "1", "NOS", "50.00", "18", "4.50", "4.50", ""))),
         page("INV-9"))
    out = check(shop)
    assert (out["matching"], out["excel"]["documents"], out["pdf"]["documents"]) == (0, 2, 2)
    assert [d["doc_number"] for d in out["only_in_excel"]] == ["INV-2"]
    assert [d["doc_number"] for d in out["only_in_pdf"]] == ["INV-9"]
    (m,) = out["mismatches"]
    assert m["document"]["doc_number"] == "INV-1"
    diffs = {d["field"]: (d["excel"], d["pdf"]) for d in m["differences"]}
    assert diffs == {"doc_date": ("2026-07-03", "2026-07-04"), "invoice_total": ("236", "300.00"),
                     "taxable_value": ("200", "300.00"), "cgst": ("18", "27.00"), "sgst": ("18", "27.00"),
                     "lines": ("1", "2")}
    assert len(m["excel_row_ids"]) == 1 and len(m["pdf_row_ids"]) == 2


def test_money_must_match_exactly_with_no_rounding_tolerance(shop):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1", lines=(("6109", "2", "PCS", "200.01", "18", "18.00", "18.00", ""),)))
    (m,) = check(shop)["mismatches"]
    assert [d["field"] for d in m["differences"]] == ["taxable_value"]


def test_an_undecided_held_row_makes_the_document_not_compared_not_a_false_mismatch(shop):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1", lines=NO_HSN))
    out = check(shop)
    assert out["mismatches"] == [] and out["matching"] == 0
    assert out["not_compared"] == [{"document": {"seller_gstin": GSTIN, "doc_type": "Invoice", "doc_number": "INV-1"},
                                    "excel_held_rows": 0, "pdf_held_rows": 1}]


def test_a_set_aside_row_is_left_out_so_the_difference_it_makes_shows(shop):  # noqa: F811
    pg, biz, _ = shop
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1", lines=(("6109", "2", "PCS", "200.00", "18", "18.00", "18.00", ""), NO_HSN[0])))
    row = get(pg, f"/api/v1/b/{biz}/runs/{_pdf_run(pg)}/rows?status=held").json()["rows"][0]
    done = post(pg, f"/api/v1/b/{biz}/rows/{row['row_id']}/resolve", {"action": "set_aside", "note": "not ours"}, key="k1")
    assert done.status_code == 200, done.text
    assert check(shop)["matching"] == 1  # the PDF without that line now agrees with the Excel


def _pdf_run(pg):
    from .conftest import scalar

    return scalar(pg.owner, "select id from imports.import_runs where report_type = 'invoices_pdf'")


def test_a_discarded_pdf_run_is_not_live_so_the_note_returns(shop):  # noqa: F811
    pg, biz, _ = shop
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1"))
    assert check(shop)["show_validate_note"] is False
    assert post(pg, f"/api/v1/b/{biz}/runs/{_pdf_run(pg)}/discard").status_code == 200
    out = check(shop)
    assert (out["show_validate_note"], out["compared"]) == (True, False)


def test_owner_admin_and_ca_read_it_billing_and_strangers_get_404(shop):  # noqa: F811
    pg, biz, _ = shop
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    for sub in ("alice", "adam", "cathy"):
        check(shop, sub)
    assert get(pg, f"/api/v1/b/{biz}/own-invoices/crosscheck", sub="bill").status_code == 404
    other = new_business(pg, "bob")
    assert get(pg, f"/api/v1/b/{biz}/own-invoices/crosscheck", sub="bob").status_code == 404
    mine = get(pg, f"/api/v1/b/{other}/own-invoices/crosscheck", sub="bob").json()  # bob sees only his own: nothing
    assert (mine["excel"]["live"], mine["pdf"]["live"], mine["show_validate_note"]) == (False, False, False)


def test_the_response_and_the_logs_carry_no_buyer_text(shop, caplog):  # noqa: F811
    excel(shop, [xl.line("INV-1", gstin=GSTIN, buyer=BUYER)])
    pdfs(shop, page("INV-1"))
    caplog.set_level("DEBUG")
    body = str(check(shop))
    assert "Demo Buyer" not in body + caplog.text and "Item description" not in body + caplog.text
