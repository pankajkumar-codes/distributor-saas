"""The product import's routes and jobs (LLD-3 §6.3, S3-c2) on PostgreSQL as app_rw: upload
on the presigned POST, parse job, preview, confirm, apply job, discard, and isolation.
The files are made up. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid
from datetime import datetime

import pytest

from app import api as app_api
from platform_common import jobs
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, as_user, new_business, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

HEADER = "code,name,hsn,unit,sale_rate,gst_rate,gst_rate_valid_from,barcode,tax_category,has_cess"
SOAP = "SOAP-1,Neem soap 100 g,3401,PCS,45.50,18,01-04-2026,8901234567890,taxable,no"
OIL = "OIL-1,Coconut oil 500 ml,1513,BTL,120,5,2026-04-01,,taxable,"


def csv_file(*lines: str) -> bytes:
    return ("\n".join((HEADER, *lines)) + "\n").encode()


@pytest.fixture()
def shop(pg, tmp_path):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    queue = FakeQueue()
    set_queue(queue)
    set_store(LocalObjectStore(tmp_path))
    try:
        yield pg, new_business(pg, "alice"), queue
    finally:
        set_queue(None)
        set_store(None)


def post(pg, path, body=None, sub="alice", key=None):
    headers = {**as_user(sub), **({"Idempotency-Key": key} if key else {})}
    return pg.client.post(path, json=body, headers=headers)


def upload(shop, content: bytes, name="products.csv"):
    """Start, upload on the presigned POST, complete: the parse job is queued."""
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": name, "size_bytes": len(content)},
             key=uuid.uuid4().hex)
    assert r.status_code == 201, r.text
    started = r.json()
    up = started["upload"]
    sent = pg.client.post(up["url"], data=up["fields"], files={"file": (name, content, "text/csv")})
    assert sent.status_code == 204, sent.text
    done = post(pg, f"/api/v1/b/{biz}/product-imports/{started['import_id']}/complete")
    assert done.status_code == 202, done.text
    return started["import_id"], done.json()["job_id"]


def run_jobs(shop) -> list:
    return shop[2].drain(jobs.handle_message)


def get(shop, import_id, query=""):
    pg, biz, _ = shop
    return pg.client.get(f"/api/v1/b/{biz}/product-imports/{import_id}{query}", headers=as_user("alice"))


def test_upload_preview_confirm_apply_through_the_routes(shop):  # AC3-13, AC3-14
    pg, biz, _ = shop
    import_id, job_id = upload(shop, csv_file(SOAP, OIL, "BAD-1,,,PCS,1,,,,taxable,"))
    assert get(shop, import_id).json()["status"] == "awaiting_upload"  # nothing read before the job
    assert run_jobs(shop) == ["done"]
    job = pg.client.get(f"/api/v1/b/{biz}/jobs/{job_id}", headers=as_user("alice")).json()
    assert job["status"] == "done" and job["result"]["status"] == "preview"

    preview = get(shop, import_id).json()
    assert (preview["status"], preview["counts"]["new"], preview["counts"]["invalid"]) == ("preview", 2, 1)
    assert [r["row_number"] for r in preview["rows"]] == [2, 3, 4]
    bad = get(shop, import_id, "?rows=invalid").json()["rows"]
    assert [r["row_number"] for r in bad] == [4] and {e["field"] for e in bad[0]["errors"]} >= {"name"}
    page = get(shop, import_id, "?limit=1").json()
    assert len(page["rows"]) == 1 and page["has_more"] is True

    url = f"/api/v1/b/{biz}/product-imports/{import_id}/confirm"
    first = post(pg, url, {"apply_changes": True})
    again = post(pg, url, {"apply_changes": True})  # a double click: the same job
    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    assert post(pg, url, {"apply_changes": False}).json()["error"]["code"] == "import_already_applied"
    assert run_jobs(shop) == ["done"]
    applied = get(shop, import_id).json()
    assert applied["status"] == "applied" and applied["counts"]["applied"] == 2
    codes = {p["code"] for p in pg.client.get(f"/api/v1/b/{biz}/products", headers=as_user("alice")).json()["items"]}
    assert codes == {"SOAP-1", "OIL-1"}
    assert post(pg, url, {"apply_changes": True}).json()["error"]["code"] == "import_already_applied"


def test_complete_before_the_file_arrives_is_refused_and_can_be_retried(shop):
    pg, biz, _ = shop
    content = csv_file(SOAP)
    r = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": "p.csv", "size_bytes": len(content)},
             key=uuid.uuid4().hex)
    import_id, up = r.json()["import_id"], r.json()["upload"]
    early = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/complete")
    assert (early.status_code, early.json()["error"]["code"]) == (409, "upload_missing")
    pg.client.post(up["url"], data=up["fields"], files={"file": ("p.csv", content, "text/csv")})
    one = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/complete").json()
    two = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/complete").json()
    assert one == two  # one parse job however often the client completes
    assert run_jobs(shop) == ["done"]


def test_the_presigned_post_takes_only_this_runs_key_and_size(shop):  # H-4
    pg, biz, _ = shop
    r = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": "p.csv", "size_bytes": 10}, key=uuid.uuid4().hex)
    up = r.json()["upload"]
    assert up["fields"]["key"].startswith(f"uploads/b/{biz}/")
    too_big = pg.client.post(up["url"], data=up["fields"], files={"file": ("p.csv", b"x" * 2097153, "text/csv")})
    assert too_big.status_code == 403
    huge = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": "p.csv", "size_bytes": 2097153},
                key=uuid.uuid4().hex)
    assert huge.json()["error"]["code"] == "file_too_large"


def test_a_file_the_reader_refuses_fails_the_run_not_the_job_runner(shop):
    import_id, _ = upload(shop, b"\xff\xfe not utf-8")
    assert run_jobs(shop) == ["done"]  # the run records the failure; nothing to retry
    out = get(shop, import_id).json()
    assert (out["status"], out["error_code"]) == ("failed", "file_rejected")


def test_discard_ends_a_preview_and_nothing_is_saved(shop):
    pg, biz, _ = shop
    import_id, _ = upload(shop, csv_file(SOAP))
    run_jobs(shop)
    r = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/discard")
    assert r.status_code == 200 and r.json()["status"] == "discarded"
    assert post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/discard").json()["status"] == "discarded"
    refused = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/confirm", {"apply_changes": True})
    assert refused.json()["error"]["code"] == "import_not_ready"
    assert pg.client.get(f"/api/v1/b/{biz}/products", headers=as_user("alice")).json()["items"] == []


def test_a_confirmed_import_cant_be_discarded(shop):
    pg, biz, _ = shop
    import_id, _ = upload(shop, csv_file(SOAP))
    run_jobs(shop)
    post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/confirm", {"apply_changes": False})
    r = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/discard")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "import_not_discardable")


def test_permissions_and_another_business(shop):  # AC3-7
    pg, biz, _ = shop
    import_id, _ = upload(shop, csv_file(SOAP))
    run_jobs(shop)
    seed_member(pg, biz, "cara", "ca")
    assert pg.client.get(f"/api/v1/b/{biz}/product-imports/{import_id}", headers=as_user("cara")).status_code == 200
    refused = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/confirm", {"apply_changes": True}, sub="cara")
    assert refused.status_code == 404  # a role without catalog.edit gets the unknown-ID answer (AC3-6)
    other = new_business(pg, "bob")
    for path in ("", "/complete", "/confirm", "/discard"):
        url = f"/api/v1/b/{other}/product-imports/{import_id}{path}"
        r = (pg.client.get(url, headers=as_user("bob")) if not path
             else post(pg, url, {"apply_changes": True} if path == "/confirm" else None, sub="bob"))
        assert r.status_code == 404, (path, r.text)
    assert get(shop, "not-a-uuid").status_code == 404


def test_only_csv_or_xlsx_and_the_upload_must_keep_its_type_and_size(shop):  # H-4, #69 review
    pg, biz, _ = shop
    pdf = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": "p.pdf", "size_bytes": 10}, key=uuid.uuid4().hex)
    assert (pdf.status_code, pdf.json()["error"]["code"]) == (422, "file_type_unsupported")
    content = csv_file(SOAP)
    r = post(pg, f"/api/v1/b/{biz}/product-imports", {"file_name": "p.csv", "size_bytes": len(content) + 1},
             key=uuid.uuid4().hex)
    import_id, up = r.json()["import_id"], r.json()["upload"]
    assert up["fields"]["Content-Type"] == "text/csv"
    other_type = pg.client.post(up["url"], data={**up["fields"], "Content-Type": "text/html"},
                                files={"file": ("p.csv", content, "text/html")})
    assert (other_type.status_code, other_type.text) == (403, "content_type")
    pg.client.post(up["url"], data=up["fields"], files={"file": ("p.csv", content, "text/csv")})
    short = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/complete")  # declared one byte more
    assert (short.status_code, short.json()["error"]["code"]) == (409, "upload_size_mismatch")


def test_an_apply_that_cant_finish_ends_the_run_failed_not_stuck(shop, monkeypatch):  # #69 review
    from platform_common.errors import Conflict

    from .. import import_jobs

    pg, biz, _ = shop
    import_id, _ = upload(shop, csv_file(SOAP))
    run_jobs(shop)

    def refuse(*args, **kwargs):
        raise Conflict("import_not_ready", "refused for the test")

    monkeypatch.setattr(import_jobs.imp, "apply", refuse)
    job_id = post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/confirm", {"apply_changes": True}).json()["job_id"]
    assert run_jobs(shop) == ["done"]
    job = pg.client.get(f"/api/v1/b/{biz}/jobs/{job_id}", headers=as_user("alice")).json()
    assert job["result"]["status"] == "failed"
    out = get(shop, import_id).json()
    assert (out["status"], out["error_code"]) == ("failed", "import_not_ready")
    assert post(pg, f"/api/v1/b/{biz}/product-imports/{import_id}/discard").json()["status"] == "failed"
    assert pg.client.get(f"/api/v1/b/{biz}/products", headers=as_user("alice")).json()["items"] == []


def test_a_confirmed_run_superseded_before_its_apply_ends_without_saving(shop):  # #69 review
    """Run A is confirmed but its job hasn't run; the same file is uploaded again (B), which
    supersedes A. A's apply job then refuses (A is no longer a preview) and saves nothing;
    B can still be confirmed and applied once."""
    pg, biz, _ = shop
    content = csv_file(SOAP)
    a, _ = upload(shop, content)
    run_jobs(shop)
    post(pg, f"/api/v1/b/{biz}/product-imports/{a}/confirm", {"apply_changes": True})
    b, _ = upload(shop, content)
    shop[2].sent.reverse()  # B's parse runs before A's apply (SQS gives no order)
    assert run_jobs(shop) == ["done", "failed"]  # B's parse supersedes A; A's apply is refused
    assert (get(shop, a).json()["status"], get(shop, a).json()["superseded_by"]) == ("discarded", b)
    assert post(pg, f"/api/v1/b/{biz}/product-imports/{a}/discard").json()["status"] == "discarded"
    post(pg, f"/api/v1/b/{biz}/product-imports/{b}/confirm", {"apply_changes": True})
    assert run_jobs(shop) == ["done"]
    assert get(shop, b).json()["counts"]["applied"] == 1
    items = pg.client.get(f"/api/v1/b/{biz}/products", headers=as_user("alice")).json()["items"]
    assert [p["code"] for p in items] == ["SOAP-1"]
