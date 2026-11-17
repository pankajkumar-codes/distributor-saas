"""The GSTR-1 export job and its routes on PostgreSQL (R1-M8 S4).

The build and the checks are staged (a real return needs confirmed documents; S2 and S3 test the build's rows and the
renderer), so what is real here is the route, the gate, the job queue, the stored files, the snapshot and its tables,
the audit row and tenant isolation. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import hashlib
import json
from pathlib import Path
import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app.modules.filing import entitlement, export_job, snapshots
from platform_common import jobs
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member
from .test_gstr1_sections import INV, SOAP, WB, A, line
from .test_periods_postgres import choose
from .test_snapshots_postgres import build_of, lines

REPO = Path(__file__).resolve().parents[6]
pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def b2b_only():
    return [
        line("INV-1", 5, INV, "B2B", WB, SOAP, "10", "1000.00", cgst="90.00", sgst="90.00", value="1180.00", buyer=A),
    ]  # fmt: skip


class Stage:
    """What the build and the checks return, changeable between calls."""

    def __init__(self):
        self.lines = b2b_only()
        self.fp = "a" * 64
        self.findings = []
        self.after = None  # a function called after each build, to change things under the job

    def build(self, tx, inst):
        b = build_of(inst, self.lines, self.fp)
        if self.after:
            self.after()
        return b

    def checks(self, tx, b):
        return list(self.findings)


@pytest.fixture()
def ex(pg, tmp_path, monkeypatch):
    from app import api as app_api
    from migrator.refdata import load
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    with pg.owner.connect() as c:
        load(c.connection.driver_connection, REPO / "refdata")
    queue, store = FakeQueue(), LocalObjectStore(tmp_path)
    set_queue(queue)
    set_store(store)
    stage = Stage()
    monkeypatch.setattr(export_job, "build_return", stage.build)
    monkeypatch.setattr(export_job, "run_checks", stage.checks)
    from app.modules.filing import api

    monkeypatch.setattr(api, "run_checks", stage.checks)
    b = new_business(pg, "alice")
    choose(pg, b, "monthly")
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    inst = next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10")
    try:
        yield pg, b, inst, stage, queue, store
    finally:
        set_queue(None)
        set_store(None)
        entitlement.set_check(None)


def start(pg, b, inst, sub="alice"):
    return pg.client.post(f"/api/v1/b/{b}/returns/{inst}/exports", headers=as_user(sub))


def status(pg, b, inst, job, sub="alice"):
    return pg.client.get(f"/api/v1/b/{b}/returns/{inst}/exports/{job}", headers=as_user(sub))


def run(queue):
    return queue.drain(jobs.handle_message)


def error_code(r):
    return r.json()["error"]["code"]


def stored(store, b, key):
    return store.get_bytes(uuid.UUID(str(b)), key)


def test_an_export_stores_the_file_the_snapshot_and_what_it_relied_on(ex):
    pg, b, inst, stage, queue, store = ex
    r = start(pg, b, inst)
    assert r.status_code == 202, r.text
    job = r.json()["job_id"]
    assert status(pg, b, inst, job).json()["status"] == "preparing"
    run(queue)
    s = status(pg, b, inst, job).json()
    assert s["status"] == "ready" and s["version"] == 1 and len(s["files"]) == 1
    # nobody has uploaded a file like this to the portal yet: never "ready to upload" until that is recorded in refdata
    assert s["unverified_tables"] == [] and s["portal_tested"] is False and s["ready_to_upload"] is False
    assert s["not_in_file"] == list(export_job.NOT_IN_FILE)
    [f] = pg.owner.connect().execute(text("select * from filing.export_files")).all()
    body = stored(store, b, f.object_key)
    assert hashlib.sha256(body).hexdigest() == f.sha256 and len(body) == f.size_bytes
    assert json.loads(body)["gstin"] == "19AAPFU0939F1ZS"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots where purpose = 'export'") == 1
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'filing.exported'") == 1
    # the audit row carries ids and counts only
    data = scalar(pg.owner, "select data from platform.audit_log where action = 'filing.exported'")
    assert set(data) == {"snapshot_id", "version", "parts"} and data["parts"] == 1


def test_a_table_without_a_tool_sample_is_never_ready_to_upload(ex):
    pg, b, inst, stage, queue, _ = ex
    stage.lines = lines()  # carries a credit note to a registered buyer: cdnr
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    s = status(pg, b, inst, job).json()
    assert s["status"] == "ready" and "cdnr" in s["unverified_tables"] and s["ready_to_upload"] is False


def test_asking_again_joins_the_job_and_a_changed_return_is_the_next_version(ex):
    pg, b, inst, stage, queue, _ = ex
    one = start(pg, b, inst).json()["job_id"]
    assert start(pg, b, inst).json()["job_id"] == one
    run(queue)
    assert start(pg, b, inst).json()["job_id"] == one  # unchanged: the finished job
    stage.fp = "b" * 64
    two = start(pg, b, inst).json()["job_id"]
    assert two != one
    run(queue)
    assert status(pg, b, inst, two).json()["version"] == 2
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 2


def test_a_return_that_is_not_ready_is_refused_and_an_accepted_warning_is_recorded_with_the_export(ex):
    from app.modules.filing.checks import Finding

    pg, b, inst, stage, queue, _ = ex
    stage.findings = [Finding("C-02", "block", "m", (), "a" * 64)]
    r = start(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "not_ready"
    stage.findings = [Finding("C-16", "warn", "m", (), "c" * 64)]
    assert error_code(start(pg, b, inst)) == "not_ready"
    ok = pg.client.post(
        f"/api/v1/b/{b}/returns/{inst}/check-acceptances",
        headers=as_user("alice"),
        json={"check_code": "C-16", "subject_fp": "c" * 64, "note": "CA to confirm"},
    )
    assert ok.status_code == 200, ok.text
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    assert status(pg, b, inst, job).json()["status"] == "ready"
    assert scalar(pg.owner, "select count(*) from filing.snapshot_acceptances") == 1
    assert scalar(pg.owner, "select count(*) from filing.export_files") == 1


def test_nothing_is_stored_when_the_return_is_refused(ex):
    pg, b, inst, stage, queue, store = ex
    stage.lines = []
    r = start(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "nothing_to_file"
    assert queue.sent == [] and scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0


def test_the_download_hook_fails_closed_outside_demo_and_local(ex, monkeypatch):
    pg, b, inst, stage, queue, _ = ex
    entitlement.set_check(lambda tx, business: False)
    r = start(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "download_not_available" and queue.sent == []
    entitlement.set_check(None)
    monkeypatch.setattr(entitlement.plans, "FREE_FOR_NOW", False)  # R1 opens it for everyone; this is the rule behind it
    monkeypatch.setattr(entitlement, "debug_env", lambda: False)  # the default outside local and test
    assert error_code(start(pg, b, inst)) == "download_not_available"
    entitlement.set_check(lambda tx, business: True)  # what M9 will say for a paid plan
    assert start(pg, b, inst).status_code == 202


def test_the_links_are_withdrawn_if_the_plan_stops_allowing_downloads(ex):
    pg, b, inst, stage, queue, _ = ex
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    entitlement.set_check(lambda tx, business: False)
    r = status(pg, b, inst, job)
    assert r.status_code == 409 and error_code(r) == "download_not_available"


def test_a_return_that_changes_under_the_job_leaves_no_snapshot_and_no_file(ex):
    pg, b, inst, stage, queue, store = ex
    job = start(pg, b, inst).json()["job_id"]
    stage.fp = "d" * 64  # the data changed between the click and the job
    run(queue)
    s = status(pg, b, inst, job).json()
    assert s == {**s, "status": "failed", "error_code": "changed_during_export"}
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0
    assert scalar(pg.owner, "select count(*) from filing.export_files") == 0


def _limits(monkeypatch, **values):
    """Refdata values for the export's limits, by their full key; everything else is read as usual."""
    real = export_job.value_on
    monkeypatch.setattr(export_job, "value_on", lambda tx, key, on: values.get(key, real(tx, key, on)))


