"""The parse job through to staged rows (R1-M3 slice 2) on PostgreSQL as app_rw, with a made-up
reader standing in for the platform readers. Made-up files; skipped unless PG_ADMIN_URL is set."""

import io
import itertools
import uuid
import zipfile

import pytest
from sqlalchemy import text

from app.modules.imports import readers, staging
from platform_common import jobs

from .conftest import PG_ADMIN_URL, scalar
from .fake_reader import TestReader
from .test_uploads_postgres import get, post, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

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
                             "invalid": 0, "held": 2, "skipped_zero": 1, "set_aside": 0, "accepted": 0, "fixed": 0}
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


# --- discard, sections, run ids, overlap between live files (R1-M3 slice 3) ---------------------

CLEAN = csv("C-1,Shipment,1,6109,10.00", "C-2,Shipment,2,6109,20.00")


def sections_of(shop, sub="alice"):  # noqa: F811
    pg, biz, _ = shop
    r = get(pg, f"/api/v1/b/{biz}/upload-sections", sub=sub)
    assert r.status_code == 200, r.text
    return {s["section"]: s for s in r.json()["sections"]}


def test_sections_always_list_all_five_with_one_of_four_statuses(shop):  # noqa: F811
    pg, biz, _ = shop
    s = sections_of(shop)
    assert list(s) == ["amazon", "flipkart", "meesho", "own_invoices_excel", "own_invoices_pdf"]
    assert {v["status"] for v in s.values()} == {"not uploaded"}
    assert [s[k]["enabled"] for k in s] == [True, True, True, True, False]
    upload(shop, "amazon", "orders-1.csv", CLEAN)
    assert sections_of(shop)["amazon"]["status"] == "processing"  # received, the job has not run
    run_jobs(shop)
    assert sections_of(shop)["amazon"]["status"] == "ready"
    upload(shop, "flipkart", "orders-2.csv", GOOD)
    run_jobs(shop)
    s = sections_of(shop)
    assert (s["flipkart"]["status"], s["flipkart"]["held_rows"], s["flipkart"]["needs_ca_check"]) == ("not uploaded", 0, False)
    # the test reader is registered for amazon only, so the flipkart file is rejected and doesn't count
    upload(shop, "amazon", "orders-3.csv", GOOD)
    run_jobs(shop)
    a = sections_of(shop)["amazon"]
    assert (a["status"], a["held_rows"]) == ("rows held", 2) and len(a["uploads"]) == 2
    assert a["uploads"][0]["run_ids"]


def test_sections_visible_to_the_ca_not_to_billing_or_strangers(shop):  # noqa: F811
    pg, biz, _ = shop
    assert sections_of(shop, "cathy")
    for sub in ("bill", "stranger"):
        assert get(pg, f"/api/v1/b/{biz}/upload-sections", sub=sub).status_code == 404


def test_discarding_a_run_frees_the_file_and_the_section(shop):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    run_id = run_of(shop, upload_id)
    assert post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard", sub="cathy").status_code == 404
    assert post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard", sub="bill").status_code == 404
    done = post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard")
    assert done.status_code == 200 and done.json()["status"] == "discarded"
    assert post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard").json()["status"] == "discarded"  # repeating is fine
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.run_discarded'") == 1
    assert sections_of(shop)["amazon"]["status"] == "not uploaded"
    again, _ = upload(shop, "amazon", "orders-1.csv", GOOD)  # the same file can come back
    run_jobs(shop)
    assert run_of(shop, again) != run_id and sections_of(shop)["amazon"]["status"] == "rows held"


def test_a_used_run_cannot_be_discarded_and_another_business_cannot_try(shop):  # noqa: F811
    from .conftest import new_business

    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", CLEAN)
    run_jobs(shop)
    run_id = run_of(shop, upload_id)
    other = new_business(pg, "olivia")
    assert post(pg, f"/api/v1/b/{other}/runs/{run_id}/discard", sub="olivia").status_code == 404
    with pg.owner.connect() as c:
        c.execute(text("update imports.import_runs set status = 'confirmed', confirmed_by = uploaded_by,"
                       " confirmed_at = now()"))
    r = post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard")
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_not_staged"


