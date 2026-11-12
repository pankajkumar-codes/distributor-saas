"""Finalize F1 (LLD-4 §4; AC4-2, AC4-3, AC4-4, AC4-13): practice documents behind the
off-by-default switch `sales.finalize.enabled` (CEO, 2026-11-09).

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, scalar, seed_member, user_id
from .test_drafts_api_postgres import create, draft_body, make_customer, make_product

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def shop(pg):
    biz = new_business(pg, "alice")
    for sub, role in (("bill", "billing"), ("cathy", "ca"), ("adam", "admin")):
        seed_member(pg, biz, sub, role)
    return pg, biz, new_business(pg, "bob")


def switch(pg, on: bool):
    """Flips the switch as test setup. A new refdata.loads row, as a real load writes, so
    the app's cached refdata snapshot is rebuilt."""
    with pg.owner.connect() as c:
        c.execute(
            text("update refdata.values set value = :v where key = 'sales.finalize.enabled'"),
            {"v": "true" if on else "false"},
        )
        c.execute(
            text(
                "insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)"
                " values (:i, 'test', '{}', 0, 0, 1)"
            ),
            {"i": uuid.uuid4()},
        )


def ready_draft(pg, biz, sub="alice", **extra):
    p = make_product(pg, biz, code=f"P-{uuid.uuid4().hex[:6]}", sub=sub, hsn="340111")  # 6 digits: no band set
    cust = make_customer(pg, biz, sub=sub)
    r = create(pg, biz, draft_body(p, customer_id=cust, **extra), sub=sub)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ready"] is True, d["computation"]["blocks"]
    return d


def fin(pg, biz, d, sub="alice", key=None, version=None):
    return pg.client.post(
        f"/api/v1/b/{biz}/drafts/{d['id']}/finalize",
        headers={
            **as_user(sub),
            "Idempotency-Key": key or uuid.uuid4().hex,
            "If-Match": str(d["version"] if version is None else version),
        },
    )


def counts(pg):
    with pg.owner.connect() as c:
        return c.execute(
            text(
                "select (select count(*) from sales.documents), (select count(*) from sales.document_lines),"
                " (select coalesce(sum(next_value), 0) from sales.number_series),"
                " (select count(*) from platform.audit_log where action = 'document.finalized')"
            )
        ).one()


def test_switch_off_is_a_404_and_issues_no_number(shop):
    pg, biz, _ = shop
    d = ready_draft(pg, biz)
    before = counts(pg)
    r = fin(pg, biz, d)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert counts(pg) == before == (0, 0, 0, 0)  # no document, no series row, no number, no audit
    assert scalar(pg.owner, "select status from sales.drafts where id = :d", d=d["id"]) == "open"


def test_switch_shipped_off(shop):
    pg, _, _ = shop
    assert scalar(pg.owner, "select value from refdata.values where key = 'sales.finalize.enabled'") == "false"


def test_finalize_issues_a_practice_document_and_freezes_the_draft(shop):
    pg, biz, _ = shop
    switch(pg, True)
    d = ready_draft(pg, biz)
    r = fin(pg, biz, d)
    assert r.status_code == 200, r.text
    doc = r.json()
    c = d["computation"]
    assert doc["is_practice"] is True and doc["doc_number"] == "PR-0001" and doc["draft_id"] == d["id"]
    assert (doc["doc_total"], doc["taxable_total"], doc["igst_total"]) == (
        c["doc_total"],
        c["taxable_total"],
        c["igst_total"],
    )
    assert doc["supply_class"] == "B2B" and doc["counterparty_name"] == "Sharma Stores"
    assert pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=as_user("alice")).status_code == 404
    assert counts(pg) == (1, 1, 2, 1)  # one document and line, the series moved 1 -> 2, one audit row
    with pg.owner.connect() as c2:
        assert c2.execute(text("select status from sales.drafts where id = :d"), {"d": d["id"]}).scalar() == "finalized"
        taxes = c2.execute(text("select component, amount::text from sales.document_line_taxes")).all()
        assert taxes == [("IGST", c["lines"][0]["taxes"][0]["amount"])]
        series = c2.execute(text("select kind, prefix, width from sales.number_series")).one()
        assert tuple(series) == ("practice", "PR-", 4)


def test_the_same_draft_twice_gives_one_document(shop):  # AC4-3
    pg, biz, _ = shop
    switch(pg, True)
    d = ready_draft(pg, biz)
    first = fin(pg, biz, d, key="k-1")
    again_same_key = fin(pg, biz, d, key="k-1")
    again_other_key = fin(pg, biz, d, key="k-2")
    assert first.status_code == again_same_key.status_code == again_other_key.status_code == 200
    assert first.json()["id"] == again_same_key.json()["id"] == again_other_key.json()["id"]
    assert counts(pg)[0] == 1 and counts(pg)[2] == 2


def test_consecutive_numbers_and_concurrent_finalizes_never_share_one(shop):  # AC4-2
    pg, biz, _ = shop
    switch(pg, True)
    ds = [ready_draft(pg, biz) for _ in range(4)]
    assert fin(pg, biz, ds[0]).json()["doc_number"] == "PR-0001"
    out, errors = {}, []

    def go(d):
        try:
            r = fin(pg, biz, d)
            out[d["id"]] = (r.status_code, r.json().get("doc_number"))
        except Exception as e:  # noqa: BLE001 - reported below
            errors.append(e)

    threads = [threading.Thread(target=go, args=(d,)) for d in ds[1:]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert sorted(n for _, n in out.values()) == ["PR-0002", "PR-0003", "PR-0004"]
    assert all(s == 200 for s, _ in out.values())


def test_a_blocked_draft_writes_nothing(shop):  # AC4-4
    pg, biz, _ = shop
    switch(pg, True)
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p)).json()  # no buyer chosen: blocked
    assert d["ready"] is False
    r = fin(pg, biz, d)
    assert r.status_code == 422 and r.json()["error"]["code"] == "finalize_blocked"
    assert r.json()["error"]["blocks"]
    assert counts(pg) == (0, 0, 0, 0)