def test_a_big_return_is_split_into_files_on_document_boundaries(ex, monkeypatch):
    pg, b, inst, stage, queue, store = ex
    stage.lines = [
        line(f"INV-{i}", 5 + i, INV, "B2B", WB, SOAP, "10", "1000.00", cgst="90.00", sgst="90.00", value="1180.00",
             buyer=A)
        for i in range(1, 21)
    ]  # fmt: skip
    _limits(monkeypatch, **{"gstr1.offline_tool.max_lines": 12})
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    s = status(pg, b, inst, job).json()
    assert s["status"] == "ready" and len(s["files"]) >= 2
    keys = [r.object_key for r in pg.owner.connect().execute(text("select object_key from filing.export_files"))]
    assert len(set(keys)) == len(keys) == len(s["files"])
    seen = []
    for k in keys:
        for party in json.loads(stored(store, b, k)).get("b2b", []):
            seen += [i["inum"] for i in party["inv"]]
    assert sorted(seen) == sorted(f"INV-{i}" for i in range(1, 21))  # every document once, none cut


def test_a_file_over_the_size_limit_stores_nothing(ex, monkeypatch):
    pg, b, inst, stage, queue, store = ex
    _limits(monkeypatch, **{"gstr1.portal_file.max_bytes": 50})
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    assert status(pg, b, inst, job).json()["error_code"] == "file_too_large"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0
    assert scalar(pg.owner, "select count(*) from filing.export_files") == 0