def test_a_second_file_with_the_same_records_shows_them_as_duplicates(shop):  # noqa: F811
    pg, biz, _ = shop
    first, _ = upload(shop, "amazon", "orders-1.csv", csv("D-1,Shipment,1,6109,10.00", "D-2,Shipment,1,6109,20.00"))
    second, _ = upload(shop, "amazon", "orders-2.csv", csv("D-2,Shipment,1,6109,20.00", "D-3,Shipment,1,6109,30.00"))
    run_jobs(shop)
    run = get(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, second)}").json()
    assert (run["counts"]["new"], run["counts"]["duplicate"]) == (1, 1)
    rows = get(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, second)}/rows?status=duplicate").json()["rows"]
    assert rows[0]["values"]["Order Id"] == "D-2" and rows[0]["errors"][0]["code"] == "duplicate_in_other_file"
    # the first file is untouched, and discarding it frees the records for the second to be staged again
    assert get(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, first)}").json()["counts"]["new"] == 2
    post(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, first)}/discard")
    post(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, second)}/discard")
    third, _ = upload(shop, "amazon", "orders-2.csv", csv("D-2,Shipment,1,6109,20.00", "D-3,Shipment,1,6109,30.00"))
    run_jobs(shop)
    assert get(pg, f"/api/v1/b/{biz}/runs/{run_of(shop, third)}").json()["counts"]["new"] == 2


def test_a_zip_lists_every_run_it_made(shop):  # noqa: F811
    pg, biz, _ = shop
    z = zipped(**{"orders-a.csv": csv("A-1,Shipment,1,6109,1.00"), "orders-b.csv": csv("B-1,Shipment,1,6109,2.00")})
    upload_id, _ = upload(shop, "amazon", "month.zip", z, "application/zip")
    run_jobs(shop)
    out = state(shop, upload_id)
    assert len(out["run_ids"]) == 2 and out["run_id"] == out["run_ids"][0]
    assert {get(pg, f"/api/v1/b/{biz}/runs/{r}").json()["upload_id"] for r in out["run_ids"]} == {upload_id}


def test_discarding_only_the_first_file_makes_the_second_stale_at_confirm(shop):  # noqa: F811
    from app.modules.imports import staging

    pg, biz, _ = shop
    first, _ = upload(shop, "amazon", "orders-1.csv", csv("D-1,Shipment,1,6109,10.00", "D-2,Shipment,1,6109,20.00"))
    second, _ = upload(shop, "amazon", "orders-2.csv", csv("D-2,Shipment,1,6109,20.00", "D-3,Shipment,1,6109,30.00"))
    run_jobs(shop)
    first_run, second_run = run_of(shop, first), run_of(shop, second)
    post(pg, f"/api/v1/b/{biz}/runs/{first_run}/discard")  # only the first
    from sqlalchemy.orm import Session

    with Session(pg.owner) as s:  # confirm is not exposed yet; call the service as the table owner would
        s.execute(text("select set_config('app.tenant_id', :b, false)"), {"b": str(biz)})
        with pytest.raises(staging.StaleRun):
            staging.confirm(s, business_id=biz, run_id=uuid.UUID(second_run), user_id=uuid.uuid4())
        s.rollback()


def test_an_overlap_with_a_file_that_is_still_live_is_not_stale(shop):  # noqa: F811
    from sqlalchemy.orm import Session

    from app.modules.imports import staging

    pg, biz, _ = shop
    upload(shop, "amazon", "orders-1.csv", csv("D-1,Shipment,1,6109,10.00", "D-2,Shipment,1,6109,20.00"))
    second, _ = upload(shop, "amazon", "orders-2.csv", csv("D-2,Shipment,1,6109,20.00", "D-3,Shipment,1,6109,30.00"))
    run_jobs(shop)
    with Session(pg.owner) as s:
        run = staging.confirm(s, business_id=biz, run_id=uuid.UUID(run_of(shop, second)), user_id=uuid.uuid4())
        assert run.status.value == "confirmed"
        s.rollback()
