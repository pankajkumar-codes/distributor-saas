"""Table 13 (documents issued) on PostgreSQL, through the routes and the real view: what is suggested, confirmation versions,
C-08, staleness, tenant and role rules, and the file and snapshot a confirmation reaches (issue #353). Made-up data.
Skipped unless PG_ADMIN_URL is set."""

import json
import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from platform_common import jobs

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member
from .test_gstr1_from_invoices_postgres import doc  # noqa: F401
from .test_gstr1_from_invoices_postgres import real  # noqa: F401

import app.modules.filing.tests.test_gstr1_from_invoices_postgres as shop

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def seeded(real, *numbers):  # noqa: F811
    """The October 2026 return of a business with these live invoices (and one practice invoice). Returns pg, biz, queue, id."""
    pg, biz, queue = real
    shop.GSTIN = scalar(pg.owner, "select gstin from business.profiles where business_id = :b", b=biz)
    rows = pg.client.get(f"/api/v1/b/{biz}/returns", params={"fy": "2026-27"}, headers=as_user("alice")).json()["returns"]
    inst_id = next(x["instance_id"] for x in rows if x["form"] == "GSTR1" and x["period"] == "2026-10")
    inst = SimpleNamespace(id=uuid.UUID(inst_id))
    for n, number in enumerate(numbers, 3):
        doc(pg, biz, inst, number, date(2026, 10, n))
    doc(pg, biz, inst, "PRACTICE-9", date(2026, 10, 20), practice=True)
    return pg, biz, queue, inst_id


def url(biz, inst_id, tail="table13"):
    return f"/api/v1/b/{biz}/returns/{inst_id}/{tail}"


def get(pg, biz, inst_id, user="alice"):
    return pg.client.get(url(biz, inst_id), headers=as_user(user))


def put(pg, biz, inst_id, rows, user="alice"):
    return pg.client.put(url(biz, inst_id), headers=as_user(user), json={"rows": rows})


def echo(rows):
    return [{k: r[k] for k in ("nature", "from_no", "to_no", "total_issued", "cancelled", "counted", "manual")} for r in rows]


def findings(pg, biz, inst_id):
    r = pg.client.get(url(biz, inst_id, ""), headers=as_user("alice")).json()
    return [f for f in r["findings"] if f["code"] == "C-08"]


def make_ready(pg, biz, inst_id):
    """Everything an export needs except Table 13: the CA warning accepted and the period gate confirmed."""
    ok = pg.client.post(url(biz, inst_id, "check-acceptances"), headers=as_user("alice"),
                        json={"check_code": "C-16", "note": "CA rules still open; test"})
    assert ok.status_code == 200, ok.text
    for item in ("purchases_uploaded", "invoices_in_portal"):
        g = pg.client.put(f"/api/v1/b/{biz}/period-gate", headers=as_user("alice"),
                          json={"kind": "month", "start": "2026-10-01", "item": item, "confirmed": True})
        assert g.status_code == 200, g.text


