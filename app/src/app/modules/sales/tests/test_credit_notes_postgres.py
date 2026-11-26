"""Credit notes (#456): made from an issued invoice, by quantity (goods returned) or by amount, never more than what
is left on a line, the closing note taking the exact remainder, practice notes in their own PR-CN- series.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, scalar
from .test_drafts_api_postgres import create, make_customer, make_product
from .test_finalize_live_postgres import flip_live, live  # noqa: F401
from .test_finalize_postgres import fin, ready_draft, shop, switch  # noqa: F401

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def invoice(pg, biz, qty="3", price="0.50", lines=1):
    """A practice invoice of `lines` lines, each `qty` at `price` (18%, a registered buyer in the same state)."""
    cust = make_customer(pg, biz)
    body = {"customer_id": cust, "lines": [
        {"product_id": make_product(pg, biz, code=f"P-{uuid.uuid4().hex[:6]}", hsn="340111"), "quantity": qty,
         "unit_price": price} for _ in range(lines)]}
    r = create(pg, biz, body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["ready"], d["computation"]["blocks"]
    r = fin(pg, biz, d)
    assert r.status_code == 200, r.text
    return r.json()


def state(pg, biz, doc_id, sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/documents/{doc_id}/credit", headers=as_user(sub))


def note(pg, biz, doc_id, body, sub="alice", key=None):
    return pg.client.post(f"/api/v1/b/{biz}/documents/{doc_id}/credit-notes", json=body,
                          headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def returned(line_id, qty, stock="restock"):
    return {"reason": "goods_returned", "stock_treatment": stock, "lines": [{"original_line_id": line_id, "quantity": qty}]}


def taxes_of(pg, doc_id):
    with pg.owner.connect() as c:
        return {r.component: r.amount for r in c.execute(text(
            "select t.component, sum(t.amount) as amount from sales.document_line_taxes t join sales.document_lines l"
            " on l.id = t.line_id where l.document_id = :d group by t.component"), {"d": doc_id})}


def test_three_partial_notes_credit_exactly_the_invoice_and_the_last_takes_the_remainder(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, price="0.20")  # 3 x 0.20: taxable 0.60, IGST 0.11 (0.108 rounded) to the other-state buyer
    s = state(pg, biz, inv["id"]).json()
    line = s["lines"][0]["original_line_id"]
    assert s["remaining_total"] == inv["doc_total"] and s["lines"][0]["remaining_quantity"] == "3"
    made = []
    for _ in range(3):
        r = note(pg, biz, inv["id"], returned(line, "1"))
        assert r.status_code == 201, r.text
        made.append(r.json())
    assert [n["doc_number"] for n in made] == ["PR-CN-0001", "PR-CN-0002", "PR-CN-0003"]
    assert all(n["kind"] == "credit_note" and n["is_practice"] and n["original_document_id"] == inv["id"]
               and n["reason_code"] == "goods_returned" and n["supply_class"] == "CDNR" for n in made)
    assert [n["taxable_total"] for n in made] == ["0.20", "0.20", "0.20"]
    assert [taxes_of(pg, n["id"]) for n in made] == [{"IGST": Decimal("0.04")}] * 2 + [{"IGST": Decimal("0.03")}]
    assert sum(Decimal(n["doc_total"]) for n in made) == Decimal(inv["doc_total"])
    s = state(pg, biz, inv["id"]).json()
    assert s["remaining_total"] == "0.00" and len(s["notes"]) == 3
    r = note(pg, biz, inv["id"], returned(line, "1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "line_fully_credited"
    # The invoice itself is untouched, and its number series is not the notes'.
    with pg.owner.connect() as c:
        assert c.execute(text("select doc_total from sales.documents where id = :d"), {"d": inv["id"]}).scalar() \
            == Decimal(inv["doc_total"])
        moves = c.execute(text("select kind, quantity from catalog.stock_movements where source_type ="
                               " 'sales_credit_note' order by created_at")).all()
        audit = c.execute(text("select data from platform.audit_log where action = 'credit_note.issued'"
                               " order by id")).scalars().all()
    assert [(m.kind, m.quantity) for m in moves] == [("return_in", Decimal("1.000"))] * 3
    assert audit[0]["original_number"] == inv["doc_number"] and audit[0]["practice"] is True


def test_a_value_note_moves_no_stock_and_can_not_exceed_what_is_left(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, qty="2", price="100.00")  # taxable 200.00
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    body = {"reason": "value_too_high", "lines": [{"original_line_id": line, "taxable": "50.00"}]}
    r = note(pg, biz, inv["id"], body)
    assert r.status_code == 201, r.text
    assert r.json()["taxable_total"] == "50.00" and r.json()["doc_total"] == "59.00"
    too_much = {"reason": "deficient", "lines": [{"original_line_id": line, "taxable": "150.01"}]}
    r = note(pg, biz, inv["id"], too_much)
    assert r.status_code == 422 and r.json()["error"]["code"] == "credit_value_too_high"
    assert scalar(pg.owner, "select count(*) from catalog.stock_movements where source_type = 'sales_credit_note'") == 0
    s = state(pg, biz, inv["id"]).json()["lines"][0]
    assert s["remaining_taxable"] == "150.00" and s["remaining_quantity"] == "2"


def test_returned_and_written_off_records_both_movements(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz, qty="4", price="10.00")
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = note(pg, biz, inv["id"], returned(line, "2", stock="write_off"))
    assert r.status_code == 201, r.text
    with pg.owner.connect() as c:
        rows = c.execute(text("select kind, quantity, source_type from catalog.stock_movements where source_id = :n"
                              " order by kind"), {"n": r.json()["id"]}).all()
    assert [(x.kind, x.quantity, x.source_type) for x in rows] == [
        ("return_in", Decimal("2.000"), "sales_credit_note"), ("written_off", Decimal("-2.000"), "credit_note_write_off")]
    detail = pg.client.get(f"/api/v1/b/{biz}/documents/{r.json()['id']}", headers=as_user("alice")).json()
    assert detail["stock_movements"] == 2


@pytest.mark.parametrize("body, code", [
    ({"reason": "goods_returned", "lines": [{"original_line_id": "L", "quantity": "1"}]}, "stock_treatment_required"),
    ({"reason": "goods_returned", "stock_treatment": "restock", "lines": [{"original_line_id": "L", "quantity": "5"}]},
     "credit_quantity_too_high"),
    ({"reason": "value_too_high", "stock_treatment": "restock", "lines": [{"original_line_id": "L", "taxable": "1"}]},
     "stock_treatment_not_allowed"),
    ({"reason": "value_too_high", "lines": [{"original_line_id": "L", "quantity": "1"}]}, "quantity_or_amount"),
    ({"reason": "goods_returned", "stock_treatment": "restock", "lines": []}, "lines_required"),
    ({"reason": "goods_returned", "stock_treatment": "restock", "lines": [{"original_line_id": "x", "quantity": "1"}]},
     "line_not_on_invoice"),
    ({"reason": "goods_returned", "stock_treatment": "restock", "doc_date": "2099-01-01",
      "lines": [{"original_line_id": "L", "quantity": "1"}]}, "date_in_future"),
    ({"reason": "goods_returned", "stock_treatment": "restock", "doc_date": "2020-01-01",
      "lines": [{"original_line_id": "L", "quantity": "1"}]}, "date_before_invoice"),
])
def test_bad_notes_are_refused_and_write_nothing(shop, body, code):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    for ln in body["lines"]:
        if ln["original_line_id"] == "L":
            ln["original_line_id"] = line
    r = note(pg, biz, inv["id"], body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'credit_note'") == 0
    assert scalar(pg.owner, "select count(*) from sales.drafts where kind = 'credit_note'") == 0


def test_a_reason_outside_section_34_is_a_422(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    r = note(pg, biz, inv["id"], {"reason": "discount", "lines": []})
    assert r.status_code == 422


def test_the_same_key_gives_one_note(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    key = uuid.uuid4().hex
    a, b = note(pg, biz, inv["id"], returned(line, "1"), key=key), note(pg, biz, inv["id"], returned(line, "1"), key=key)
    assert a.status_code == 201 and a.json() == b.json()
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'credit_note'") == 1


def test_two_notes_at_once_can_not_both_credit_the_last_units(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    out = []

    def go():
        out.append(note(pg, biz, inv["id"], returned(line, "3")))

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(r.status_code for r in out) == [201, 422]
    assert [r.json()["error"]["code"] for r in out if r.status_code == 422] == ["line_fully_credited"]
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'credit_note'") == 1


def test_switch_off_roles_and_other_businesses(shop):  # noqa: F811
    pg, biz, other = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    assert state(pg, biz, inv["id"], sub="cathy").status_code == 200  # the CA reads
    assert note(pg, biz, inv["id"], returned(line, "1"), sub="cathy").status_code == 404  # but makes no note
    assert state(pg, biz, inv["id"], sub="bob").status_code == 404
    assert note(pg, other, inv["id"], returned(line, "1"), sub="bob").status_code == 404
    assert state(pg, other, inv["id"], sub="bob").status_code == 404
    r = note(pg, biz, inv["id"], returned(line, "1"), sub="bill")  # billing makes notes
    assert r.status_code == 201, r.text
    assert state(pg, biz, r.json()["id"]).status_code == 404  # a note has no credit state of its own
    switch(pg, False)
    assert note(pg, biz, inv["id"], returned(line, "1")).status_code == 404
    assert scalar(pg.owner, "select count(*) from sales.documents where kind = 'credit_note'") == 1


def test_a_practice_note_never_reaches_filing(shop):  # noqa: F811
    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    assert note(pg, biz, inv["id"], returned(line, "1")).status_code == 201
    assert scalar(pg.owner, "select count(*) from sales.v_filing_lines") == 0


# --- Live notes, behind both switches (test setup only) -------------------------------------------------------------



def test_a_live_note_on_a_live_invoice_takes_a_live_number_and_its_return(live):  # noqa: F811
    pg, biz = live
    flip_live(pg, True)
    r = fin(pg, biz, ready_draft(pg, biz))
    assert r.status_code == 200, r.text
    inv = r.json()
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    r = note(pg, biz, inv["id"], returned(line, "1"))
    assert r.status_code == 201, r.text
    n = r.json()
    assert not n["is_practice"] and n["doc_number"] == "CN000001"  # default CN settings, the FY scope before 26-11
    with pg.owner.connect() as c:
        period = c.execute(text("select i.return_period from sales.documents d join filing.return_instances i"
                                " on i.id = d.return_instance_id where d.id = :d"), {"d": n["id"]}).scalar()
        filing_kinds = c.execute(text("select doc_kind from sales.v_filing_lines order by doc_kind")).scalars().all()
    assert period == "2026-11" and filing_kinds == ["credit_note", "invoice"]


def test_concurrent_live_finalizes_in_a_monthly_series_never_share_a_number(live):  # noqa: F811
    """Staff follow-up from #460: the monthly allocate under two finalizes at once."""
    from datetime import datetime

    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    pg, biz = live
    flip_live(pg, True)
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 27, 12, 0, tzinfo=IST))
    drafts_ = [ready_draft(pg, biz) for _ in range(4)]
    out = []

    def go(d):
        out.append(fin(pg, biz, d))

    ts = [threading.Thread(target=go, args=(d,)) for d in drafts_]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert all(r.status_code == 200 for r in out), [r.text for r in out]
    assert sorted(r.json()["doc_number"] for r in out) == [f"INV-/26-11/{i:04d}" for i in range(1, 5)]