# --- resolving held rows (R1-M3 slice 4) -------------------------------------------------------


def held_rows(shop, run_id, sub="alice"):  # noqa: F811
    pg, biz, _ = shop
    return get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows?status=held", sub=sub).json()["rows"]


def resolve(shop, row_id, action, note, sub="alice", key=None):  # noqa: F811
    pg, biz, _ = shop
    return post(pg, f"/api/v1/b/{biz}/rows/{row_id}/resolve", {"action": action, "note": note}, sub=sub,
                key=key or uuid.uuid4().hex)


def staged(shop):  # noqa: F811
    upload_id, _ = upload(shop, "amazon", "orders-1.csv", GOOD)
    run_jobs(shop)
    return run_of(shop, upload_id)


def test_a_held_row_offers_set_aside_with_wording_from_refdata(shop):  # noqa: F811
    run_id = staged(shop)
    row = held_rows(shop, run_id)[0]
    assert [(a["action"], a["label"]) for a in row["allowed_actions"]] == [("set_aside", "Leave this row out")]
    assert "left out of the return" in row["allowed_actions"][0]["effect_note"] and row["resolution"] is None


def test_setting_a_row_aside_keeps_the_note_clears_the_hold_and_is_audited(shop):  # noqa: F811
    pg, biz, _ = shop
    run_id = staged(shop)
    row = held_rows(shop, run_id)[0]
    done = resolve(shop, row["row_id"], "set_aside", "  Not our sale  ")
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["resolution"]["action"] == "set_aside" and out["resolution"]["note"] == "Not our sale"
    assert out["allowed_actions"] == [] and out["status"] == "held"  # the row itself is never edited
    run = get(pg, f"/api/v1/b/{biz}/runs/{run_id}").json()
    assert run["counts"]["held"] == 1 and run["counts"]["set_aside"] == 1 and sum(run["held_by_reason"].values()) == 1
    s = sections_of(shop)["amazon"]
    assert (s["status"], s["held_rows"]) == ("rows held", 1)
    other = [r for r in held_rows(shop, run_id) if r["row_id"] != row["row_id"]][0]
    resolve(shop, other["row_id"], "set_aside", "Also not ours")
    assert sections_of(shop)["amazon"]["status"] == "ready"
    audit = pg.owner.connect().execute(text(
        "select reason, data from platform.audit_log where action = 'imports.row_set_aside' order by id")).all()
    assert [a.reason for a in audit] == ["Not our sale", "Also not ours"]
    assert set(audit[0].data) == {"run_id", "row_id", "hold_reason"}
    assert scalar(pg.owner, "select count(*) from imports.import_rows") == 4  # rows untouched


def test_a_decision_needs_a_note_and_a_row_the_user_can_act_on(shop):  # noqa: F811
    pg, biz, _ = shop
    run_id = staged(shop)
    rows = get(pg, f"/api/v1/b/{biz}/runs/{run_id}/rows").json()["rows"]
    held = next(r for r in rows if r["status"] == "held")
    new = next(r for r in rows if r["status"] == "new")
    assert resolve(shop, held["row_id"], "set_aside", "   ").json()["error"]["code"] == "note_required"
    assert resolve(shop, held["row_id"], "set_aside", "x" * 501).status_code == 422
    assert resolve(shop, held["row_id"], "accept", "Fine").json()["error"]["code"] == "action_not_allowed"  # switch is off
    assert resolve(shop, held["row_id"], "bogus", "Fine").status_code == 422
    assert resolve(shop, new["row_id"], "set_aside", "Fine").json()["error"]["code"] == "action_not_allowed"
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 0


