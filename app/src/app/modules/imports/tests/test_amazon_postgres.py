"""The Amazon readers through the upload pipeline on PostgreSQL (R1-M4 slice 1): made-up files, the real
readers registered. Skipped unless PG_ADMIN_URL is set."""

import pytest
from sqlalchemy import text

from app.modules.imports import readers
from app.modules.imports.readers import register_platform_readers

from .fixtures import amazon as fxa
from .conftest import PG_ADMIN_URL, scalar
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_platform_readers()
    yield
    readers.clear_for_tests()


def mtr(content_b2c=None, content_b2b=None):
    files = {}
    if content_b2c is not None:
        files["MTR_B2C-JUL-2026.csv"] = content_b2c
    if content_b2b is not None:
        files["MTR_B2B-JUL-2026.csv"] = content_b2b
    return fxa.zipped(files)


def test_a_zip_of_both_reports_stages_two_runs_with_the_hold_rules(shop):  # noqa: F811
    pg, _, _ = shop
    z = mtr(fxa.b2c_good(gstin=GSTIN), fxa.b2b_good(gstin=GSTIN))
    upload_id, _ = upload(shop, "amazon", "july.zip", z, "application/zip")
    assert run_jobs(shop) == ["done"]
    assert state(shop, upload_id)["status"] == "parsed"
    runs = pg.owner.connect().execute(
        text("select profile_id, profile_verified, gstin from imports.import_runs order by profile_id")).all()
    assert [r.profile_id for r in runs] == ["amazon/mtr_b2b@1", "amazon/mtr_b2c@1"]
    assert all(r.profile_verified is False and r.gstin == GSTIN for r in runs)
    statuses = pg.owner.connect().execute(
        text("select status, hold_reason, count(*) n from imports.import_rows group by 1, 2 order by 1, 2")).all()
    counts = {(r.status, r.hold_reason): r.n for r in statuses}
    assert counts.get(("skipped_zero", None), 0) >= 1
    assert sum(counts.values()) == scalar(pg.owner, "select count(*) from imports.import_rows")


def test_held_reasons_come_through(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "amazon", "july.zip", mtr(fxa.b2c_held(gstin=GSTIN)), "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["status"] == "parsed"
    reasons = {r[0] for r in pg.owner.connect().execute(
        text("select hold_reason from imports.import_rows where status = 'held'")).all()}
    assert reasons == {"blank_hsn", "blank_qty", "unknown_state", "unknown_txn_type", "sanity"}


def test_the_same_zip_twice_makes_no_new_rows(shop):  # noqa: F811
    pg, _, _ = shop
    z = mtr(fxa.b2c_good(gstin=GSTIN))
    one, _ = upload(shop, "amazon", "july.zip", z, "application/zip")
    two, _ = upload(shop, "amazon", "july-again.zip", z, "application/zip")
    assert run_jobs(shop) == ["done", "done"]
    assert state(shop, one)["run_id"] == state(shop, two)["run_id"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 1


def test_a_report_for_another_gstin_is_rejected_whole(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "amazon", "july.zip", mtr(fxa.b2c_good(gstin=fxa.OTHER)), "application/zip")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("rejected", "wrong_gstin")
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_the_run_warns_that_the_layout_is_unchecked(shop):  # noqa: F811
    pg, biz, _ = shop
    from .test_uploads_postgres import get
    upload_id, _ = upload(shop, "amazon", "july.zip", mtr(fxa.b2c_good(gstin=GSTIN)), "application/zip")
    run_jobs(shop)
    run_id = state(shop, upload_id)["run_id"]
    body = get(pg, f"/api/v1/b/{biz}/runs/{run_id}").json()
    assert body["profile_verified"] is False and body["warnings"]
