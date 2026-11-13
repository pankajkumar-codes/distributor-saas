"""Months on a run, `already_uploaded_of`, the coverage view and the from/to filters (R1-M4 slice 4) on
PostgreSQL, through the real readers on made-up files. Skipped unless PG_ADMIN_URL is set."""

import pytest

from app.modules.imports import readers
from app.modules.imports.readers import register_platform_readers

from .conftest import PG_ADMIN_URL, new_business
from .fixtures import amazon as fxa
from .test_parse_postgres import GSTIN, state
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture(autouse=True)
def real_readers():
    readers.clear_for_tests()
    register_platform_readers()
    yield
    readers.clear_for_tests()


def amazon_zip(rows_b2c=None):
    b2c = fxa.b2c_good(gstin=GSTIN) if rows_b2c is None else rows_b2c
    return fxa.zipped({"MTR_B2C-JUL-2026.csv": b2c, "MTR_B2B-JUL-2026.csv": fxa.b2b_good(gstin=GSTIN)})


def test_a_run_says_which_months_it_covers(shop):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "july.zip", amazon_zip(), "application/zip")
    run_jobs(shop)
    run = get(pg, f"/api/v1/b/{biz}/runs/{state(shop, upload_id)['run_id']}").json()
    assert run["months"] == ["2026-07"] and run["already_uploaded_of"] is None


def test_coverage_lists_each_platform_with_what_it_needs_and_has(shop):  # noqa: F811
    pg, biz, _ = shop
    upload(shop, "amazon", "july.zip", amazon_zip(), "application/zip")
    run_jobs(shop)
    body = get(pg, f"/api/v1/b/{biz}/marketplace-coverage").json()
    (month,) = body["months"]
    assert month["month"] == "2026-07"
    by = {p["marketplace"]: p for p in month["marketplaces"]}
    assert by["amazon"]["required"] == ["mtr_b2b", "mtr_b2c"] and by["amazon"]["received"] == ["mtr_b2b", "mtr_b2c"]
    assert by["amazon"]["complete"] is True and by["amazon"]["held_rows"] == 0
    assert by["flipkart"]["received"] == [] and by["flipkart"]["complete"] is False


def test_coverage_is_incomplete_with_one_of_two_reports_and_counts_open_held_rows(shop):  # noqa: F811
    pg, biz, _ = shop
    z = fxa.zipped({"MTR_B2C-JUL-2026.csv": fxa.b2c_held(gstin=GSTIN)})
    upload(shop, "amazon", "july.zip", z, "application/zip")
    run_jobs(shop)
    (month,) = get(pg, f"/api/v1/b/{biz}/marketplace-coverage").json()["months"]
    amazon = next(p for p in month["marketplaces"] if p["marketplace"] == "amazon")
    assert amazon["received"] == ["mtr_b2c"] and amazon["complete"] is False and amazon["held_rows"] == 7


def test_the_range_keeps_only_months_inside_it(shop):  # noqa: F811
    pg, biz, _ = shop
    upload(shop, "amazon", "july.zip", amazon_zip(), "application/zip")
    run_jobs(shop)
    base = f"/api/v1/b/{biz}/marketplace-coverage"
    assert len(get(pg, base + "?from=2026-07-01&to=2026-07-31").json()["months"]) == 1
    assert len(get(pg, base + "?from=2026-07-31").json()["months"]) == 1
    assert get(pg, base + "?from=2026-08-01&to=2026-09-30").json()["months"] == []
    assert get(pg, base + "?from=2026-09-01&to=2026-08-01").status_code == 422


def test_uploads_and_sections_are_filtered_by_the_months_they_cover_and_unplaced_ones_always_show(shop):  # noqa: F811
    pg, biz, _ = shop
    upload(shop, "amazon", "july.zip", amazon_zip(), "application/zip")
    upload(shop, "amazon", "notes.csv", b"a,b\n1,2\n")  # turned away: no month known
    run_jobs(shop)
    july = get(pg, f"/api/v1/b/{biz}/uploads?from=2026-07-01&to=2026-07-31").json()["uploads"]
    august = get(pg, f"/api/v1/b/{biz}/uploads?from=2026-08-01&to=2026-08-31").json()["uploads"]
    assert sorted(u["file_name"] for u in july) == ["july.zip", "notes.csv"]
    assert [u["file_name"] for u in august] == ["notes.csv"]
    sec = {s["section"]: s for s in get(pg, f"/api/v1/b/{biz}/upload-sections?from=2026-08-01&to=2026-08-31").json()["sections"]}
    assert sec["amazon"]["uploads"] == [] and sec["amazon"]["status"] == "not uploaded"  # rejected files are not live
    july_sec = {s["section"]: s for s in get(pg, f"/api/v1/b/{biz}/upload-sections?from=2026-07-01&to=2026-07-31").json()["sections"]}
    assert [u["file_name"] for u in july_sec["amazon"]["uploads"]] == ["july.zip"]
    assert "Merchant Tax Report" in sec["amazon"]["requirement_note"]


def test_a_file_whose_earlier_preview_was_discarded_says_so(shop):  # noqa: F811
    pg, biz, _ = shop
    z = amazon_zip()
    one, _ = upload(shop, "amazon", "july.zip", z, "application/zip")
    run_jobs(shop)
    first = state(shop, one)["run_id"]
    assert post(pg, f"/api/v1/b/{biz}/runs/{first}/discard").status_code == 200
    two, _ = upload(shop, "amazon", "july-again.zip", z, "application/zip")
    run_jobs(shop)
    again = get(pg, f"/api/v1/b/{biz}/runs/{state(shop, two)['run_id']}").json()
    assert again["id"] != first and again["already_uploaded_of"] is not None


def test_another_business_sees_no_coverage_and_cannot_read_ours(shop):  # noqa: F811
    pg, biz, _ = shop
    upload(shop, "amazon", "july.zip", amazon_zip(), "application/zip")
    run_jobs(shop)
    other = new_business(pg, "bob")
    assert get(pg, f"/api/v1/b/{other}/marketplace-coverage", sub="bob").json()["months"] == []
    assert get(pg, f"/api/v1/b/{biz}/marketplace-coverage", sub="bob").status_code == 404
