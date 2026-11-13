"""Upload routes and the parse job (LLD-7 §3, §8; R1-M3 slice 1) on PostgreSQL as app_rw.

Made-up files. Skipped unless PG_ADMIN_URL points at a disposable server. These cover the
upload lifecycle up to the point a reader would stage rows: with no reader registered a
platform file is rejected in plain words, and a PDF is stored.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app import api as app_api
from platform_common import jobs
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

CSV = b"Seller Gstin,Invoice Number\n19AAAAA0000A1Z5,INV-1\n"
PDF = b"%PDF-1.7\nmade-up invoice\n"


@pytest.fixture()
def shop(pg, tmp_path):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 13, 12, tzinfo=IST))
    queue = FakeQueue()
    set_queue(queue)
    set_store(LocalObjectStore(tmp_path))
    biz = new_business(pg, "alice")
    for sub, role in (("adam", "admin"), ("cathy", "ca"), ("bill", "billing")):
        seed_member(pg, biz, sub, role)
    try:
        yield pg, biz, queue
    finally:
        set_queue(None)
        set_store(None)


def post(pg, path, body=None, sub="alice", key=None):
    return pg.client.post(path, json=body, headers={**as_user(sub), **({"Idempotency-Key": key} if key else {})})


def get(pg, path, sub="alice"):
    return pg.client.get(path, headers=as_user(sub))


def start(shop, section, name, content, sub="alice"):
    pg, biz, _ = shop
    return post(pg, f"/api/v1/b/{biz}/uploads", {"section": section, "file_name": name, "size_bytes": len(content)},
                sub=sub, key=uuid.uuid4().hex)


def send(shop, started, name, content, ctype="text/csv"):
    up = started.json()["upload"]
    return shop[0].client.post(up["url"], data=up["fields"], files={"file": (name, content, ctype)})


def upload(shop, section, name, content, ctype="text/csv", sub="alice"):
    """Start, post the file, complete. Returns (upload_id, job_id)."""
    pg, biz, _ = shop
    started = start(shop, section, name, content, sub=sub)
    assert started.status_code == 201, started.text
    assert send(shop, started, name, content, ctype).status_code == 204
    done = post(pg, f"/api/v1/b/{biz}/uploads/{started.json()['upload_id']}/complete", sub=sub)
    assert done.status_code == 202, done.text
    return started.json()["upload_id"], done.json()["job_id"]


def run_jobs(shop):
    return shop[2].drain(jobs.handle_message)


def test_a_platform_file_with_no_reader_is_rejected_in_plain_words(shop):
    pg, biz, _ = shop
    upload_id, job_id = upload(shop, "amazon", "MTR_B2C.csv", CSV)
    assert get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()["status"] == "received"  # nothing read before the job
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["reject_reason"]) == ("rejected", "no_reader")
    assert "can't read" in out["reject_message"] and out["raw_available"] is True
    assert get(pg, f"/api/v1/b/{biz}/jobs/{job_id}").json()["status"] == "done"
    assert scalar(pg.owner, "select checksum_sha256 from imports.uploads where id = :u", u=upload_id)
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.rejected'") == 1


def test_a_pdf_is_stored_and_marked_read_with_no_rows(shop):
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "own_invoices_pdf", "inv.pdf", PDF, "application/pdf")
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["run_id"]) == ("stored", None)


def test_a_file_that_is_not_a_pdf_is_rejected(shop):
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "own_invoices_pdf", "inv.pdf", b"not a pdf at all", "application/pdf")
    run_jobs(shop)
    assert get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()["reject_reason"] == "not_a_pdf"


def test_the_same_complete_twice_is_one_job(shop):
    pg, biz, _ = shop
    upload_id, job_id = upload(shop, "meesho", "m.zip", b"PK\x03\x04", "application/zip")
    again = post(pg, f"/api/v1/b/{biz}/uploads/{upload_id}/complete")
    assert again.status_code == 202 and again.json()["job_id"] == job_id
    assert len(run_jobs(shop)) == 1


def test_start_is_idempotent_by_key(shop):
    pg, biz, _ = shop
    body = {"section": "flipkart", "file_name": "s.xlsx", "size_bytes": 10}
    one = post(pg, f"/api/v1/b/{biz}/uploads", body, key="k-1")
    two = post(pg, f"/api/v1/b/{biz}/uploads", body, key="k-1")
    assert one.status_code == two.status_code == 201 and one.json()["upload_id"] == two.json()["upload_id"]
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 1


@pytest.mark.parametrize(
    ("section", "name", "size", "code"),
    [
        ("amazon", "x.pdf", 10, "file_type_not_allowed"),
        ("own_invoices_pdf", "x.csv", 10, "file_type_not_allowed"),
        ("own_invoices_excel", "x.zip", 10, "file_type_not_allowed"),
        ("amazon", "x.xls", 10, "file_type_not_allowed"),
        ("amazon", "x.csv", 20 * 1024 * 1024 + 1, "file_too_large"),
        ("amazon", "x.csv", 0, "file_too_large"),
    ],
)
def test_wrong_type_or_size_is_refused_at_start(shop, section, name, size, code):
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/uploads", {"section": section, "file_name": name, "size_bytes": size}, key="k")
    assert r.status_code == 422 and r.json()["error"]["code"] == code
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 0


def test_an_unknown_section_is_refused(shop):
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/uploads", {"section": "ebay", "file_name": "x.csv", "size_bytes": 5}, key="k")
    assert r.status_code == 422


def test_complete_before_the_file_arrives_is_refused_and_can_be_retried(shop):
    pg, biz, _ = shop
    started = start(shop, "amazon", "a.csv", CSV)
    upload_id = started.json()["upload_id"]
    early = post(pg, f"/api/v1/b/{biz}/uploads/{upload_id}/complete")
    assert (early.status_code, early.json()["error"]["code"]) == (409, "upload_not_received")
    send(shop, started, "a.csv", CSV)
    assert post(pg, f"/api/v1/b/{biz}/uploads/{upload_id}/complete").status_code == 202


def test_a_file_swapped_after_complete_is_not_read_as_the_checked_one(shop):  # H-4 window
    pg, biz, _ = shop
    started = start(shop, "amazon", "a.csv", CSV)
    send(shop, started, "a.csv", CSV)
    post(pg, f"/api/v1/b/{biz}/uploads/{started.json()['upload_id']}/complete")
    assert send(shop, started, "a.csv", CSV[:-5]).status_code == 204  # smaller: within the POST cap and window
    run_jobs(shop)
    out = get(pg, f"/api/v1/b/{biz}/uploads/{started.json()['upload_id']}").json()
    assert out["reject_reason"] == "upload_changed"


def test_the_presigned_post_takes_only_this_uploads_key_and_size(shop):  # H-4
    pg, biz, _ = shop
    started = start(shop, "amazon", "a.csv", CSV)
    up = started.json()["upload"]
    assert up["fields"]["key"].startswith(f"uploads/b/{biz}/")
    too_big = pg.client.post(up["url"], data=up["fields"], files={"file": ("a.csv", b"x" * (len(CSV) + 1), "text/csv")})
    assert too_big.status_code == 403


def test_the_list_filters_by_section_and_pages(shop):
    pg, biz, _ = shop
    for section, name in (("amazon", "a.csv"), ("flipkart", "f.csv"), ("amazon", "b.csv")):
        assert start(shop, section, name, CSV).status_code == 201
    everything = get(pg, f"/api/v1/b/{biz}/uploads").json()
    assert [u["file_name"] for u in everything["uploads"]] == ["b.csv", "f.csv", "a.csv"]
    only = get(pg, f"/api/v1/b/{biz}/uploads?section=amazon").json()["uploads"]
    assert [u["file_name"] for u in only] == ["b.csv", "a.csv"]
    page = get(pg, f"/api/v1/b/{biz}/uploads?limit=1").json()
    assert len(page["uploads"]) == 1 and page["has_more"] is True


# --- who may do what (EM, 2026-11-13: owner and admin upload; the CA views; AC-roles) ---


def test_owner_and_admin_upload_the_ca_views_billing_sees_nothing(shop):
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "a.csv", CSV, sub="adam")  # an admin
    for sub, code in (("alice", 200), ("adam", 200), ("cathy", 200), ("bill", 404)):
        assert get(pg, f"/api/v1/b/{biz}/uploads", sub=sub).status_code == code
        assert get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}", sub=sub).status_code == code
    for sub in ("cathy", "bill"):  # the CA and billing cannot upload
        r = post(pg, f"/api/v1/b/{biz}/uploads", {"section": "amazon", "file_name": "a.csv", "size_bytes": 5}, sub=sub,
                 key=uuid.uuid4().hex)
        assert r.status_code == 404
        assert post(pg, f"/api/v1/b/{biz}/uploads/{upload_id}/complete", sub=sub).status_code == 404


def test_another_business_gets_404_on_every_route(shop):
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "a.csv", CSV)
    other = new_business(pg, "bob")
    assert get(pg, f"/api/v1/b/{other}/uploads/{upload_id}", sub="bob").status_code == 404
    assert post(pg, f"/api/v1/b/{other}/uploads/{upload_id}/complete", sub="bob").status_code == 404
    assert get(pg, f"/api/v1/b/{other}/uploads", sub="bob").json()["uploads"] == []
    assert get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}", sub="bob").status_code == 404  # not a member of biz


def test_the_job_refuses_when_the_user_lost_the_permission(shop):
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "amazon", "a.csv", CSV, sub="adam")
    with pg.owner.connect() as c:
        c.execute(text("update identity.memberships set role = 'billing' where user_sub = 'adam'"))
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["reject_reason"]) == ("rejected", "not_allowed")


def test_a_read_error_settles_the_upload_as_rejected(shop, monkeypatch):
    from app.modules.imports import uploads as up_mod
    from platform_common.errors import AppError

    pg, biz, _ = shop
    upload_id, job_id = upload(shop, "amazon", "a.csv", CSV)

    def boom(uow, upload_id):
        raise AppError("storage_error", "cannot read the object")

    monkeypatch.setattr(up_mod, "process", boom)
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["reject_reason"]) == ("rejected", "read_failed")
    assert "couldn't read" in out["reject_message"]


def test_an_unexpected_error_retries_then_settles_on_the_last_attempt(shop, monkeypatch):
    from app.modules.imports import uploads as up_mod

    pg, biz, _ = shop
    upload_id, job_id = upload(shop, "amazon", "a.csv", CSV)

    def boom(uow, upload_id):
        raise RuntimeError("bug")

    monkeypatch.setattr(up_mod, "process", boom)
    assert run_jobs(shop) == ["retry"]  # attempt 1 of MAX_ATTEMPTS: rolled back, still received
    assert get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()["status"] == "received"
    monkeypatch.setattr(jobs, "MAX_ATTEMPTS", 2)
    assert jobs.run(uuid.UUID(str(job_id))) == "done"  # the redelivery is the last attempt
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["reject_reason"]) == ("rejected", "read_failed")


def test_uploads_cannot_be_deleted_or_widened_by_the_app_role(shop):
    pg, biz, _ = shop
    upload(shop, "amazon", "a.csv", CSV)
    with pg.app_rw.connect() as c, c.begin():
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(biz)})
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("delete from imports.uploads"))
    with pg.app_rw.connect() as c, c.begin():
        c.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(biz)})
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("update imports.uploads set file_name = 'other.csv'"))
