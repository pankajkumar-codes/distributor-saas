"""The Meesho readers through the upload pipeline on PostgreSQL (R1-M4 slice 3). Skipped unless
PG_ADMIN_URL is set."""

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_platform_readers

from .conftest import PG_ADMIN_URL, scalar
from .fixtures import amazon as fxa
from .fixtures import meesho as fx
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_platform_readers()
    yield
    readers.clear_for_tests()


def month(gstin=GSTIN, extra=()):
    sales = fx.workbook([fx.sale("1", gstin=gstin), fx.sale("2", gstin=gstin), fx.adjustment("2", gstin=gstin), *extra])
    returns = fx.workbook([fx.sale("1", gstin=gstin, cancel_return_date="2026-07-20 00:00:00")], headers=fx.RETURN_HEADERS)
    return fxa.zipped({"tcs_sales.xlsx": sales, "tcs_sales_return.xlsx": returns})


def test_a_month_zip_stages_a_sales_run_and_a_returns_run_and_holds_the_adjustment(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "meesho", "july.zip", month(), "application/zip")
    assert run_jobs(shop) == ["done"]
    assert state(shop, upload_id)["status"] == "parsed"
    runs = pg.owner.connect().execute(text("select profile_id, profile_verified from imports.import_runs order by 1")).all()
    assert [(r.profile_id, r.profile_verified) for r in runs] == [("meesho/orders@1", False), ("meesho/returns@1", False)]
    counts = {(r.status, r.hold_reason): r.n for r in pg.owner.connect().execute(
        text("select status, hold_reason, count(*) n from imports.import_rows group by 1, 2"))}
    assert counts == {("new", None): 3, ("held", "price_adjustment"): 1}


def test_the_same_month_twice_makes_no_new_runs_or_rows(shop):  # noqa: F811
    pg, _, _ = shop
    z = month()  # built once: a rebuilt workbook has different bytes, so a different checksum
    one, _ = upload(shop, "meesho", "july.zip", z, "application/zip")
    two, _ = upload(shop, "meesho", "july-again.zip", z, "application/zip")
    assert run_jobs(shop) == ["done", "done"]
    assert state(shop, one)["run_id"] == state(shop, two)["run_id"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 2
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 4


def test_identical_rows_stay_separate_and_colliding_rows_are_conflicts(shop):  # noqa: F811
    pg, _, _ = shop
    extra = [fx.sale("7", gstin=GSTIN), fx.sale("7", gstin=GSTIN),            # identical: two records
             fx.sale("8", gstin=GSTIN), fx.sale("8", gstin=GSTIN, state="KARNATAKA")]  # collide, differ
    upload(shop, "meesho", "july.zip", month(extra=extra), "application/zip")
    run_jobs(shop)
    counts = {r.status: r.n for r in pg.owner.connect().execute(text(
        "select r.status, count(*) n from imports.import_rows r join imports.import_runs u on u.id = r.run_id "
        "where u.profile_id = 'meesho/orders@1' group by 1"))}
    assert counts == {"new": 4, "held": 1, "conflict": 2}


def test_another_gstin_on_a_later_row_rejects_the_zip_whole(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "meesho", "july.zip", month(extra=[fx.sale("9", gstin=fx.OTHER)]), "application/zip")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("rejected", "wrong_gstin")
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_a_zip_entry_with_another_name_is_a_bad_zip(shop):  # noqa: F811
    z = fxa.zipped({"tcs_sales.xlsx": fx.sales_good(), "notes.txt": b"hi"})
    upload_id, _ = upload(shop, "meesho", "july.zip", z, "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] == "bad_zip"
