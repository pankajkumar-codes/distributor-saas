"""The parse job through to staged rows (R1-M3 slice 2) on PostgreSQL as app_rw, with a made-up
reader standing in for the platform readers. Made-up files; skipped unless PG_ADMIN_URL is set."""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import text

from app.modules.imports import readers, staging
from platform_common import jobs

from .conftest import PG_ADMIN_URL, scalar
from .fake_reader import TestReader
from .test_uploads_postgres import get, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

HEAD = "Seller Gstin,Order Id,Txn Type,Qty,Hsn,Amount\n"
GSTIN = "19AAPFU0939F1ZS"  # the business the test fixture creates


def csv(*rows, gstin=GSTIN):
    return (HEAD + "".join(f"{gstin},{r}\n" for r in rows)).encode()


GOOD = csv("O-1,Shipment,1,6109,100.00", "O-2,Shipment,,6109,50.00", "O-3,Shipment,1,,70.00",
           "O-4,Cancel,1,6109,0.00")


@pytest.fixture(autouse=True)
def reader():
    readers.clear_for_tests()
    readers.register(TestReader())
    yield
    readers.clear_for_tests()


def zipped(**files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def state(shop, upload_id):  # noqa: F811
    pg, biz, _ = shop
    return get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()


def test_a_file_is_staged_with_held_and_skipped_rows(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    assert run_jobs(shop) == ["done"]
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("parsed", None) and out["run_id"]
    rows = pg.owner.connect().execute(
        text("select row_number, status, hold_reason from imports.import_rows order by row_number")).all()
    assert [(r.status, r.hold_reason) for r in rows] == [
        ("new", None), ("held", "blank_qty"), ("held", "blank_hsn"), ("skipped_zero", None)]
    run = pg.owner.connect().execute(text("select summary, profile_verified, gstin, upload_id from imports.import_runs")).one()
    assert run.summary["new"] == 1 and run.summary["held"] == 2 and run.summary["skipped_zero"] == 1
    assert run.profile_verified is False  # no refdata row says the layout was checked
    assert run.gstin == GSTIN and str(run.upload_id) == upload_id


def test_the_same_file_twice_is_one_run(shop):  # noqa: F811
    pg, _, _ = shop
    one, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    two, _ = upload(shop, "amazon", "orders-copy.csv", GOOD)
    assert run_jobs(shop) == ["done", "done"]
    assert state(shop, one)["run_id"] == state(shop, two)["run_id"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 1
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 4


def test_a_file_for_another_gstin_is_rejected_whole(shop):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", csv("O-1,Shipment,1,6109,1.00", gstin="29AAAAA0000A1Z5"))
    run_jobs(shop)
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("rejected", "wrong_gstin")
    assert "different GSTIN" in out["reject_message"] and out["run_id"] is None
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_an_unknown_layout_is_rejected(shop):  # noqa: F811
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", b"a,b\n1,2\n")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert (out["status"], out["reject_reason"]) == ("rejected", "unknown_layout")
    assert "columns" in out["reject_message"]


def test_a_layout_two_readers_claim_needs_a_choice(shop):  # noqa: F811
    readers.register(TestReader("test_orders_v2"))
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] == "needs_choice"


def test_a_zip_stages_each_file_in_it(shop):  # noqa: F811
    pg, _, _ = shop
    z = zipped(**{"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "orders-b.csv": csv("B-1,Shipment,1,6109,2.00")})
    upload_id, _ = upload(shop, "amazon", "month.zip", z, "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["status"] == "parsed"
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 2


@pytest.mark.parametrize("files", [
    {"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "notes.txt": b"hello"},   # a file no reader expects
    {"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "sub/orders-b.csv": b"x"},  # a folder in a name
    {f"orders-{i}.csv": csv(f"A-{i},Shipment,1,6109,1.00") for i in range(11)},  # too many files
])
def test_a_bad_zip_is_rejected_with_nothing_stored(shop, files):  # noqa: F811
    pg, _, _ = shop
    upload_id, _ = upload(shop, "amazon", "month.zip", zipped(**files), "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] == "bad_zip"
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0


def test_a_crash_while_staging_leaves_no_half_run_and_the_retry_finishes(shop, monkeypatch):  # noqa: F811
    pg, _, _ = shop
    z = zipped(**{"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "orders-b.csv": csv("B-1,Shipment,1,6109,2.00")})
    upload_id, job_id = upload(shop, "amazon", "month.zip", z, "application/zip")
    real, calls = staging.stage, []

    def flaky(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(staging, "stage", flaky)
    assert run_jobs(shop) == ["retry"]
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0  # the first file's run was rolled back too
    assert state(shop, upload_id)["status"] == "received"
    assert jobs.run(uuid.UUID(str(job_id))) == "done"
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 2
    assert state(shop, upload_id)["status"] == "parsed"


def test_personal_and_unmapped_columns_are_not_stored(shop):  # noqa: F811
    pg, _, _ = shop
    body = ("Seller Gstin,Order Id,Txn Type,Qty,Hsn,Amount,Buyer Name\n"
            f"{GSTIN},O-9,Shipment,1,6109,5.00,Some Buyer\n").encode()
    upload(shop, "amazon", "orders-1.csv", body)
    run_jobs(shop)
    raw = scalar(pg.owner, "select raw::text from imports.import_rows")
    assert "Some Buyer" not in raw and "Buyer Name" not in raw


def run_of(shop, upload_id, sub="alice"):  # noqa: F811
    pg, biz, _ = shop
    return get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}", sub=sub).json()["run_id"]


def test_the_run_and_its_rows_read_back_in_plain_words(shop):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    run_id = run_of(shop, upload_id)
    run = get(pg, f"/api/v1/b/{biz}/runs/{run_id}").json()
    assert run["counts"] == {"new": 1, "already_imported": 0, "changed": 0, "duplicate": 0, "conflict": 0,
                             "invalid": 0, "held": 2, "skipped_zero": 1}
    assert run["held_by_reason"] == {"blank_hsn": 1, "blank_qty": 1}
    assert (run["section"], run["upload_id"], run["gstin"], run["status"]) == ("amazon", upload_id, GSTIN, "staged")
    assert run["profile_verified"] is False and run["warnings"][0]["code"] == "layout_unchecked"
    rows = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows").json()
    assert [r["row_number"] for r in rows["rows"]] == [2, 3, 4, 5] and rows["has_more"] is False
    held = [r for r in rows["rows"] if r["status"] == "held"]
    assert [(r["hold_reason"], r["reason_label"]) for r in held] == [("blank_qty", "Quantity missing"),
                                                                    ("blank_hsn", "HSN missing")]
    assert held[0]["values"]["Order Id"] == "O-2" and held[0]["file_name"] == "orders-1.csv"
    assert held[0]["needs_ca_check"] is False
    only = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held&limit=1").json()
    assert len(only["rows"]) == 1 and only["has_more"] is True
    assert get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=bogus").status_code == 422


def test_runs_are_visible_to_the_ca_and_nobody_else(shop):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    run_id = run_of(shop, upload_id)
    for path in (f"/runs/{run_id}", f"/runs/{run_id}/rows"):
        assert get(pg, f"/api/v1/b/{biz}{path}", sub="cathy").status_code == 200
        assert get(pg, f"/api/v1/b/{biz}{path}", sub="bill").status_code == 404
        assert get(pg, f"/api/v1/b/{biz}{path}", sub="stranger").status_code == 404


def test_another_business_cannot_read_a_run_by_its_id(shop):  # noqa: F811
    from .conftest import new_business

    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    run_id = run_of(shop, upload_id)
    other = new_business(pg, "olivia")
    for path in (f"/runs/{run_id}", f"/runs/{run_id}/rows"):
        assert get(pg, f"/api/v1/b/{other}{path}", sub="olivia").status_code == 404


@pytest.mark.parametrize("second", [csv("B-1,Shipment,1,6109,2.00", gstin="29AAAAA0000A1Z5"),
                                    (HEAD + ",B-1,Shipment,1,6109,2.00\n").encode()])  # wrong GSTIN, then none
def test_a_zip_with_one_bad_gstin_stages_nothing(shop, second):  # noqa: F811
    pg, _, _ = shop
    z = zipped(**{"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "orders-b.csv": second})
    upload_id, _ = upload(shop, "amazon", "month.zip", z, "application/zip")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert out["status"] == "rejected" and out["reject_reason"] in ("wrong_gstin", "gstin_missing")
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 0


def test_a_damaged_file_inside_a_zip_is_rejected_at_once(shop):  # noqa: F811
    pg, _, _ = shop
    z = bytearray(zipped(**{"orders-a.csv": csv(*[f"A-{i},Shipment,1,6109,1.00" for i in range(50)])}))
    z[45] ^= 0xFF  # a byte in the compressed data (stored uncompressed here, so the CRC no longer matches)
    upload_id, _ = upload(shop, "amazon", "month.zip", bytes(z), "application/zip")
    run_jobs(shop)
    assert state(shop, upload_id)["reject_reason"] in ("bad_zip", "unreadable_file")
    assert scalar(pg.owner, "select count(*) from imports.import_runs") == 0