def test_deciding_twice_is_safe_and_a_decision_cannot_be_swapped(shop):  # noqa: F811
    pg, _, _ = shop
    row = held_rows(shop, staged(shop))[0]
    assert resolve(shop, row["row_id"], "set_aside", "Once", key="k-1").status_code == 200
    assert resolve(shop, row["row_id"], "set_aside", "Once", key="k-1").status_code == 200  # same key
    assert resolve(shop, row["row_id"], "set_aside", "Once again").status_code == 200  # same decision, no new row
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 1
    assert resolve(shop, row["row_id"], "accept", "Changed my mind").status_code == 422


def _decided_meanwhile(shop, row_id, kind, monkeypatch):  # noqa: F811
    """Another request decides the row after this one read it as undecided and before it inserts:
    on the first allowed_actions call (made while reading the row) a second session commits the
    competing decision. (The app's engine holds one connection, so two in-process requests
    cannot overlap; the other request is played by the owner's connection.)"""
    from app.modules.imports import runs

    pg, biz, _ = shop
    real, calls = runs.allowed_actions, itertools.count()

    def waiting(*a, **k):
        result = real(*a, **k)
        if next(calls) == 0:
            with pg.owner.begin() as c:
                c.execute(text("insert into imports.row_resolutions (id, business_id, row_id, kind, note, created_by)"
                               " values (:i, :b, :r, :k, 'Other request', :u)"),
                          {"i": uuid.uuid4(), "b": biz, "r": row_id, "k": kind, "u": uuid.uuid4()})
        return result

    monkeypatch.setattr(runs, "allowed_actions", waiting)


def test_a_decision_that_lands_between_the_read_and_the_insert_is_not_doubled(shop, monkeypatch):  # noqa: F811
    from app.modules.refdata.reader import _reset_cache

    pg, _, _ = shop
    run_id = staged(shop)
    with pg.owner.connect() as c:
        c.execute(text("update refdata.values set value = 'true' where key like 'imports.held.blank\\_%.accept_allowed'"))
    _reset_cache()
    try:
        rows = {r["hold_reason"]: r for r in held_rows(shop, run_id)}
        # The same decision twice is one decision: this request answers as the code path does for a decided row.
        _decided_meanwhile(shop, rows["blank_hsn"]["row_id"], "set_aside", monkeypatch)
        done = resolve(shop, rows["blank_hsn"]["row_id"], "set_aside", "Mine")
        assert done.status_code == 200 and done.json()["resolution"]["action"] == "set_aside"
        assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 1
        assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.row_set_aside'") == 0
        # A different decision loses, with the same 422 as the code path.
        monkeypatch.undo()
        _decided_meanwhile(shop, rows["blank_qty"]["row_id"], "accepted", monkeypatch)
        lost = resolve(shop, rows["blank_qty"]["row_id"], "set_aside", "Mine")
        assert lost.status_code == 422 and lost.json()["error"]["code"] == "action_not_allowed"
        assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 2
        assert scalar(pg.owner, "select kind from imports.row_resolutions where row_id = :r",
                      r=rows["blank_qty"]["row_id"]) == "accepted"
    finally:
        _reset_cache()


def test_two_sessions_inserting_a_decision_at_once_leave_one(shop):  # noqa: F811
    """The second insert waits for the first to commit, then inserts nothing."""
    import threading

    pg, biz, _ = shop
    row = held_rows(shop, staged(shop))[0]
    sql = text("insert into imports.row_resolutions (id, business_id, row_id, kind, note, created_by)"
               " values (:i, :b, :r, 'set_aside', 'x', :u) on conflict (row_id) do nothing returning id")

    def args():
        return {"i": uuid.uuid4(), "b": biz, "r": row["row_id"], "u": uuid.uuid4()}

    out = []
    with pg.owner.connect().execution_options(isolation_level="READ COMMITTED") as first:  # the engine autocommits
        first.execute(sql, args())  # not committed yet
        other = threading.Thread(target=lambda: out.append(_second(pg, sql, args())))
        other.start()
        other.join(timeout=1)
        assert other.is_alive()  # waiting on the first session's row
        first.commit()
    other.join(timeout=10)
    assert out == [None]
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 1


