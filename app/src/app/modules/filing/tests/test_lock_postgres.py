"""Mark filed, lock, unlock and relock on PostgreSQL (R1-M8 S5). The build is staged as in the export tests; the instance
rows, the guard trigger, the snapshots, the stored file, the audit log and the roles are real."""

import uuid

import pytest
from sqlalchemy import text

from app.modules.filing import lock

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member
from .test_export_job_postgres import ex, run, start, status, stored  # noqa: F401  (ex is a fixture)
from .test_gstr1_sections import INV, SOAP, WB, A, line

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

FILED = "2026-11-10"  # after October ends, before the frozen today (15 November)


@pytest.fixture()
def lk(ex, monkeypatch):  # noqa: F811
    pg, b, inst, stage, queue, store = ex
    monkeypatch.setattr(lock, "build_return", stage.build)
    return pg, b, inst, stage, queue, store


def filed(pg, b, inst, sub="alice", arn="AA1911260000001", on=FILED, **extra):
    return pg.client.post(f"/api/v1/b/{b}/returns/{inst}/filed", headers=as_user(sub),
                          json={"filed_on": on, "arn": arn, **extra})  # fmt: skip


def unlock(pg, b, inst, sub="alice", reason="the portal said to refile"):
    return pg.client.post(f"/api/v1/b/{b}/returns/{inst}/unlock", headers=as_user(sub), json={"reason": reason})


def error_code(r):
    return r.json()["error"]["code"]


def export(pg, b, inst, queue):
    job = start(pg, b, inst).json()["job_id"]
    run(queue)
    return job


def inv(n):
    return line(f"INV-{n}", 5 + n, INV, "B2B", WB, SOAP, "10", "1000.00", cgst="90.00", sgst="90.00", value="1180.00",
                buyer=A)  # fmt: skip


def instance_status(pg, inst):
    return scalar(pg.owner, "select status from filing.return_instances where id = :i", i=inst)


def test_marking_filed_after_an_export_locks_the_return_and_keeps_its_file(lk):
    pg, b, inst, stage, queue, store = lk
    export(pg, b, inst, queue)
    r = filed(pg, b, inst)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "filed_locked", "filed_on": FILED, "arn": "AA1911260000001", "snapshot_version": 2,
                        "changed_since_export": False, "has_file": True}  # fmt: skip
    assert instance_status(pg, inst) == "filed_locked"
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    mine = next(x for x in rows if x["instance_id"] == inst)
    assert (mine["status"], mine["filed_on"], mine["arn"]) == ("filed_locked", FILED, "AA1911260000001")
    assert pg.client.get(f"/api/v1/b/{b}/returns/{inst}", headers=as_user("alice")).json()["instance"]["arn"] == mine["arn"]
    other = next(x for x in rows if x["instance_id"] != inst)
    assert other["filed_on"] is None and other["arn"] is None
    [ev] = pg.owner.connect().execute(text("select * from filing.instance_events where kind = 'filed'")).all()
    assert ev.arn == "AA1911260000001" and str(ev.filed_on) == FILED and ev.snapshot_id is not None
    assert scalar(pg.owner, "select purpose from filing.return_snapshots where id = :s", s=ev.snapshot_id) == "lock"
    data = scalar(pg.owner, "select data from platform.audit_log where action = 'returns.filed'")
    assert data["version"] == 2 and data["changed_since_export"] is False
    # the locked return is downloaded from its lock snapshot: the same bytes the export made
    got = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/lock-file", headers=as_user("alice"))
    assert got.status_code == 200 and got.json()["version"] == 2 and len(got.json()["files"]) == 1
    keys = [r.object_key for r in pg.owner.connect().execute(text("select object_key from filing.export_files order by part_no"))]
    assert len(keys) == 2 and stored(store, b, keys[0]) == stored(store, b, keys[1])


