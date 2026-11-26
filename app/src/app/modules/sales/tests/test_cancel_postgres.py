"""Cancelling an issued invoice (#456): only while its return is open, never with a credit note, never twice; the
invoice row never changes, its number stays used, it leaves the supply lines and Table 13 counts it, its stock comes back.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user
from .test_credit_notes_postgres import invoice, note, returned, state
from .test_finalize_live_postgres import flip_live, live  # noqa: F401
from .test_finalize_postgres import fin, ready_draft, shop, switch  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def cancel(pg, biz, doc_id, body, sub="alice", key=None):
    return pg.client.post(f"/api/v1/b/{biz}/documents/{doc_id}/cancel", json=body,
                          headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


MISTAKE = {"reason": "raised_in_error", "declared_not_delivered": True}


def stock_rows(pg, doc_id):
    with pg.owner.connect() as c:
        return c.execute(text(
            "select m.kind, m.quantity from catalog.stock_movements m where m.source_id = :d or m.reverses_id in"
            " (select id from catalog.stock_movements where source_id = :d) order by m.kind"), {"d": doc_id}).all()


def test_a_practice_invoice_is_cancelled_once_its_stock_comes_back_and_it_takes_no_note(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, qty="3")
    r = cancel(pg, biz, inv["id"], MISTAKE)
    assert r.status_code == 200, r.text
    assert r.json()["cancel_reason"] == "raised_in_error" and r.json()["doc_number"] == inv["doc_number"]
    assert [(k, str(q)) for k, q in stock_rows(pg, inv["id"])] == [("reversal", "3.000"), ("sale_out", "-3.000")]
    got = pg.client.get(f"/api/v1/b/{biz}/documents/{inv['id']}", headers=as_user("alice")).json()
    assert got["cancel_reason"] == "raised_in_error" and got["doc_total"] == inv["doc_total"]  # the row is unchanged
    assert state(pg, biz, inv["id"]).json()["cancelled"] is True
    r = cancel(pg, biz, inv["id"], MISTAKE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_cancelled"
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = note(pg, biz, inv["id"], returned(line, "1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "invoice_cancelled"
    with pg.owner.connect() as c:
        audit = c.execute(text("select action, data from platform.audit_log where target_id = :d order by id"),
                          {"d": inv["id"]}).all()
        with pytest.raises(Exception, match="insert-only"):
            c.execute(text("delete from sales.document_cancellations where document_id = :d"), {"d": inv["id"]})
    assert audit[-1].action == "invoice.cancelled" and audit[-1].data["stock_reversals"] == 1


@pytest.mark.parametrize("body, code", [
    ({"reason": "raised_in_error"}, "declaration_required"),
    ({"reason": "did_not_happen", "declared_not_delivered": False}, "declaration_required"),
    ({"reason": "raised_in_error", "declared_not_delivered": True, "duplicate_of": "PR-0001"}, "duplicate_of_invalid"),
])
def test_without_the_declaration_nothing_is_cancelled(shop, body, code):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    r = cancel(pg, biz, inv["id"], body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    with pg.owner.connect() as c:
        assert c.execute(text("select count(*) from sales.document_cancellations")).scalar() == 0
    assert [k for k, _ in stock_rows(pg, inv["id"])] == ["sale_out"]


def test_a_duplicate_needs_no_declaration_and_the_same_key_cancels_once(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    body = {"reason": "duplicate", "duplicate_of": "PR-0007"}
    first = cancel(pg, biz, inv["id"], body, key="k-1")
    again = cancel(pg, biz, inv["id"], body, key="k-1")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len(stock_rows(pg, inv["id"])) == 2


def test_an_invoice_with_a_credit_note_can_not_be_cancelled(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    made = note(pg, biz, inv["id"], returned(line, "1")).json()
    r = cancel(pg, biz, inv["id"], MISTAKE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "has_credit_note"
    assert made["doc_number"] in r.json()["error"]["message"]
    r = cancel(pg, biz, made["id"], MISTAKE)  # a credit note is not cancelled this way
    assert r.status_code == 404


def test_roles_other_businesses_and_the_switch(shop):  # noqa: F811
    pg, biz, other = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    assert cancel(pg, biz, inv["id"], MISTAKE, sub="cathy").status_code == 404  # the CA reads, never cancels
    assert cancel(pg, other, inv["id"], MISTAKE, sub="bob").status_code == 404
    switch(pg, False)
    assert cancel(pg, biz, inv["id"], MISTAKE).status_code == 404
    switch(pg, True)
    assert cancel(pg, biz, inv["id"], MISTAKE, sub="bill").status_code == 200  # billing


def test_a_live_cancel_leaves_the_supply_lines_counts_in_table_13_and_is_closed_once_the_return_is_filed(live):  # noqa: F811
    pg, biz = live
    flip_live(pg, True)
    kept = fin(pg, biz, ready_draft(pg, biz)).json()
    gone = fin(pg, biz, ready_draft(pg, biz)).json()
    r = cancel(pg, biz, gone["id"], MISTAKE)
    assert r.status_code == 200, r.text
    with pg.owner.connect() as c:
        numbers = c.execute(text("select distinct doc_number from sales.v_filing_lines")).scalars().all()
        cancelled = c.execute(text("select doc_number from sales.v_cancelled_documents")).scalars().all()
    assert numbers == [kept["doc_number"]] and cancelled == [gone["doc_number"]]
    third = fin(pg, biz, ready_draft(pg, biz)).json()
    with pg.owner.connect() as c:
        c.execute(text("set session_replication_role = replica"))  # as test_finalize_live: skip the filed-event guard
        c.execute(text("update filing.return_instances set status = 'filed_locked' where id = (select"
                       " return_instance_id from sales.documents where id = :d)"), {"d": third["id"]})
        c.execute(text("set session_replication_role = default"))
    r = cancel(pg, biz, third["id"], MISTAKE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "return_filed", r.text