def test_a_crash_before_commit_is_retried_into_one_snapshot_under_the_same_keys(ex, monkeypatch):
    pg, b, inst, stage, queue, store = ex
    job = start(pg, b, inst).json()["job_id"]
    real = snapshots.write_snapshot
    calls = []

    def flaky(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the connection dropped")
        return real(*a, **kw)

    monkeypatch.setattr(snapshots, "write_snapshot", flaky)
    try:
        run(queue)
    except RuntimeError:
        pass
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0
    jobs.handle_message({"type": jobs.RUN, "job_id": job})
    run(queue)
    assert status(pg, b, inst, job).json()["status"] == "ready"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 1
    assert scalar(pg.owner, "select count(*) from filing.export_files") == 1


def test_a_job_that_already_committed_is_not_written_twice(ex):
    pg, b, inst, stage, queue, _ = ex
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    jobs.handle_message({"type": jobs.RUN, "job_id": job})  # a duplicate delivery
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 1
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'filing.exported'") == 1


def test_who_may_export_and_which_business(ex):
    pg, b, inst, stage, queue, _ = ex
    seed_member(pg, b, "bill", "billing")
    seed_member(pg, b, "cathy", "ca")
    assert start(pg, b, inst, "bill").status_code in (403, 404)  # billing does not prepare returns
    job = start(pg, b, inst, "cathy").json()["job_id"]  # a CA prepares returns
    run(queue)
    other = new_business(pg, "mallory")
    mine = start(pg, b, inst).json()["job_id"]
    assert pg.client.post(f"/api/v1/b/{other}/returns/{inst}/exports", headers=as_user("mallory")).status_code in (
        403,
        404,
    )
    r = pg.client.get(f"/api/v1/b/{other}/returns/{inst}/exports/{job}", headers=as_user("mallory"))
    assert r.status_code in (403, 404)
    assert pg.client.get(f"/api/v1/b/{b}/returns/{inst}/exports/{job}", headers=as_user("mallory")).status_code in (
        403,
        404,
    )
    assert mine  # the owner's own job is unaffected


def test_a_job_of_another_return_or_kind_is_not_found_here(ex):
    pg, b, inst, stage, queue, _ = ex
    job = start(pg, b, inst).json()["job_id"]
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    other = next(x["instance_id"] for x in rows if x["instance_id"] != inst and x["form"] == "GSTR1")
    assert status(pg, b, other, job).status_code == 404
    assert status(pg, b, inst, uuid.uuid4()).status_code == 404


def test_a_job_result_naming_a_snapshot_that_is_not_this_returns_is_not_served(ex):
    pg, b, inst, stage, queue, _ = ex
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    assert status(pg, b, inst, job).json()["status"] == "ready"
    with pg.owner.begin() as c:
        c.execute(
            text("update platform.jobs set result = jsonb_set(result, '{snapshot_id}', to_jsonb(cast(:s as text)))"
                 " where id = :j"),
            {"s": str(uuid.uuid4()), "j": job},
        )  # fmt: skip
    assert status(pg, b, inst, job).status_code == 404


def test_a_member_who_loses_the_role_before_the_job_runs_is_refused_by_the_job(ex):
    pg, b, inst, stage, queue, store = ex
    seed_member(pg, b, "cathy", "ca")
    job = start(pg, b, inst, "cathy").json()["job_id"]
    with pg.owner.connect() as c:
        c.execute(text("update identity.memberships set role = 'billing' where user_sub = 'cathy'"))
    run(queue)
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0
    assert scalar(pg.owner, "select error_code from platform.jobs where id = :j", j=job) == "not_allowed"


def test_the_export_tables_are_insert_only(ex):
    from sqlalchemy.exc import DBAPIError

    pg, b, inst, stage, queue, _ = ex
    start(pg, b, inst)
    run(queue)
    with pytest.raises(DBAPIError):
        with pg.owner.begin() as c:
            c.execute(text("update filing.export_files set sha256 = repeat('0', 64)"))
    with pytest.raises(DBAPIError):
        with pg.owner.begin() as c:
            c.execute(text("delete from filing.export_files"))


def test_a_file_is_ready_to_upload_only_when_the_portal_has_accepted_one_like_it_and_no_table_is_unverified(ex, monkeypatch):
    pg, b, inst, stage, queue, _ = ex
    monkeypatch.setattr(export_job, "_portal_verified", lambda tx: True)
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    s = status(pg, b, inst, job).json()
    assert s["portal_tested"] is True and s["ready_to_upload"] is True
    stage.fp = "e" * 64
    stage.lines = lines()  # a credit note to a registered buyer: cdnr has no sample
    two = start(pg, b, inst).json()["job_id"]
    run(queue)
    s = status(pg, b, inst, two).json()
    assert s["portal_tested"] is True and s["ready_to_upload"] is False


def test_the_shipped_refdata_says_the_portal_has_not_been_tried(ex):
    pg, b, inst, stage, queue, _ = ex
    with pg.app_rw.begin() as c:
        assert export_job._portal_verified(c) is False


def test_a_failed_job_does_not_lock_the_user_out(ex, monkeypatch):
    pg, b, inst, stage, queue, store = ex
    one = start(pg, b, inst).json()["job_id"]
    real = export_job.make_files

    def broken(tx, model):
        raise jobs.JobFailed("store_unavailable")

    monkeypatch.setattr(export_job, "make_files", broken)
    run(queue)
    assert status(pg, b, inst, one).json()["error_code"] == "store_unavailable"
    monkeypatch.setattr(export_job, "make_files", real)
    two = start(pg, b, inst).json()["job_id"]  # a new click gets a new job, not the failed one
    assert two != one
    assert start(pg, b, inst).json()["job_id"] == two  # and a second click joins that one
    run(queue)
    assert status(pg, b, inst, two).json()["status"] == "ready"
    assert status(pg, b, inst, one).json()["status"] == "failed"  # the old job still tells what happened
    assert start(pg, b, inst).json()["job_id"] == two  # unchanged and finished: joins it


def test_a_return_refused_by_the_job_for_not_ready_can_be_asked_again_once_a_warning_is_accepted(ex):
    from app.modules.filing.checks import Finding

    pg, b, inst, stage, queue, _ = ex
    job = start(pg, b, inst).json()["job_id"]
    stage.findings = [Finding("C-16", "warn", "m", (), "c" * 64)]  # the job sees a warning the click did not
    run(queue)
    assert status(pg, b, inst, job).json()["error_code"] == "not_ready"
    ok = pg.client.post(f"/api/v1/b/{b}/returns/{inst}/check-acceptances", headers=as_user("alice"),
                        json={"check_code": "C-16", "subject_fp": "c" * 64, "note": "CA to confirm"})
    assert ok.status_code == 200
    again = start(pg, b, inst).json()["job_id"]
    assert again != job
    run(queue)
    assert status(pg, b, inst, again).json()["status"] == "ready"


def test_the_plan_shows_the_prices_and_says_free_for_now_until_the_one_flag_is_removed(ex, monkeypatch):
    pg, b, inst, stage, queue, _ = ex
    r = pg.client.get(f"/api/v1/b/{b}/plan", headers=as_user("alice"))
    assert r.status_code == 200
    assert r.json() == {"name": "GST filing", "monthly_rupees": 499, "quarterly_rupees": 1499,
                        "gst_note": "plus 18% GST on our fee", "free_for_now": True}  # fmt: skip
    assert start(pg, b, inst).status_code == 202  # free for now: the download is open to this business
    monkeypatch.setattr(entitlement.plans, "FREE_FOR_NOW", False)
    assert pg.client.get(f"/api/v1/b/{b}/plan", headers=as_user("alice")).json()["free_for_now"] is False
    other = new_business(pg, "mallory")  # another tenant's plan is not readable with this user's token
    assert pg.client.get(f"/api/v1/b/{b}/plan", headers=as_user("mallory")).status_code in (403, 404)
    assert other