def test_nothing_exported_yet_is_refused_until_the_user_says_why(lk):
    pg, b, inst, stage, queue, _ = lk
    r = filed(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "changed_since_export"
    assert instance_status(pg, inst) == "open" and scalar(pg.owner, "select count(*) from filing.return_snapshots") == 0
    assert filed(pg, b, inst, accept_changed={"reason": "  "}).status_code == 422
    r = filed(pg, b, inst, accept_changed={"reason": "Filed from the offline tool before we made a file"})
    assert r.status_code == 200 and r.json()["changed_since_export"] is True
    row = pg.owner.connect().execute(text("select * from filing.return_snapshots")).one()
    assert row.purpose == "lock" and row.changed_since_export and row.accept_reason.startswith("Filed from")
    assert row.difference["added"] == [{"section": "b2b", "number": "INV-1"}]


def test_a_return_changed_since_the_export_shows_the_difference_and_locks_only_with_a_reason(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    stage.lines = [inv(1), inv(2)]
    stage.fp = "b" * 64  # a document was added after the file was made
    r = filed(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "changed_since_export"
    c = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/changes", headers=as_user("alice")).json()
    assert c["same"] is False and c["reference"] == {"purpose": "export", "version": 1}
    assert c["difference"]["added"] == [{"section": "b2b", "number": "INV-2"}]
    assert instance_status(pg, inst) == "open"
    assert filed(pg, b, inst, accept_changed={"reason": "I filed INV-2 on the portal by hand"}).status_code == 200
    d = scalar(pg.owner, "select difference from filing.return_snapshots where purpose = 'lock'")
    assert d["added"] == [{"section": "b2b", "number": "INV-2"}] and d["removed"] == []


def test_the_changes_route_says_same_when_nothing_moved(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    c = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/changes", headers=as_user("alice")).json()
    assert c["same"] is True and c["difference"] == {"added": [], "removed": [], "changed": [], "summaries": []}


@pytest.mark.parametrize(
    ("body", "code"),
    [({"arn": "  "}, "arn_invalid"), ({"arn": "X" * 33}, "arn_invalid"), ({"on": "2026-11-16"}, "filed_on_future"),
     ({"on": "2026-10-30"}, "filed_on_before_period")],
)  # fmt: skip
def test_the_filing_date_and_arn_are_checked(lk, body, code):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    r = filed(pg, b, inst, **body)
    assert r.status_code == 422 and error_code(r) == code
    assert instance_status(pg, inst) == "open"


def test_a_return_already_locked_is_refused_and_nothing_is_added(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    assert filed(pg, b, inst).status_code == 200
    r = filed(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "period_not_open"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots where purpose = 'lock'") == 1
    assert scalar(pg.owner, "select count(*) from filing.instance_events where kind = 'filed'") == 1


def test_a_failure_while_locking_leaves_the_return_open_with_no_snapshot_and_no_event(lk, monkeypatch):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)

    def boom(*a, **kw):
        raise RuntimeError("the store went away")

    monkeypatch.setattr(lock, "_store_file", boom)
    assert filed(pg, b, inst).status_code == 500
    assert instance_status(pg, inst) == "open"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots where purpose = 'lock'") == 0
    assert scalar(pg.owner, "select count(*) from filing.instance_events where kind = 'filed'") == 0


def test_a_locked_return_is_no_longer_exported(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    filed(pg, b, inst)
    stage.fp = "c" * 64
    r = start(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "not_ready"


def test_who_may_lock_and_who_may_unlock(lk):
    pg, b, inst, stage, queue, _ = lk
    seed_member(pg, b, "ann", "admin")
    seed_member(pg, b, "cathy", "ca")
    seed_member(pg, b, "bill", "billing")
    export(pg, b, inst, queue)
    assert filed(pg, b, inst, "bill").status_code in (403, 404)
    assert instance_status(pg, inst) == "open"
    assert filed(pg, b, inst, "cathy").status_code == 200  # a CA may lock
    for sub in ("ann", "cathy", "bill"):
        assert unlock(pg, b, inst, sub).status_code in (403, 404), sub  # only the owner unlocks
    assert instance_status(pg, inst) == "filed_locked"
    assert unlock(pg, b, inst).status_code == 200


def test_unlock_needs_a_reason_and_a_locked_return_and_keeps_every_snapshot(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    r = unlock(pg, b, inst)
    assert r.status_code == 409 and error_code(r) == "not_locked"
    filed(pg, b, inst)
    assert unlock(pg, b, inst, reason="  ").status_code == 422
    assert instance_status(pg, inst) == "filed_locked"
    assert unlock(pg, b, inst, reason="A wrong ARN was entered").json() == {"status": "unlocked"}
    assert instance_status(pg, inst) == "unlocked"
    [ev] = pg.owner.connect().execute(text("select * from filing.instance_events where kind = 'unlocked'")).all()
    assert ev.reason == "A wrong ARN was entered" and ev.actor_user_id is not None
    assert scalar(pg.owner, "select reason from platform.audit_log where action = 'returns.unlock'") == "A wrong ARN was entered"
    assert scalar(pg.owner, "select count(*) from filing.return_snapshots") == 2
    assert unlock(pg, b, inst).status_code == 409  # already unlocked


def test_a_relock_compares_with_the_lock_snapshot_and_makes_the_next_version(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    filed(pg, b, inst)
    unlock(pg, b, inst)
    r = filed(pg, b, inst, arn="AA1911260000002")
    assert r.status_code == 200 and r.json()["snapshot_version"] == 3 and r.json()["changed_since_export"] is False
    assert instance_status(pg, inst) == "filed_locked"
    # members of the relock are the members of the first lock
    sql = (
        "select m.source_kind, m.source_id from filing.snapshot_members m join filing.return_snapshots s"
        " on s.id = m.snapshot_id where s.version = :v"
    )
    with pg.owner.connect() as c:
        first = set(map(tuple, c.execute(text(sql), {"v": 2}).all()))
        again = set(map(tuple, c.execute(text(sql), {"v": 3}).all()))
    assert first and first == again


def test_a_relock_after_a_change_needs_a_reason_too(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    filed(pg, b, inst)
    unlock(pg, b, inst)
    stage.lines = [inv(1), inv(2)]
    stage.fp = "d" * 64
    c = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/changes", headers=as_user("alice")).json()
    assert c["reference"] == {"purpose": "lock", "version": 2}
    assert error_code(filed(pg, b, inst)) == "changed_since_export"


def test_another_business_and_an_unknown_return_are_404_on_every_new_route(lk):
    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    other = new_business(pg, "mallory")
    base = f"/api/v1/b/{other}/returns/{inst}"
    h = as_user("mallory")
    assert pg.client.get(f"{base}/changes", headers=h).status_code == 404
    assert pg.client.post(f"{base}/filed", headers=h, json={"filed_on": FILED, "arn": "A1"}).status_code == 404
    assert pg.client.get(f"{base}/lock-file", headers=h).status_code == 404
    assert pg.client.post(f"{base}/unlock", headers=h, json={"reason": "x"}).status_code == 404
    missing = f"/api/v1/b/{b}/returns/{uuid.uuid4()}"
    assert pg.client.post(f"{missing}/filed", headers=as_user("alice"), json={"filed_on": FILED, "arn": "A1"}).status_code == 404
    assert instance_status(pg, inst) == "open"


def test_the_lock_file_is_refused_before_a_lock_and_when_the_plan_does_not_allow_downloads(lk):
    from app.modules.filing import entitlement

    pg, b, inst, stage, queue, _ = lk
    export(pg, b, inst, queue)
    r = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/lock-file", headers=as_user("alice"))
    assert r.status_code == 409 and error_code(r) == "not_locked"
    filed(pg, b, inst)
    entitlement.set_check(lambda tx, business: False)
    r = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/lock-file", headers=as_user("alice"))
    assert r.status_code == 409 and error_code(r) == "download_not_available"


def test_a_return_that_cannot_be_written_as_a_file_still_locks_without_one(lk):
    pg, b, inst, stage, queue, _ = lk
    stage.lines = []
    r = filed(pg, b, inst, accept_changed={"reason": "Nil return filed on the portal"})
    assert r.status_code == 200 and r.json()["has_file"] is False
    g = pg.client.get(f"/api/v1/b/{b}/returns/{inst}/lock-file", headers=as_user("alice"))
    assert g.status_code == 409 and error_code(g) == "no_file"


def test_a_direct_status_change_without_the_event_is_still_refused_by_the_database(lk):
    from sqlalchemy.exc import DBAPIError

    pg, b, inst, *_ = lk
    with pytest.raises(DBAPIError):
        with pg.owner.execution_options(isolation_level="READ COMMITTED").begin() as c:
            c.execute(text("select set_config('app.tenant_id', :b, true)"), {"b": str(b)})
            c.execute(text("update filing.return_instances set status = 'filed_locked' where id = :i"), {"i": inst})


# -- Filed outside Kartaa (issue #424) -------------------------------------------------------------------------------


def completed(pg, b, inst, sub="alice", arn="AA1911260000009", on="2026-11-14"):
    return pg.client.post(f"/api/v1/b/{b}/returns/{inst}/completed", headers=as_user(sub), json={"filed_on": on, "arn": arn})


def gstr3b(pg, b):
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    return next(x["instance_id"] for x in rows if x["form"] == "GSTR3B" and x["period"] == "2026-10")


def test_a_gstr3b_filed_outside_kartaa_is_marked_filed_with_its_arn(lk):
    pg, b, _, *_ = lk
    inst = gstr3b(pg, b)
    r = completed(pg, b, inst)
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "filed_locked", "filed_on": "2026-11-14", "arn": "AA1911260000009"}
    assert instance_status(pg, inst) == "filed_locked"
    rows = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    mine = next(x for x in rows if x["instance_id"] == inst)
    assert (mine["status"], mine["arn"]) == ("filed_locked", "AA1911260000009")
    [ev] = pg.owner.connect().execute(text("select * from filing.instance_events where kind = 'filed'")).all()
    assert ev.reason == "Filed outside Kartaa" and ev.snapshot_id is None
    assert scalar(pg.owner, "select data->>'form' from platform.audit_log where action = 'returns.filed_outside'") == "GSTR3B"
    assert error_code(completed(pg, b, inst)) == "period_not_open"  # once only
    assert unlock(pg, b, inst).status_code == 200  # the owner can take it back, and mark it again
    assert completed(pg, b, inst).status_code == 200


def test_a_gstr1_filed_outside_kartaa_locks_with_the_reason_even_without_a_file(lk):
    pg, b, inst, *_ = lk
    r = completed(pg, b, inst)
    assert r.status_code == 200, r.text
    assert instance_status(pg, inst) == "filed_locked"
    snap = pg.owner.connect().execute(
        text("select changed_since_export, accept_reason from filing.return_snapshots where purpose = 'lock'")
    ).one()
    assert (snap.changed_since_export, snap.accept_reason) == (True, "Filed outside Kartaa")


@pytest.mark.parametrize(
    "body, code",
    [
        ({"filed_on": "2026-11-14", "arn": "  "}, "arn_invalid"),
        ({"filed_on": "2026-11-16", "arn": "A1"}, "filed_on_future"),  # today is frozen at 15 November
        ({"filed_on": "2026-10-30", "arn": "A1"}, "filed_on_before_period"),
    ],
)
def test_marking_a_gstr3b_completed_checks_the_date_and_arn(lk, body, code):
    pg, b, _, *_ = lk
    inst = gstr3b(pg, b)
    r = pg.client.post(f"/api/v1/b/{b}/returns/{inst}/completed", headers=as_user("alice"), json=body)
    assert r.status_code == 422 and error_code(r) == code, r.text
    assert instance_status(pg, inst) == "open"


def test_who_may_mark_completed_and_another_business_gets_404(lk):
    pg, b, _, *_ = lk
    inst = gstr3b(pg, b)
    seed_member(pg, b, "bill", "billing")
    assert completed(pg, b, inst, "bill").status_code in (403, 404)
    other = new_business(pg, "mallory")
    assert pg.client.post(f"/api/v1/b/{other}/returns/{inst}/completed", headers=as_user("mallory"),
                          json={"filed_on": "2026-11-14", "arn": "A1"}).status_code == 404  # fmt: skip
    assert pg.client.post(f"/api/v1/b/{b}/returns/not-a-uuid/completed", headers=as_user("alice"),
                          json={"filed_on": "2026-11-14", "arn": "A1"}).status_code == 404  # fmt: skip
    assert instance_status(pg, inst) == "open"
    seed_member(pg, b, "cathy", "ca")
    assert completed(pg, b, inst, "cathy").status_code == 200  # a CA may, as with marking filed
