"""The Flipkart readers through the upload pipeline on PostgreSQL (R1-M4 slice 2). Skipped unless
PG_ADMIN_URL is set."""

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_platform_readers

from .fixtures import amazon as fxa
from .fixtures import flipkart as fx
from .conftest import PG_ADMIN_URL, scalar
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NAME = "Sales Report - Jul 2026.xlsx"


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_platform_readers()
    yield
    readers.clear_for_tests()


def good(gstin=GSTIN):
    return fx.workbook([fx.sale("1", gstin=gstin), fx.sale("2", gstin=gstin, hsn=""), fx.sale("3", gstin=gstin, sub="Cancellation", taxable="0.0", invoice="0.0")],
                       [fx.note("CN-1", gstin=gstin)])


def test_one_workbook_stages_a_sales_run_and_a_cash_back_run(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "flipkart", NAME, good(), XLSX)
    assert run_jobs(shop) == ["done"]
    assert state(shop, upload_id)["status"] == "parsed"
    runs = pg.owner.connect().execute(
        text("select profile_id, sheet, profile_verified from imports.import_runs order by profile_id")).all()
    assert [(r.profile_id, r.sheet, r.profile_verified) for r in runs] == [
        ("flipkart/cashback@1", "Cash Back Report", False), ("flipkart/orders@1", "Sales Report", False)]
    counts = {(r.status, r.hold_reason): r.n for r in pg.owner.connect().execute(
        text("select status, hold_reason, count(*) n from imports.import_rows group by 1, 2"))}
    assert counts == {("new", None): 1, ("held", "blank_hsn"): 1, ("skipped_zero", None): 1,
                      ("held", "cashback_adjustment"): 1}


def test_a_workbook_inside_a_zip_works_and_a_second_upload_makes_no_new_runs(shop):  # noqa: F811
    pg, _, _ = shop
    z = fxa.zipped({NAME: good()})
    one, _ = upload(shop, "flipkart", "july.zip", z, "application/zip")
    two, _ = upload(shop, "flipkart", "july-again.zip", z, "application/zip")
    assert run_jobs(shop) == ["done", "done"]
    assert state(shop, one)["run_id"] == state(shop, two)["run_id"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 2
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 4


def test_another_gstin_on_a_later_row_in_either_sheet_rejects_the_workbook(shop):  # noqa: F811
    pg, _, _ = shop
    sales = fx.workbook([fx.sale("1", gstin=GSTIN), fx.sale("2", gstin=fx.OTHER)])
    notes = fx.workbook([fx.sale("1", gstin=GSTIN)], [fx.note("CN-1", gstin=GSTIN), fx.note("CN-2", gstin=fx.OTHER)])
    for content in (sales, notes):
        upload_id, _ = upload(shop, "flipkart", NAME, content, XLSX)
        run_jobs(shop)
        out = state(shop, upload_id)
        assert (out["status"], out["reject_reason"]) == ("rejected", "wrong_gstin")
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_a_workbook_with_a_header_only_cash_back_sheet_stages_the_sales_and_an_empty_run(shop):  # noqa: F811
    from .test_uploads_postgres import get
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "flipkart", NAME, fx.workbook([fx.sale("1", gstin=GSTIN)], []), XLSX)
    run_jobs(shop)
    assert state(shop, upload_id)["status"] == "parsed"
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 1
    empty = scalar(pg.owner, "select id from imports.import_runs where profile_id = 'flipkart/cashback@1'")
    body = get(pg, f"/api/v1/b/{biz}/runs/{empty}").json()
    assert body["counts"]["new"] == 0 and "no_rows" in [w["code"] for w in body["warnings"]]


def test_a_workbook_with_no_sheet_a_reader_names_is_an_unknown_layout(shop):  # noqa: F811
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    wb.active.title = "Other"
    wb.create_sheet("Another")
    buf = io.BytesIO()
    wb.save(buf)
    upload_id, _ = upload(shop, "flipkart", NAME, buf.getvalue(), XLSX)
    run_jobs(shop)
    assert state(shop, upload_id)["status"] == "rejected"