def test_a_failure_after_the_number_is_taken_rolls_the_number_back(shop):  # AC4-4, NF-8
    pg, biz, _ = shop
    switch(pg, True)
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 200
    d = ready_draft(pg, biz)
    with pg.owner.connect() as c:  # deleted after the draft was saved: mark_used refuses
        c.execute(
            text("update catalog.products set status = 'deleted' where id = :p"), {"p": d["lines"][0]["product_id"]}
        )
    r = fin(pg, biz, d)
    assert r.status_code in (409, 422), r.text
    assert counts(pg) == (1, 1, 2, 1)  # next_value still 2: PR-0002 was not used up
    assert scalar(pg.owner, "select status from sales.drafts where id = :d", d=d["id"]) == "open"


def test_stale_version_is_refused(shop):
    pg, biz, _ = shop
    switch(pg, True)
    d = ready_draft(pg, biz)
    r = fin(pg, biz, d, version=d["version"] + 1)
    assert r.status_code == 409 and counts(pg) == (0, 0, 0, 0)


def test_live_numbering_is_refused_until_f2(shop):
    pg, biz, _ = shop
    switch(pg, True)
    d = ready_draft(pg, biz)
    with pg.owner.connect() as c:
        c.execute(
            text(
                "insert into business.series_settings (business_id, kind, prefix, width, practice_mode,"
                " updated_by) values (:b, 'invoice', 'INV-', 4, false, :u)"
            ),
            {"b": biz, "u": user_id(pg.owner, "alice")},
        )
    r = fin(pg, biz, d)
    assert r.status_code == 422 and r.json()["error"]["code"] == "live_numbering_unavailable"
    assert counts(pg) == (0, 0, 0, 0)


@pytest.mark.parametrize("sub", ["cathy", "bob"])  # the CA; the owner of another business
def test_ca_and_other_businesses_get_404(shop, sub):  # AC4-13 (role denials are 404, LLD-0)
    pg, biz, _ = shop
    switch(pg, True)
    d = ready_draft(pg, biz)
    r = fin(pg, biz, d, sub=sub)
    assert r.status_code == 404 and counts(pg) == (0, 0, 0, 0)


def test_another_businesss_draft_id_is_a_404(shop):
    pg, biz, other = shop
    switch(pg, True)
    theirs = ready_draft(pg, other, sub="bob")
    r = pg.client.post(
        f"/api/v1/b/{biz}/drafts/{theirs['id']}/finalize",
        headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex, "If-Match": "1"},
    )
    assert r.status_code == 404 and counts(pg) == (0, 0, 0, 0)


def test_a_practice_document_never_reaches_filing(shop):  # EM, 2026-11-09; TD-7
    pg, biz, _ = shop
    switch(pg, True)
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 200
    with pg.app_rw.connect() as c, c.begin():
        ctx(c, user_id(pg.owner, "alice"), tenant=biz)
        assert c.execute(text("select count(*) from sales.document_lines")).scalar() == 1
        assert c.execute(text("select count(*) from sales.v_filing_lines")).scalar() == 0
    # The view filters on is_practice, not on anything F1 happens to leave empty: the same
    # rows with the flag cleared do show (owner-only setup, past the insert-only trigger).
    with pg.owner.connect() as c:  # a disposable database: the flag is put back anyway
        c.execute(text("set session_replication_role = replica"))
        c.execute(text("update sales.documents set is_practice = false"))
        assert c.execute(text("select count(*) from sales.v_filing_lines")).scalar() == 1
        c.execute(text("update sales.documents set is_practice = true"))
        c.execute(text("set session_replication_role = origin"))


def test_documents_are_insert_only(shop):
    pg, biz, _ = shop
    switch(pg, True)
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 200
    for sql in (
        "update sales.documents set doc_total = 0",
        "delete from sales.document_line_taxes",
        "delete from sales.document_lines",
        "delete from sales.documents",
        "truncate sales.pos_overrides",
        "truncate sales.document_line_taxes",
        "truncate sales.document_lines cascade",
        "truncate sales.documents cascade",
    ):
        with pg.owner.connect() as c, pytest.raises(Exception, match="insert-only"):
            c.execute(text(sql))
    with pg.app_rw.connect() as c, c.begin():
        ctx(c, user_id(pg.owner, "alice"), tenant=biz)
        with pytest.raises(Exception, match="permission denied"):
            c.execute(text("update sales.documents set doc_total = 0"))


def test_a_draft_cannot_be_marked_finalized_without_its_document(shop):
    pg, biz, _ = shop
    d = ready_draft(pg, biz)
    with pg.app_rw.connect() as c, c.begin():
        ctx(c, user_id(pg.owner, "alice"), tenant=biz)
        with pytest.raises(Exception, match="has no document"):
            c.execute(text("update sales.drafts set status = 'finalized' where id = :d"), {"d": d["id"]})