def _second(pg, sql, params):
    with pg.owner.connect().execution_options(isolation_level="READ COMMITTED") as c:
        found = c.execute(sql, params).first()
        c.commit()
        return found


def test_the_database_itself_refuses_a_second_decision_on_a_row(shop):  # noqa: F811
    pg, biz, _ = shop
    row = held_rows(shop, staged(shop))[0]
    resolve(shop, row["row_id"], "set_aside", "Once")
    with pg.owner.connect() as c:
        with pytest.raises(Exception, match="row_resolutions_one_per_row"):
            c.execute(text(
                "insert into imports.row_resolutions (id, business_id, row_id, kind, note, created_by)"
                " select gen_random_uuid(), business_id, row_id, 'accepted', 'again', created_by"
                " from imports.row_resolutions"))


def test_accept_is_offered_only_when_refdata_allows_it(shop):  # noqa: F811
    from app.modules.refdata.reader import _reset_cache

    pg, _, _ = shop
    run_id = staged(shop)
    with pg.owner.connect() as c:
        c.execute(text("update refdata.values set value = 'true' where key = 'imports.held.blank_qty.accept_allowed'"))
    _reset_cache()
    try:
        rows = {r["hold_reason"]: r for r in held_rows(shop, run_id)}
        assert [a["action"] for a in rows["blank_qty"]["allowed_actions"]] == ["set_aside", "accept"]
        assert [a["action"] for a in rows["blank_hsn"]["allowed_actions"]] == ["set_aside", "enter_hsn"]  # accept stays off; the fix is offered
        done = resolve(shop, rows["blank_qty"]["row_id"], "accept", "Quantity is one, I checked the invoice")
        assert done.json()["resolution"]["action"] == "accept"
        assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.row_accepted'") == 1
        run = get(pg, f"/api/v1/b/{shop[1]}/runs/{run_id}").json()
        assert run["counts"]["accepted"] == 1 and run["counts"]["held"] == 1
    finally:
        _reset_cache()


def test_only_owner_and_admin_decide_and_only_in_their_own_business(shop):  # noqa: F811
    from .conftest import new_business

    pg, biz, _ = shop
    row = held_rows(shop, staged(shop))[0]
    for sub in ("cathy", "bill", "stranger"):
        assert resolve(shop, row["row_id"], "set_aside", "Nope", sub=sub).status_code == 404
    other = new_business(pg, "olivia")
    r = post(pg, f"/api/v1/b/{other}/rows/{row['row_id']}/resolve", {"action": "set_aside", "note": "Nope"}, sub="olivia",
             key="k-o")
    assert r.status_code == 404
    assert resolve(shop, row["row_id"], "set_aside", "Mine", sub="adam").status_code == 200  # an admin may
    assert {r["resolution"]["action"] for r in held_rows(shop, row["run_id"], sub="cathy") if r["resolution"]} == {"set_aside"}
    assert scalar(pg.owner, "select count(*) from imports.row_resolutions") == 1


def test_a_discarded_runs_rows_cannot_be_decided(shop):  # noqa: F811
    pg, biz, _ = shop
    run_id = staged(shop)
    row = held_rows(shop, run_id)[0]
    post(pg, f"/api/v1/b/{biz}/runs/{run_id}/discard")
    r = resolve(shop, row["row_id"], "set_aside", "Late")
    assert r.status_code == 409 and r.json()["error"]["code"] == "run_not_staged"


def test_resolutions_cannot_be_changed_or_deleted_by_the_app_role(shop):  # noqa: F811
    pg, _, _ = shop
    row = held_rows(shop, staged(shop))[0]
    resolve(shop, row["row_id"], "set_aside", "Once")
    with pg.app_rw.connect() as c:
        for sql in ("update imports.row_resolutions set note = 'x'", "delete from imports.row_resolutions"):
            with pytest.raises(Exception, match="permission denied"):
                c.execute(text(sql))
            c.rollback()