def test_the_rows_come_from_live_documents_only_and_c08_blocks_until_they_are_confirmed(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1", "INV-2", "INV-4")
    t = get(pg, biz, inst_id).json()
    assert t["applies"] and t["required"] and not t["confirmed"] and not t["stale"] and t["version"] is None
    (r,) = t["rows"]
    assert (r["nature"], r["from_no"], r["to_no"], r["total_issued"], r["cancelled"], r["missing"], r["source"]) == (
        1, "INV-1", "INV-4", 3, 0, 1, "own_live")  # fmt: skip
    assert r["net_issue"] == 3 and not r["manual"] and not r["needs_ca_check"]  # the practice invoice is nowhere
    (f,) = findings(pg, biz, inst_id)
    assert f["level"] == "block" and not f["needs_ca_check"]
    assert put(pg, biz, inst_id, echo(t["rows"])).json()["confirmed"]
    assert findings(pg, biz, inst_id) == []


def test_confirming_twice_is_one_version_and_a_change_is_the_next_and_old_versions_stay(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1", "INV-2")
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    a, b = put(pg, biz, inst_id, rows).json(), put(pg, biz, inst_id, rows).json()
    assert a["version"] == b["version"] == 1 and a["confirmed_at"] == b["confirmed_at"]
    rows[0]["cancelled"] = 1  # the person says one of the two was cancelled
    c = put(pg, biz, inst_id, rows).json()
    assert c["version"] == 2 and c["rows"][0]["net_issue"] == 1
    assert scalar(pg.owner, "select count(*) from filing.table13_confirmations") == 2
    assert scalar(pg.owner, "select count(*) from filing.table13_rows") == 2  # one row per version: version 1 is unchanged
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'return.table13_confirmed'") == 2
    assert get(pg, biz, inst_id).json()["rows"][0]["cancelled"] == 1


def test_a_document_added_after_confirming_makes_it_stale_and_c08_comes_back_with_the_edits_kept(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1", "INV-2")
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    rows.append({"nature": 6, "from_no": "RV-1", "to_no": "RV-2", "total_issued": 2, "cancelled": 0, "counted": True, "manual": True})
    assert put(pg, biz, inst_id, rows).json()["confirmed"]
    doc(pg, biz, SimpleNamespace(id=uuid.UUID(inst_id)), "INV-3", date(2026, 10, 9))
    t = get(pg, biz, inst_id).json()
    assert t["stale"] and not t["confirmed"] and t["version"] == 1
    assert [(r["nature"], r["from_no"], r["to_no"], r["manual"]) for r in t["rows"]] == [
        (1, "INV-1", "INV-3", False), (6, "RV-1", "RV-2", True)]  # fmt: skip
    assert len(findings(pg, biz, inst_id)) == 1
    again = put(pg, biz, inst_id, echo(t["rows"])).json()
    assert again["confirmed"] and again["version"] == 2 and not findings(pg, biz, inst_id)


def test_bad_rows_and_rows_that_are_not_suggestions_are_refused_and_nothing_is_written(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1", "INV-2")
    good = echo(get(pg, biz, inst_id).json()["rows"])
    bad = put(pg, biz, inst_id, [{**good[0], "cancelled": 3}])
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "table13_row_invalid"
    moved = put(pg, biz, inst_id, [{**good[0], "to_no": "INV-9"}])  # from and to are never edited on a suggested row
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "table13_not_current"
    assert pg.client.put(url(biz, inst_id), headers=as_user("alice"), json={"rows": [{**good[0], "extra": 1}]}).status_code == 422
    assert scalar(pg.owner, "select count(*) from filing.table13_confirmations") == 0


def test_a_row_not_counted_is_kept_but_stays_out_of_the_file_and_c08_asks_again_when_none_is_counted(real):  # noqa: F811
    pg, biz, queue, inst_id = seeded(real, "INV-1", "INV-2")
    make_ready(pg, biz, inst_id)
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    rows.append({"nature": 1, "from_no": "AMZ-1", "to_no": "AMZ-5", "total_issued": 5, "cancelled": 0, "counted": False, "manual": True})
    put(pg, biz, inst_id, rows)
    job = pg.client.post(url(biz, inst_id, "exports"), headers=as_user("alice"))
    assert job.status_code == 202, job.text
    queue.drain(jobs.handle_message)
    sid = scalar(pg.owner, "select snapshot_id from filing.export_files limit 1")
    lines = pg.owner.connect().execute(text("select from_no, to_no from filing.snapshot_lines where section = 'docs'")).all()
    assert [tuple(x) for x in lines] == [("INV-1", "INV-2")] and sid  # the marketplace series was not counted
    nothing = [{**r, "counted": False} for r in rows]
    t = put(pg, biz, inst_id, nothing).json()
    assert t["confirmed"] and len(findings(pg, biz, inst_id)) == 1  # confirmed, but nothing counted is still empty


def test_the_json_carries_the_confirmed_rows_in_the_real_files_layout(real):  # noqa: F811
    from platform_common.storage import get_store

    pg, biz, queue, inst_id = seeded(real, "INV-1", "INV-2", "INV-3")
    make_ready(pg, biz, inst_id)
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    rows[0]["cancelled"] = 1
    put(pg, biz, inst_id, rows)
    job = pg.client.post(url(biz, inst_id, "exports"), headers=as_user("alice")).json()["job_id"]
    queue.drain(jobs.handle_message)
    status = pg.client.get(url(biz, inst_id, f"exports/{job}"), headers=as_user("alice")).json()
    assert status["status"] == "ready" and not any("Table 13" in n for n in status["not_in_file"])
    key = scalar(pg.owner, "select object_key from filing.export_files where part_no = 1")
    data = json.loads(get_store().get_bytes(biz, key))
    slots = data["doc_issue"]["doc_det"]
    assert [s["doc_num"] for s in slots] == list(range(1, 13))
    assert slots[0]["docs"] == [{"cancel": 1, "num": 1, "totnum": 3, "from": "INV-1", "to": "INV-3", "net_issue": 2}]
    assert all(s["docs"] == [] for s in slots[1:])


def test_who_may_read_or_confirm_and_which_business(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1")
    seed_member(pg, biz, "bill", "billing")
    seed_member(pg, biz, "cathy", "ca")
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    assert get(pg, biz, inst_id, "bill").status_code in (403, 404)
    assert put(pg, biz, inst_id, rows, "bill").status_code in (403, 404)
    assert put(pg, biz, inst_id, rows, "cathy").status_code == 200  # a CA prepares returns
    other = new_business(pg, "mallory")
    assert pg.client.get(url(other, inst_id), headers=as_user("mallory")).status_code in (403, 404)  # not their return
    assert pg.client.put(url(other, inst_id), headers=as_user("mallory"), json={"rows": rows}).status_code in (403, 404)
    assert get(pg, biz, inst_id, "mallory").status_code in (403, 404)
    assert scalar(pg.owner, "select count(*) from filing.table13_confirmations") == 1


def test_a_return_with_nothing_in_tables_4_to_10_needs_no_table_13(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real)
    t = get(pg, biz, inst_id).json()
    assert t["applies"] and not t["required"] and t["rows"] == [] and findings(pg, biz, inst_id) == []


def test_a_locked_return_cannot_be_changed_and_keeps_its_rows_in_the_lock_snapshot(real):  # noqa: F811
    pg, biz, queue, inst_id = seeded(real, "INV-1", "INV-2")
    make_ready(pg, biz, inst_id)
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    put(pg, biz, inst_id, rows)
    pg.client.post(url(biz, inst_id, "exports"), headers=as_user("alice"))
    queue.drain(jobs.handle_message)
    done = pg.client.post(url(biz, inst_id, "filed"), headers=as_user("alice"), json={"filed_on": "2026-11-10", "arn": "AA1910260000001"})
    assert done.status_code == 200 and not done.json()["changed_since_export"], done.text
    locked = pg.client.put(url(biz, inst_id), headers=as_user("alice"), json={"rows": [{**rows[0], "cancelled": 1}]})
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "return_not_open"
    purposes = pg.owner.connect().execute(
        text("select s.purpose, l.from_no, l.to_no, l.total_count from filing.snapshot_lines l join filing.return_snapshots s"
             " on s.id = l.snapshot_id where l.section = 'docs' order by s.purpose")).all()
    assert [tuple(x) for x in purposes] == [("export", "INV-1", "INV-2", 2), ("lock", "INV-1", "INV-2", 2)]


def test_a_confirmation_changed_after_the_export_is_a_difference_at_lock_time(real):  # noqa: F811
    pg, biz, queue, inst_id = seeded(real, "INV-1", "INV-2")
    make_ready(pg, biz, inst_id)
    rows = echo(get(pg, biz, inst_id).json()["rows"])
    put(pg, biz, inst_id, rows)
    pg.client.post(url(biz, inst_id, "exports"), headers=as_user("alice"))
    queue.drain(jobs.handle_message)
    rows[0]["cancelled"] = 1
    put(pg, biz, inst_id, rows)  # the build is the same, the file would not be
    ch = pg.client.get(url(biz, inst_id, "changes"), headers=as_user("alice")).json()
    assert ch["difference"]["summaries"] == ["docs"]
    refused = pg.client.post(url(biz, inst_id, "filed"), headers=as_user("alice"), json={"filed_on": "2026-11-10", "arn": "AA1910260000001"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "changed_since_export"


def test_the_table_13_tables_are_insert_only(real):  # noqa: F811
    pg, biz, _, inst_id = seeded(real, "INV-1")
    put(pg, biz, inst_id, echo(get(pg, biz, inst_id).json()["rows"]))
    for sql in ("update filing.table13_rows set total_count = 9", "delete from filing.table13_rows",
                "update filing.table13_confirmations set version = 9", "delete from filing.table13_confirmations",
                "truncate filing.table13_rows"):  # fmt: skip
        with pytest.raises(DBAPIError):
            with pg.owner.begin() as c:
                c.execute(text(sql))
