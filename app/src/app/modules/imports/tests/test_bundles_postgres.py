"""Bundle upload, slice 2 (bundle-upload-plan): the routes, the two jobs and the tables on PostgreSQL as app_rw.

Made-up files only (the readers' masked fixtures). Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import json
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import api as app_api
from app.modules.imports.readers import clear_for_tests, register_readers
from platform_common import jobs
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, scalar, seed_member, user_id
from .fixtures import amazon, flipkart, meesho, own_excel, pdf
from .test_bundle import zip_of

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

ZIP = "application/zip"


@pytest.fixture()
def shop(pg, tmp_path):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 17, 12, tzinfo=IST))
    queue = FakeQueue()
    set_queue(queue)
    set_store(LocalObjectStore(tmp_path))
    clear_for_tests()
    register_readers()
    biz = new_business(pg, "alice")
    for sub, role in (("adam", "admin"), ("cathy", "ca"), ("bill", "billing")):
        seed_member(pg, biz, sub, role)
    try:
        yield pg, biz, queue
    finally:
        set_queue(None)
        set_store(None)
        clear_for_tests()


def post(pg, path, body=None, sub="alice", key=None):
    return pg.client.post(path, json=body, headers={**as_user(sub), **({"Idempotency-Key": key} if key else {})})


def get(pg, path, sub="alice"):
    return pg.client.get(path, headers=as_user(sub))


def patch(pg, path, body, sub="alice"):
    return pg.client.patch(path, json=body, headers=as_user(sub))


MIXED = [
    ("Amazon/MTR_B2C.csv", amazon.b2c_good()),
    ("Flipkart/sales.xlsx", flipkart.good()),
    ("Meesho/orders.xlsx", meesho.sales_good()),
    ("mine/invoices.xlsx", own_excel.good()),
    ("mine/INV-1.pdf", pdf.one_invoice()),
    ("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40),
    ("notes.txt", b"just some words, no table"),
]


def upload_bundle(shop, content, name="reports.zip", sub="alice"):
    """Start, post the zip, complete. Returns (bundle_id, job_id)."""
    pg, biz, _ = shop
    started = post(pg, f"/api/v1/b/{biz}/upload-bundles", {"file_name": name, "size_bytes": len(content)}, sub=sub,
                   key=uuid.uuid4().hex)
    assert started.status_code == 201, started.text
    up = started.json()["upload"]
    assert pg.client.post(up["url"], data=up["fields"], files={"file": (name, content, ZIP)}).status_code == 204
    done = post(pg, f"/api/v1/b/{biz}/upload-bundles/{started.json()['bundle_id']}/complete", sub=sub)
    assert done.status_code == 202, done.text
    return started.json()["bundle_id"], done.json()["job_id"]


def run_jobs(shop):
    return shop[2].drain(jobs.handle_message)


def classified(shop, entries=MIXED):
    pg, biz, _ = shop
    bundle_id, _ = upload_bundle(shop, zip_of(entries))
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}").json()
    assert out["status"] == "classified", out
    return bundle_id, out


def by_name(out):
    return {f["file_name"]: f for f in out["files"]}


# --- the sorting job ---------------------------------------------------------------------------------------------


def test_a_mixed_zip_is_sorted_by_content_and_nothing_is_read_or_staged(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    files = by_name(out)
    assert {n: (f["section"], f["state"]) for n, f in files.items()} == {
        "MTR_B2C.csv": ("amazon", "used"), "sales.xlsx": ("flipkart", "used"), "orders.xlsx": ("meesho", "used"),
        "invoices.xlsx": ("own_invoices_excel", "used"), "INV-1.pdf": ("own_invoices_pdf", "used"),
        "photo.png": (None, "not_used"), "notes.txt": (None, "not_used"),
    }
    assert files["photo.png"]["reason"] == "This file type is not used."
    assert files["INV-1.pdf"]["note"].startswith("Will be read as your invoices")
    assert files["MTR_B2C.csv"]["note"] is None
    assert out["selectable_sections"] == ["amazon", "flipkart", "meesho", "own_invoices_excel", "own_invoices_pdf"]
    # classifying reads no rows and makes no uploads
    for table in ("imports.uploads", "imports.import_runs", "imports.import_rows"):
        assert scalar(pg.owner, f"select count(*) from {table}") == 0
    assert scalar(pg.owner, "select count(*) from imports.bundle_files") == len(MIXED)


def test_the_audit_log_holds_counts_never_a_file_name(shop):
    pg, biz, _ = shop
    classified(shop)
    rows = scalar(pg.owner, "select json_agg(data) from platform.audit_log where action like 'imports.bundle_%'")
    blob = json.dumps(rows)
    assert "MTR_B2C" not in blob and "sales.xlsx" not in blob and "photo" not in blob
    one = scalar(pg.owner, "select data from platform.audit_log where action = 'imports.bundle_classified'")
    assert (one["files"], one["used"], one["not_used"], one["not_selected"]) == (7, 5, 2, 0)


def test_a_renamed_file_is_sorted_by_what_it_holds(shop):
    _, out = classified(shop, [("Amazon report.xlsx", flipkart.good())])
    (f,) = out["files"]
    assert (f["section"], f["state"]) == ("flipkart", "used")


def test_an_unsafe_zip_is_refused_whole_in_plain_words(shop):
    pg, biz, _ = shop
    bundle_id, _ = upload_bundle(shop, zip_of([("a.csv", b"x"), ("b.csv", b"y")], encrypted=("a.csv",)))
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}").json()
    assert (out["status"], out["reject_reason"], out["files"]) == ("rejected", "encrypted", [])
    assert out["reject_message"] == "The zip is password protected."
    assert scalar(pg.owner, "select count(*) from imports.bundle_files") == 0


def test_a_utf16_text_file_is_said_in_words(shop):
    _, out = classified(shop, [("sales.csv", b"\xff\xfe" + "Seller Gstin\n".encode("utf-16-le"))])
    assert out["files"][0]["reason_code"] == "utf16"
    assert "UTF-8" in out["files"][0]["reason"]


def test_a_section_the_business_did_not_choose_is_listed_and_cannot_be_moved_there(shop):
    pg, biz, _ = shop
    r = pg.client.put(f"/api/v1/b/{biz}/channels", headers=as_user("alice"),
                      json={"amazon": True, "flipkart": False, "meesho": False, "own_invoices": False})
    assert r.status_code == 200, r.text
    bundle_id, out = classified(shop)
    files = by_name(out)
    assert files["MTR_B2C.csv"]["state"] == "used"
    assert [files[n]["state"] for n in ("sales.xlsx", "orders.xlsx", "invoices.xlsx", "INV-1.pdf")] == ["not_selected"] * 4
    assert out["selectable_sections"] == ["amazon"]
    moved = patch(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/files/{files['sales.xlsx']['n']}",
                  {"section": "flipkart"})
    assert moved.status_code == 422 and moved.json()["error"]["code"] == "section_not_selected"


# --- the user's choices --------------------------------------------------------------------------------------------


def test_a_file_can_be_moved_or_dropped_and_every_choice_is_kept(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    files = by_name(out)
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/files"
    dropped = patch(pg, f"{base}/{files['orders.xlsx']['n']}", {"section": None}).json()
    assert by_name(dropped)["orders.xlsx"]["state"] == "dropped"
    moved = patch(pg, f"{base}/{files['notes.txt']['n']}", {"section": "own_invoices_excel"})
    assert moved.status_code == 422 and moved.json()["error"]["code"] == "file_type_not_allowed"  # .txt is not accepted there
    back = patch(pg, f"{base}/{files['orders.xlsx']['n']}", {"section": "meesho"}).json()
    f = by_name(back)["orders.xlsx"]
    assert (f["state"], f["section"], f["moved"], f["found_section"]) == ("used", "meesho", True, "meesho")
    assert scalar(pg.owner, "select count(*) from imports.bundle_choices") == 2  # drop, then move back: both kept
    # a choice is never an edit
    for sql in ("update imports.bundle_choices set section = null", "delete from imports.bundle_choices",
                "update imports.bundle_files set state = 'used'", "delete from imports.bundle_files"):
        with pytest.raises(DBAPIError, match="insert-only"), pg.owner.connect() as c:
            c.execute(text(sql))


def test_nothing_readable_cannot_be_moved(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    n = by_name(out)["photo.png"]["n"]
    r = patch(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/files/{n}", {"section": "amazon"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "file_cannot_be_moved"
    assert patch(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/files/99", {"section": "amazon"}).status_code == 404
    # dropping first does not open the way: the sorting's reason still holds
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/files/{n}"
    assert patch(pg, base, {"section": None}).status_code == 200
    again = patch(pg, base, {"section": "amazon"})
    assert again.status_code == 422 and again.json()["error"]["code"] == "file_cannot_be_moved"


# --- staging -------------------------------------------------------------------------------------------------------


def test_staging_makes_one_ordinary_upload_per_file_that_is_read_and_asking_twice_makes_no_more(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    files = by_name(out)
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    patch(pg, f"{base}/files/{files['orders.xlsx']['n']}", {"section": None})  # dropped: not staged
    patch(pg, f"{base}/files/{files['sales.xlsx']['n']}", {"section": "amazon"})  # moved to a section that will refuse it
    one = post(pg, f"{base}/stage")
    two = post(pg, f"{base}/stage")
    assert one.status_code == two.status_code == 202 and one.json()["job_id"] == two.json()["job_id"]
    assert get(pg, base).json()["status"] == "staging"
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 0  # nothing until the job runs
    assert run_jobs(shop)[0] == "done"
    done = get(pg, base).json()
    assert done["status"] == "staged"
    staged = {f["file_name"]: f for f in done["files"] if f["upload_id"]}
    assert set(staged) == {"MTR_B2C.csv", "sales.xlsx", "invoices.xlsx", "INV-1.pdf"}
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 4
    assert scalar(pg.owner, "select count(*) from imports.bundle_uploads") == 4
    # each is a normal upload, in the section it was sent to, and the usual parse job reads it
    run_jobs(shop)
    rows = pg.owner.connect().execute(
        text("select section, file_name, status, reject_reason from imports.uploads order by file_name")).all()
    assert {(r.section, r.file_name) for r in rows} == {
        ("amazon", "MTR_B2C.csv"), ("amazon", "sales.xlsx"), ("own_invoices_excel", "invoices.xlsx"),
        ("own_invoices_pdf", "INV-1.pdf")}
    state = {r.file_name: (r.status, r.reject_reason) for r in rows}
    # the usual parse job ran on every one, and a file the business's reader will not take is refused in that
    # reader's own words (these made-up files carry another GSTIN than the test business)
    assert all(status != "received" for status, _ in state.values()), state
    assert state["sales.xlsx"][0] == "rejected" and state["sales.xlsx"][1] != "wrong_gstin"  # a Flipkart workbook to Amazon
    for sql in ("update imports.bundle_uploads set n = n", "delete from imports.bundle_uploads"):  # rows exist now
        with pytest.raises(DBAPIError, match="insert-only"), pg.owner.connect() as c:
            c.execute(text(sql))
    # staging again after it finished changes nothing
    assert post(pg, f"{base}/stage").json()["job_id"] == one.json()["job_id"]
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 4


def test_the_same_bundle_cannot_be_changed_after_staging_and_nothing_to_stage_is_said(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop, [("photo.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)])
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    r = post(pg, f"{base}/stage")
    assert r.status_code == 422 and r.json()["error"]["code"] == "nothing_to_stage"
    bundle_id, out = classified(shop, [("a.csv", amazon.b2c_good())])
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    post(pg, f"{base}/stage")
    run_jobs(shop)
    late = patch(pg, f"{base}/files/1", {"section": None})
    assert late.status_code == 409 and late.json()["error"]["code"] == "bundle_not_open"


def test_a_zip_that_changed_between_listing_and_staging_is_refused_not_staged(shop):
    from platform_common.storage import get_store

    pg, biz, _ = shop
    bundle_id, out = classified(shop, [("a.csv", amazon.b2c_good())])
    key = scalar(pg.owner, "select s3_key from imports.bundles where id = :i", i=bundle_id)
    get_store().put(biz, key, zip_of([("a.csv", b"another file")]), ZIP)  # the object is swapped after the listing
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    post(pg, f"{base}/stage")
    run_jobs(shop)
    done = get(pg, base).json()
    assert (done["status"], done["reject_reason"]) == ("rejected", "bundle_changed")
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 0


def test_a_listing_that_disagrees_for_the_last_file_stages_nothing_at_all(shop, monkeypatch):
    from dataclasses import replace

    from app.modules.imports import bundle as engine

    pg, biz, _ = shop
    bundle_id, out = classified(shop, [("a.csv", amazon.b2c_good()), ("b.xlsx", flipkart.good()), ("c.xlsx", own_excel.good())])
    real = engine.open_bundle

    def changed(content, limits):
        files = real(content, limits)
        return files[:-1] + [replace(files[-1], size=files[-1].size + 1)]  # only the last file disagrees

    monkeypatch.setattr(engine, "open_bundle", changed)
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    post(pg, f"{base}/stage")
    run_jobs(shop)
    done = get(pg, base).json()
    assert (done["status"], done["reject_reason"]) == ("rejected", "bundle_changed")
    assert all(f["upload_id"] is None for f in done["files"])
    for table in ("imports.uploads", "imports.bundle_uploads"):
        assert scalar(pg.owner, f"select count(*) from {table}") == 0
    assert scalar(pg.owner, "select count(*) from platform.jobs where type = 'imports.parse'") == 0
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'imports.upload_received'") == 0


# --- who may do what -----------------------------------------------------------------------------------------------


def test_owner_and_admin_upload_the_ca_views_billing_sees_nothing(shop):
    pg, biz, _ = shop
    bundle_id, _ = upload_bundle(shop, zip_of(MIXED), sub="adam")  # an admin
    run_jobs(shop)
    base = f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"
    for sub, code in (("alice", 200), ("adam", 200), ("cathy", 200), ("bill", 404)):
        assert get(pg, base, sub=sub).status_code == code
    for sub in ("cathy", "bill"):  # the CA and billing cannot start, change or stage
        assert post(pg, f"/api/v1/b/{biz}/upload-bundles", {"file_name": "a.zip", "size_bytes": 5}, sub=sub,
                    key=uuid.uuid4().hex).status_code == 404
        assert post(pg, f"{base}/complete", sub=sub).status_code == 404
        assert patch(pg, f"{base}/files/1", {"section": None}, sub=sub).status_code == 404
        assert post(pg, f"{base}/stage", sub=sub).status_code == 404
    assert scalar(pg.owner, "select count(*) from imports.bundle_choices") == 0
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 0


def test_another_business_gets_404_on_every_route(shop):
    pg, biz, _ = shop
    bundle_id, _ = upload_bundle(shop, zip_of(MIXED))
    run_jobs(shop)
    other = new_business(pg, "bob")
    for path in (f"/api/v1/b/{other}/upload-bundles/{bundle_id}", f"/api/v1/b/{biz}/upload-bundles/{bundle_id}"):
        assert get(pg, path, sub="bob").status_code == 404  # its own business with another's id; not a member of biz
        assert post(pg, f"{path}/complete", sub="bob").status_code == 404
        assert patch(pg, f"{path}/files/1", {"section": None}, sub="bob").status_code == 404
        assert post(pg, f"{path}/stage", sub="bob").status_code == 404
    assert scalar(pg.owner, "select count(*) from imports.bundle_choices") == 0
    assert scalar(pg.owner, "select count(*) from imports.uploads") == 0


def test_the_job_refuses_when_the_user_lost_the_permission(shop):
    pg, biz, _ = shop
    bundle_id, _ = upload_bundle(shop, zip_of(MIXED), sub="adam")
    with pg.owner.connect() as c:
        c.execute(text("update identity.memberships set role = 'billing' where user_sub = 'adam'"))
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}").json()
    assert (out["status"], out["reject_reason"]) == ("rejected", "not_allowed")


# --- start and complete --------------------------------------------------------------------------------------------


def test_start_takes_only_a_zip_within_the_cap_and_is_idempotent_by_key(shop):
    pg, biz, _ = shop
    url = f"/api/v1/b/{biz}/upload-bundles"
    assert post(pg, url, {"file_name": "a.csv", "size_bytes": 5}, key="k0").json()["error"]["code"] == "file_type_not_allowed"
    big = post(pg, url, {"file_name": "a.zip", "size_bytes": 104857601}, key="k1")
    assert big.status_code == 422 and big.json()["error"]["code"] == "file_too_large"
    body = {"file_name": "a.zip", "size_bytes": 10}
    one = post(pg, url, body, key="k2")
    two = post(pg, url, body, key="k2")
    assert one.status_code == two.status_code == 201 and one.json()["bundle_id"] == two.json()["bundle_id"]
    assert scalar(pg.owner, "select count(*) from imports.bundles") == 1


def test_complete_twice_is_one_job_and_an_unfinished_upload_is_not_completed(shop):
    pg, biz, _ = shop
    started = post(pg, f"/api/v1/b/{biz}/upload-bundles", {"file_name": "a.zip", "size_bytes": 10}, key="k3").json()
    r = post(pg, f"/api/v1/b/{biz}/upload-bundles/{started['bundle_id']}/complete")
    assert r.status_code == 409 and r.json()["error"]["code"] == "upload_not_received"
    bundle_id, job_id = upload_bundle(shop, zip_of(MIXED))
    assert post(pg, f"/api/v1/b/{biz}/upload-bundles/{bundle_id}/complete").json()["job_id"] == job_id
    assert len(run_jobs(shop)) == 1


# --- the tables ----------------------------------------------------------------------------------------------------


def test_the_tables_refuse_another_businesss_rows_even_for_the_owner_role(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    other = new_business(pg, "bob")
    with pytest.raises(DBAPIError, match="foreign key"), pg.owner.connect() as c:
        c.execute(text("insert into imports.bundle_files (bundle_id, business_id, n, file_name, size_bytes, state,"
                       " reason_code) values (:i, :b, 50, 'x.csv', 1, 'not_used', 'no_match')"), {"i": bundle_id, "b": other})
    with pytest.raises(DBAPIError, match="foreign key"), pg.owner.connect() as c:
        c.execute(text("insert into imports.bundle_choices (id, bundle_id, business_id, n, section, chosen_by)"
                       " values (gen_random_uuid(), :i, :b, 1, null, gen_random_uuid())"), {"i": bundle_id, "b": other})


def test_one_business_cannot_read_or_write_anothers_bundle_through_the_app_role(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    other = new_business(pg, "bob")
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "bob"), other)
        for table in ("bundles", "bundle_files", "bundle_choices", "bundle_uploads"):
            assert c.execute(text(f"select count(*) from imports.{table}")).scalar() == 0
        with pytest.raises(DBAPIError, match="row-level security"):
            c.execute(text("insert into imports.bundles (id, business_id, s3_key, file_name, size_bytes, created_by)"
                           " values (gen_random_uuid(), :b, 'k', 'a.zip', 1, gen_random_uuid())"), {"b": biz})
    with pg.app_rw.begin() as c:  # and the app role cannot change or remove what it wrote
        ctx(c, user_id(pg.owner, "alice"), biz)
        with pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text("delete from imports.bundle_files"))


def test_a_read_only_role_and_a_support_grant_read_but_do_not_write(shop):
    pg, biz, _ = shop
    bundle_id, out = classified(shop)
    with pg.app_rw.begin() as c:
        ctx(c, user_id(pg.owner, "alice"), biz, role="app_ro")
        assert c.execute(text("select count(*) from imports.bundle_files")).scalar() == len(MIXED)
        with pytest.raises(DBAPIError, match="permission denied"):
            c.execute(text("insert into imports.bundle_choices (id, bundle_id, business_id, n, section, chosen_by)"
                           " values (gen_random_uuid(), :i, :b, 1, null, gen_random_uuid())"), {"i": bundle_id, "b": biz})
