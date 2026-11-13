"""The local demo's sample files do what docs/LOCAL_DEMO.md says they do, through the real API.

The samples are built for the demo business's synthetic GSTIN; here they are built for the test
business's, which changes only that column. A drift test compares the committed files with the
generator."""

import importlib.util
import sys
from pathlib import Path

import pytest

from app import demo_readers
from app.modules.imports import readers
from app.modules.imports.parsing import read_table

from .conftest import scalar
from .test_parse_postgres import GSTIN, get, post, run_jobs, shop, state, upload  # noqa: F401

DEMO_DIR = Path(__file__).resolve().parents[6] / "demo"
spec = importlib.util.spec_from_file_location("make_samples", DEMO_DIR / "make_samples.py")
samples = importlib.util.module_from_spec(spec)
sys.modules["make_samples"] = samples
spec.loader.exec_module(samples)


@pytest.fixture(autouse=True)
def demo_reader(monkeypatch):
    readers.clear_for_tests()
    monkeypatch.setenv("DEMO_READERS", "1")
    assert demo_readers.register_demo_readers() is True
    yield
    readers.clear_for_tests()


def files():
    return samples.build(gstin=GSTIN)


def run_counts(shop, upload_id):  # noqa: F811
    pg, biz, _ = shop
    run_id = state(shop, upload_id)["run_id"]
    return get(pg, f"/api/v1/b/{biz}/runs/{run_id}").json()


def test_the_good_file_stages_with_nothing_held(shop):  # noqa: F811
    upload_id, _ = upload(shop, "amazon", "demo-orders-good.csv", files()["demo-orders-good.csv"])
    assert run_jobs(shop) == ["done"]
    assert state(shop, upload_id)["status"] == "parsed"
    run = run_counts(shop, upload_id)
    assert run["counts"]["new"] == 6 and run["counts"]["held"] == 0 and run["profile_verified"] is False


def test_the_held_rows_file_shows_two_held_and_one_skipped(shop):  # noqa: F811
    upload_id, _ = upload(shop, "flipkart", "demo-orders-held-rows.csv", files()["demo-orders-held-rows.csv"])
    run_jobs(shop)
    run = run_counts(shop, upload_id)
    assert (run["counts"]["new"], run["counts"]["held"], run["counts"]["skipped_zero"]) == (2, 2, 1)
    assert run["held_by_reason"] == {"blank_hsn": 1, "blank_qty": 1}


def test_the_wrong_gstin_file_is_refused_whole(shop):  # noqa: F811
    upload_id, _ = upload(shop, "amazon", "demo-orders-wrong-gstin.csv", files()["demo-orders-wrong-gstin.csv"])
    run_jobs(shop)
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("rejected", "wrong_gstin")
    assert scalar(shop[0].owner, "select count(*) from imports.import_runs") == 0


def test_the_bundle_zip_stages_both_files(shop):  # noqa: F811
    upload_id, _ = upload(shop, "meesho", "demo-orders-bundle.zip", files()["demo-orders-bundle.zip"], "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["status"] == "parsed"
    assert scalar(shop[0].owner, "select count(*) from imports.import_runs where upload_id = :u", u=upload_id) == 2


def test_a_file_that_is_not_a_report_is_refused(shop):  # noqa: F811
    upload_id, _ = upload(shop, "amazon", "not-a-report.csv", files()["not-a-report.csv"])
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] == "unknown_layout"


def test_the_own_invoice_workbook_is_not_read_in_this_milestone(shop):  # noqa: F811
    xlsx = files()["demo-own-invoices.xlsx"]
    upload_id, _ = upload(shop, "own_invoices_excel", "demo-own-invoices.xlsx", xlsx,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert out["status"] == "rejected" and out["reject_reason"] == "no_reader"


def test_committed_samples_match_the_generator():
    built = samples.build()
    for name, data in built.items():
        committed = (DEMO_DIR / "samples" / name).read_bytes()
        if name.endswith(".xlsx"):  # a workbook's bytes carry write times; compare what it says
            assert read_table(committed, name).rows == read_table(data, name).rows, name
        else:
            assert committed == data, f"{name} is out of date: run python demo/make_samples.py"


def test_demo_readers_refuse_to_register_unless_asked_and_local(monkeypatch):
    readers.clear_for_tests()
    monkeypatch.delenv("DEMO_READERS", raising=False)
    assert demo_readers.register_demo_readers() is False and readers.readers_for("amazon") == []
    monkeypatch.setenv("DEMO_READERS", "1")
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "api")  # on Lambda debug_env is never true
    assert demo_readers.register_demo_readers() is False and readers.readers_for("amazon") == []
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME")
    assert demo_readers.register_demo_readers() is True
    assert demo_readers.register_demo_readers() is True  # twice is fine
    assert [r.id for r in readers.readers_for("amazon")] == ["demo_amazon_orders_v1"]
