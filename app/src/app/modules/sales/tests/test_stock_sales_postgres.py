"""Sales from the catalog with stock (R2-M4): the sale takes stock out when it is finalized,
"no stock" warns and never blocks, a price edited on the invoice is kept, tenants stay apart.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member
from .test_drafts_api_postgres import create, make_customer, make_product, put
from .test_finalize_postgres import counts, fin, switch

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def shop(pg):
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "cathy", "ca")
    return pg, biz, new_business(pg, "bob")


def product(pg, biz, **extra):
    return make_product(pg, biz, code=f"P-{uuid.uuid4().hex[:6]}", hsn="340111", **extra)


def stock_in(pg, biz, product_id, quantity, sub="alice"):
    r = pg.client.post(f"/api/v1/b/{biz}/products/{product_id}/stock-adjustments",
                       json={"quantity": quantity, "reason": "Opening count", "occurred_on": "2026-11-01"},
                       headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text


def on_hand(pg, biz, product_id, sub="alice") -> str:
    r = pg.client.get(f"/api/v1/b/{biz}/stock", params={"q": ""}, headers=as_user(sub))
    return {i["product_id"]: i["on_hand"] for i in r.json()["items"]}[product_id]


def draft(pg, biz, p, quantity="2.500", **extra):
    cust = make_customer(pg, biz)
    body = {"lines": [{"product_id": p, "quantity": quantity, **extra.pop("line", {})}], "customer_id": cust, **extra}
    r = create(pg, biz, body)
    assert r.status_code == 201, r.text
    return r.json()


def codes(d, kind="warnings"):
    return [(i["code"], i.get("line_no")) for i in d["computation"][kind]]


def movements(pg):
    with pg.owner.connect() as c:
        return c.execute(text("select kind, quantity, source_type, source_id, source_line_id"
                              " from catalog.stock_movements order by created_at, id")).all()


# --- Creating an invoice from the catalog never stops for stock -----------------------------


def test_a_draft_at_zero_stock_is_created_and_only_warned(shop):
    pg, biz, _ = shop
    p = product(pg, biz)
    d = draft(pg, biz, p)
    assert ("no_stock", 1) in codes(d)
    assert d["ready"] is True and codes(d, "blocks") == []  # nothing stops it: not even finalize later
    assert d["computation"]["doc_total"] != "0.00"


def test_stock_warns_low_when_short_and_stays_silent_when_enough(shop):
    pg, biz, _ = shop
    p = product(pg, biz)
    stock_in(pg, biz, p, "10")
    enough = draft(pg, biz, p, quantity="2.500")
    assert not {c for c, _ in codes(enough)} & {"no_stock", "low_stock"}
    short = draft(pg, biz, p, quantity="12")
    assert ("low_stock", 1) in codes(short) and short["ready"] is True


def test_a_price_edited_on_the_invoice_is_kept_and_the_gst_follows(shop):
    pg, biz, _ = shop
    p = product(pg, biz)  # catalog price 45.50
    plain = draft(pg, biz, p, quantity="2")
    assert plain["lines"][0]["unit_price"] == "45.50"
    edited = draft(pg, biz, p, quantity="2", line={"unit_price": "60.00"})
    assert edited["lines"][0]["unit_price"] == "60.00"
    assert edited["computation"]["taxable_total"] == "120.00"
    assert edited["computation"]["igst_total"] == "21.60"  # 18% of 120.00, from the edited price
    # The catalog price itself did not move.
    got = pg.client.get(f"/api/v1/b/{biz}/products/{p}", headers=as_user("alice")).json()
    assert got["sale_rate"] == "45.50"


def test_a_product_without_a_set_price_needs_one_before_finalize_but_the_draft_saves(shop):
    pg, biz, _ = shop
    p = product(pg, biz)
    with pg.owner.connect() as c:
        # A product made from a purchase line: no selling price and, as there, no MRP to take the rate from (D-107).
        c.execute(text("update catalog.products set price_needed = true, sale_rate = 0, mrp = null where id = :p"),
                  {"p": p})
    d = draft(pg, biz, p)
    assert ("price_not_set", 1) in codes(d, "blocks") and d["ready"] is False
    typed = draft(pg, biz, p, line={"unit_price": "80.00"})
    assert codes(typed, "blocks") == [("mrp_missing", 1)] and typed["ready"] is False  # the price is fine now
    with pg.owner.connect() as c:
        c.execute(text("update catalog.products set mrp = 94.40 where id = :p"), {"p": p})
    from_mrp = draft(pg, biz, p)  # with an MRP the blank rate is 94.40 / 1.18 = 80.00, a set price: no block
    assert codes(from_mrp, "blocks") == [] and from_mrp["lines"][0]["unit_price"] == "80.00"


# --- Finalizing takes stock out, once, and never refuses for stock ---------------------------


def test_finalize_writes_one_sale_out_per_line_and_a_retry_adds_none(shop):
    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    stock_in(pg, biz, p, "10")
    d = draft(pg, biz, p, quantity="2.500")
    assert on_hand(pg, biz, p) == "10.000"  # a draft moves no stock
    first = fin(pg, biz, d, key="k-1")
    assert first.status_code == 200, first.text
    again = fin(pg, biz, d, key="k-2")
    assert again.json()["id"] == first.json()["id"]
    rows = movements(pg)
    assert [(r.kind, r.quantity) for r in rows] == [("adjustment", Decimal("10.000")),
                                                    ("sale_out", Decimal("-2.500"))]
    doc_line = scalar(pg.owner, "select id from sales.document_lines where document_id = :d", d=first.json()["id"])
    assert (rows[1].source_type, str(rows[1].source_id), rows[1].source_line_id) == (
        "sales_invoice", first.json()["id"], doc_line)
    assert on_hand(pg, biz, p) == "7.500"


def test_finalizing_at_zero_or_negative_stock_still_works_and_the_balance_goes_negative(shop):
    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    d = draft(pg, biz, p, quantity="4")
    assert fin(pg, biz, d).status_code == 200
    assert on_hand(pg, biz, p) == "-4.000"
    again = draft(pg, biz, p, quantity="1")
    assert ("no_stock", 1) in codes(again)
    assert fin(pg, biz, again).status_code == 200
    assert on_hand(pg, biz, p) == "-5.000"


def test_two_lines_of_one_product_make_two_movements(shop):
    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    stock_in(pg, biz, p, "10")
    cust = make_customer(pg, biz)
    r = create(pg, biz, {"customer_id": cust, "lines": [{"product_id": p, "quantity": "1"},
                                                         {"product_id": p, "quantity": "2"}]})
    assert fin(pg, biz, r.json()).status_code == 200
    assert [str(m.quantity) for m in movements(pg) if m.kind == "sale_out"] == ["-1.000", "-2.000"]
    assert on_hand(pg, biz, p) == "7.000"


def test_a_failure_while_taking_stock_out_rolls_back_the_invoice_and_its_number(shop, monkeypatch):
    from app.modules.sales import finalize as fz

    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    d = draft(pg, biz, p)

    def boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr(fz, "record_sale_out", boom)
    assert fin(pg, biz, d).status_code == 500
    assert counts(pg) == (0, 0, 0, 0)  # no document, no line, no number used, no audit row
    assert movements(pg) == []
    assert scalar(pg.owner, "select status from sales.drafts where id = :d", d=d["id"]) == "open"


def test_reversing_the_stock_movement_never_edits_the_finalized_invoice(shop):
    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    doc = fin(pg, biz, draft(pg, biz, p, quantity="3")).json()
    sale_out = scalar(pg.owner, "select id from catalog.stock_movements where kind = 'sale_out'")
    r = pg.client.post(f"/api/v1/b/{biz}/stock-movements/{sale_out}/reversals", json={"reason": "Customer returned all"},
                       headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    assert on_hand(pg, biz, p) == "0.000"
    with pg.owner.connect() as c:
        row = c.execute(text("select doc_number, doc_total::text, quantity::text from sales.documents d"
                             " join sales.document_lines l on l.document_id = d.id")).one()
    assert (row[0], row[1], row[2]) == (doc["doc_number"], doc["doc_total"], "3.000")


# --- Tenants and the business type ---------------------------------------------------------------


def test_another_business_sees_none_of_the_sale_out_and_cannot_finalize_it(shop):
    pg, biz, other = shop
    switch(pg, True)
    p = product(pg, biz)
    d = draft(pg, biz, p)
    fin(pg, biz, d)
    sale_out = scalar(pg.owner, "select id from catalog.stock_movements where kind = 'sale_out'")
    assert pg.client.get(f"/api/v1/b/{other}/products/{p}/stock-movements", headers=as_user("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/stock", headers=as_user("bob")).json()["items"] == []
    assert pg.client.post(f"/api/v1/b/{other}/stock-movements/{sale_out}/reversals", json={"reason": "x"},
                          headers={**as_user("bob"), "Idempotency-Key": uuid.uuid4().hex}).status_code == 404
    # Bob drafting with Alice's product id: the product is not found for him.
    r = create(pg, other, {"lines": [{"product_id": p, "quantity": "1"}], "customer_id": None,
                           "cash_buyer": {"state_code": "19"}}, sub="bob")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "product_not_found")
    assert len(movements(pg)) == 1


def test_sales_routes_do_not_need_a_business_type(pg):  # D-095: optional, never blocks
    biz = new_business(pg, "carol", business_type=None)
    base = f"/api/v1/b/{biz}"
    assert pg.client.get(f"{base}/drafts", headers=as_user("carol")).status_code == 200
    made = pg.client.post(f"{base}/drafts", json={"lines": []}, headers={**as_user("carol"),
                                                                       "Idempotency-Key": uuid.uuid4().hex})
    assert made.status_code == 201, made.text
    # A member without the permission still gets the plain 404.
    seed_member(pg, biz, "cathy", "ca")
    assert pg.client.get(f"{base}/drafts", headers=as_user("cathy")).status_code == 404


def test_replacing_a_draft_keeps_working_with_stock_in_play(shop):
    pg, biz, _ = shop
    p = product(pg, biz)
    d = draft(pg, biz, p, quantity="1")
    r = put(pg, biz, d, {"customer_id": d["customer_id"], "lines": [{"product_id": p, "quantity": "5"}]})
    assert r.status_code == 200, r.text
    assert ("no_stock", 1) in codes(r.json())


def test_a_practice_invoice_takes_stock_out_tagged_as_practice_and_its_reversal_keeps_the_tag(shop):
    pg, biz, _ = shop
    switch(pg, True)
    p = product(pg, biz)
    stock_in(pg, biz, p, "10")
    doc = fin(pg, biz, draft(pg, biz, p, quantity="2")).json()
    assert doc["is_practice"] is True
    with pg.owner.connect() as c:
        tags = c.execute(text("select kind, is_practice from catalog.stock_movements order by created_at, id")).all()
    assert [tuple(t) for t in tags] == [("adjustment", False), ("sale_out", True)]
    sale_out = scalar(pg.owner, "select id from catalog.stock_movements where kind = 'sale_out'")
    r = pg.client.post(f"/api/v1/b/{biz}/stock-movements/{sale_out}/reversals", json={"reason": "Test sale"},
                       headers={**as_user("alice"), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201 and r.json()["is_practice"] is True
    path = f"/api/v1/b/{biz}/products/{p}/stock-movements"
    everything = pg.client.get(path, headers=as_user("alice")).json()["items"]
    only_practice = pg.client.get(path, params={"practice": "true"}, headers=as_user("alice")).json()["items"]
    not_practice = pg.client.get(path, params={"practice": "false"}, headers=as_user("alice")).json()["items"]
    assert [m["kind"] for m in everything] == ["reversal", "sale_out", "adjustment"]
    assert [m["kind"] for m in only_practice] == ["reversal", "sale_out"]
    assert [m["kind"] for m in not_practice] == ["adjustment"]