def test_the_note_pdf_names_its_invoice_and_reason_with_two_copies(shop):  # noqa: F811
    from app.modules.sales import document_pdf

    pg, biz, _ = shop
    switch(pg, True)
    inv = invoice(pg, biz)
    line = state(pg, biz, inv["id"]).json()["lines"][0]["original_line_id"]
    made = note(pg, biz, inv["id"], returned(line, "1")).json()
    with pg.owner.connect() as c:
        body = document_pdf.build(c, biz, uuid.UUID(made["id"]))
        invoice_body = document_pdf.build(c, biz, uuid.UUID(inv["id"]))
    assert body["note"] == {"kind": "credit_note", "original_number": inv["doc_number"],
                            "original_date": inv["doc_date"], "reason": "Goods returned"}
    assert body["copies"] == ["Original for Recipient", "Duplicate for Supplier"] and body["due_date"] is None
    assert body["number"] == "PR-CN-0001" and body["totals"]["total"] == made["doc_total"]
    assert invoice_body["note"] is None and len(invoice_body["copies"]) == 3


def test_a_prefix_another_kind_already_used_this_year_is_refused(live):  # noqa: F811
    """Staff review of #463: a credit series CN... exists, then the invoice prefix is renamed to the same CN."""
    pg, biz = live
    flip_live(pg, True)
    with pg.owner.connect() as c:
        c.execute(text("update business.series_settings set prefix = 'CN' where business_id = :b and kind = 'invoice'"),
                  {"b": biz})
        gstin = c.execute(text("select gstin from business.profiles where business_id = :b"), {"b": biz}).scalar()
        c.execute(text("insert into sales.number_series (id, business_id, gstin, kind, fy, month, prefix, width,"
                       " next_value) values (:i, :b, :g, 'credit_note', '2026-27', '', 'CN', 6, 2)"),
                  {"i": uuid.uuid4(), "b": biz, "g": gstin})
    r = fin(pg, biz, ready_draft(pg, biz))
    assert r.status_code == 422 and r.json()["error"]["code"] == "prefix_in_use", r.text
    with pg.owner.connect() as c:
        assert c.execute(text("select count(*) from sales.documents where business_id = :b"), {"b": biz}).scalar() == 0
        with pytest.raises(Exception, match="number_series_prefix_uq"):
            c.execute(text("insert into sales.number_series (id, business_id, gstin, kind, fy, month, prefix, width,"
                           " next_value) values (:i, :b, :g, 'invoice', '2026-27', '', 'cn', 6, 1)"),
                      {"i": uuid.uuid4(), "b": biz, "g": gstin})
