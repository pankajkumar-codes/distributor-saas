"""The stock ledger on PostgreSQL as app_rw with FORCE row-level security (R2-M3).

Insert-only movements, a derived balance, once-only receipts from a confirmed purchase
line, adjustments and reversals, "no stock" that never blocks, and tenant scoping.
The clock is frozen at 2026-11-18 IST. Skipped unless PG_ADMIN_URL is set.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import api as app_api
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.uow import Principal, UnitOfWork

from ..interface import ConfirmedPurchaseLine, NewCatalogItem, receive_confirmed_purchase_line
from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, seed_member, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TODAY = date(2026, 11, 18)
D = Decimal


@pytest.fixture()
def shop(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 18, 12, tzinfo=IST))
    biz = new_business(pg, "alice")
    set_type(pg, biz, "retail")
    return pg, biz


def set_type(pg, biz, kind):
    with pg.owner.connect() as c:
        c.execute(text("update business.profiles set business_type = :t where business_id = :b"),
                  {"t": kind, "b": biz})


def post(pg, path, body=None, sub="alice", key=None):
    return pg.client.post(path, json=body or {}, headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def make_product(pg, biz, code="SOAP-1", sub="alice"):
    body = {"code": code, "name": "Neem soap", "hsn": "3401", "uqc": "PCS", "sale_rate": "45.50",
            "tax_category": "taxable", "rate": {"rate": "18", "valid_from": "2026-04-01"}}
    r = post(pg, f"/api/v1/b/{biz}/products", body, sub=sub)
    assert r.status_code == 201, r.text
    return r.json()


def run(pg, biz, fn, sub="alice"):
    """Call `fn(uow)` in one app_rw transaction bound like a unit of work for `sub` in `biz`."""
    uid = user_id(pg.owner, sub)
    with pg.app_rw.begin() as c:
        ctx(c, uid, biz)
        uow = UnitOfWork(Session(bind=c), Principal(user_sub=sub, request_id="t", user_id=uid, business_id=biz,
                                                    role="owner"), False)
        return fn(uow)


def line(product_id=None, new_item=None, quantity="10", source=None, **kw):
    return ConfirmedPurchaseLine(source_id=source or uuid.uuid4(), source_line_id=kw.pop("line_id", uuid.uuid4()),
                                 quantity=D(quantity), received_on=kw.pop("received_on", TODAY),
                                 product_id=product_id, new_item=new_item, **kw)


def new_item(code="NEW-1", **kw):
    return NewCatalogItem(code=code, name="Fresh item", uqc="PCS", hsn="3401", tax_category="taxable",
                          gst_rate="18", rate_valid_from=date(2026, 4, 1), **kw)


def receive(pg, biz, ln, sub="alice"):
    return run(pg, biz, lambda uow: receive_confirmed_purchase_line(uow, ln, today=TODAY), sub)


def movements_in_db(pg, biz):
    with pg.owner.connect() as c:
        return c.execute(text("select kind, quantity from catalog.stock_movements where business_id = :b"
                              " order by created_at, id"), {"b": biz}).all()


def audit_actions(pg, biz):
    with pg.owner.connect() as c:
        return [a for (a,) in c.execute(text("select action from platform.audit_log where business_id = :b"
                                             " order by at, id"), {"b": biz})]


def stock(pg, biz, sub="alice", **params):
    r = pg.client.get(f"/api/v1/b/{biz}/stock", params=params, headers=as_user(sub))
    assert r.status_code == 200, r.text
    return {i["code"]: i for i in r.json()["items"]}


# --- A confirmed purchase line becomes stock, once ----------------------------------------


def test_a_confirmed_line_into_an_existing_product_adds_one_stock_in_movement(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    ln = line(uuid.UUID(p["id"]), quantity="12.5", unit_cost=D("30.00"))
    got = receive(pg, biz, ln)
    assert (got.created_product, got.already_received, got.price_needed) == (False, False, False)
    assert movements_in_db(pg, biz) == [("purchase_in", D("12.500"))]
    assert stock(pg, biz)["SOAP-1"]["on_hand"] == "12.500"
    assert audit_actions(pg, biz)[-1] == "stock.received"
    with pg.owner.connect() as c:
        row = c.execute(text("select source_type, source_id, source_line_id, unit_cost from catalog.stock_movements"
                             )).one()
    assert row == ("purchase_invoice", ln.source_id, ln.source_line_id, D("30.00"))


def test_a_new_item_is_created_with_its_rate_and_asks_for_a_selling_price(shop):
    pg, biz = shop
    got = receive(pg, biz, line(new_item=new_item(), quantity="4"))
    assert got.created_product and got.price_needed
    item = stock(pg, biz)["NEW-1"]
    assert (item["on_hand"], item["price_needed"], item["sale_rate"], item["no_stock"]) == (
        "4.000", True, "0.00", False)
    assert [i["code"] for i in stock(pg, biz, only="price_needed").values()] == ["NEW-1"]
    # The business names the price per 1 qty with the existing product PATCH; the flag clears.
    p = pg.client.get(f"/api/v1/b/{biz}/products/{got.product_id}", headers=as_user("alice"))
    assert p.json()["price_needed"] is True
    r = pg.client.patch(f"/api/v1/b/{biz}/products/{got.product_id}", json={"sale_rate": "99.00"},
                        headers={**as_user("alice"), "If-Match": str(p.json()["version"])})
    assert r.status_code == 200, r.text
    assert r.json()["price_needed"] is False and r.json()["sale_rate"] == "99.00"
    assert stock(pg, biz)["NEW-1"]["price_needed"] is False
    assert stock(pg, biz, only="price_needed") == {}


def test_a_retry_of_the_same_line_returns_the_same_ids_and_adds_nothing(shop):
    pg, biz = shop
    ln = line(new_item=new_item(), quantity="4")
    first = receive(pg, biz, ln)
    again = receive(pg, biz, ln)
    assert again.already_received and not again.created_product
    assert (again.movement_id, again.product_id) == (first.movement_id, first.product_id)
    assert movements_in_db(pg, biz) == [("purchase_in", D("4.000"))]
    assert audit_actions(pg, biz).count("stock.received") == 1
    # Naming the item again on a retry must not create a second product either.
    assert receive(pg, biz, line(new_item=new_item(), quantity="4", source=ln.source_id, line_id=ln.source_line_id)
                   ).already_received
    other = make_product(pg, biz, code="OTHER-1")
    with pytest.raises(Conflict) as e:
        receive(pg, biz, line(uuid.UUID(other["id"]), source=ln.source_id, line_id=ln.source_line_id))
    assert e.value.code == "source_line_conflict"


@pytest.mark.parametrize("quantity", ["0", "-1", "1.0005", "1e3x", "1000000000000"])
def test_bad_quantities_are_refused_and_nothing_is_written(shop, quantity):
    pg, biz = shop
    p = make_product(pg, biz)
    bad = line(uuid.UUID(p["id"]))
    object.__setattr__(bad, "quantity", quantity if quantity == "1e3x" else D(quantity))
    with pytest.raises(Invalid):
        receive(pg, biz, bad)
    assert movements_in_db(pg, biz) == []


def test_a_float_quantity_is_refused(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    bad = line(uuid.UUID(p["id"]))
    object.__setattr__(bad, "quantity", 1.5)
    with pytest.raises(Invalid) as e:
        receive(pg, biz, bad)
    assert e.value.code == "quantity_invalid"


def test_exactly_one_of_product_and_new_item_and_no_future_dates(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    for bad in (line(), line(uuid.UUID(p["id"]), new_item=new_item())):
        with pytest.raises(Invalid) as e:
            receive(pg, biz, bad)
        assert e.value.code == "product_or_new_item"
    with pytest.raises(Invalid) as e:
        receive(pg, biz, line(uuid.UUID(p["id"]), received_on=date(2026, 11, 19)))
    assert e.value.code == "date_in_future"
    with pytest.raises(Invalid):
        receive(pg, biz, line(uuid.UUID(p["id"]), unit_cost=D("1.234")))
    assert movements_in_db(pg, biz) == []


def test_a_failed_new_item_leaves_no_product_and_no_movement(shop):
    pg, biz = shop
    make_product(pg, biz, code="TAKEN-1")
    with pytest.raises(Invalid):  # the code is taken
        receive(pg, biz, line(new_item=new_item(code="TAKEN-1")))
    assert movements_in_db(pg, biz) == []
    with pg.owner.connect() as c:
        assert c.execute(text("select count(*) from catalog.products where business_id = :b"), {"b": biz}).scalar() == 1


def test_receiving_needs_the_business_type_first(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 18, 12, tzinfo=IST))
    biz = new_business(pg, "alice")  # no business type chosen
    with pytest.raises(Conflict) as e:
        receive(pg, biz, line(new_item=new_item()))
    assert e.value.code == "business_type_required"
    assert movements_in_db(pg, biz) == []


# --- Insert-only ------------------------------------------------------------------------------


def test_a_movement_can_be_neither_updated_nor_deleted_by_anyone(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    receive(pg, biz, line(uuid.UUID(p["id"])))
    for sql in ("update catalog.stock_movements set quantity = 99", "delete from catalog.stock_movements"):
        with pytest.raises(DBAPIError):  # the database owner is stopped by the trigger
            with pg.owner.begin() as c:
                c.execute(text(sql))
        with pytest.raises(DBAPIError):  # app_rw has no grant
            with pg.app_rw.begin() as c:
                ctx(c, user_id(pg.owner, "alice"), biz)
                c.execute(text(sql))
    assert movements_in_db(pg, biz) == [("purchase_in", D("10.000"))]


@pytest.mark.parametrize("values", [
    "'adjustment', 5, null, null",                     # an adjustment needs a reason
    "'purchase_in', -5, null, null",                   # stock-in is positive and needs its source
    "'sale_out', 5, 'sales_invoice', gen_random_uuid()",  # a sale-out is negative
    "'adjustment', 0, null, null",                     # never zero
    "'reversal', -5, null, null",                      # a reversal names what it reverses
])
def test_the_table_refuses_malformed_movements(shop, values):
    pg, biz = shop
    p = make_product(pg, biz)
    kind, qty, stype, sid = values.split(", ", 3)
    with pytest.raises(DBAPIError):
        with pg.owner.begin() as c:
            c.execute(text(
                "insert into catalog.stock_movements (id, business_id, product_id, kind, quantity, occurred_on,"
                " source_type, source_id, source_line_id, created_by) values (gen_random_uuid(), :b, :p,"
                f" {kind}, {qty}, current_date, {stype}, {sid}, case when {sid} is null then null else gen_random_uuid() end,"
                " gen_random_uuid())"), {"b": biz, "p": p["id"]})


# --- Adjustments, reversals, and stock that never blocks ------------------------------------


def test_adjusting_below_zero_is_allowed_and_shows_no_stock(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    receive(pg, biz, line(uuid.UUID(p["id"]), quantity="3"))
    r = post(pg, f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments",
             {"quantity": "-5.250", "reason": "Damaged in storage", "occurred_on": "2026-11-18"})
    assert r.status_code == 201, r.text
    assert (r.json()["kind"], r.json()["quantity"], r.json()["reason"]) == ("adjustment", "-5.250",
                                                                           "Damaged in storage")
    item = stock(pg, biz)["SOAP-1"]
    assert (item["on_hand"], item["no_stock"]) == ("-2.250", True)
    assert list(stock(pg, biz, only="no_stock")) == ["SOAP-1"]
    assert audit_actions(pg, biz)[-1] == "stock.adjusted"


def test_adjustments_need_a_reason_a_decimal_string_and_a_real_date(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    path = f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments"
    ok = {"quantity": "1", "reason": "Count", "occurred_on": "2026-11-18"}
    assert post(pg, path, {**ok, "reason": "  "}).status_code == 422
    assert post(pg, path, {**ok, "quantity": "0"}).status_code == 422
    assert post(pg, path, {**ok, "quantity": "1.2345"}).status_code == 422
    assert post(pg, path, {**ok, "quantity": 2}).status_code == 422  # a JSON number is refused
    assert post(pg, path, {**ok, "occurred_on": "2026-11-19"}).status_code == 422
    assert post(pg, path, {**ok, "extra": 1}).status_code == 422
    assert movements_in_db(pg, biz) == []


def test_an_adjustment_retried_with_its_key_adds_one_movement(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    body = {"quantity": "2", "reason": "Count", "occurred_on": "2026-11-18"}
    a = post(pg, f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments", body, key="same-key")
    b = post(pg, f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments", body, key="same-key")
    assert a.json() == b.json()
    assert movements_in_db(pg, biz) == [("adjustment", D("2.000"))]


def test_a_reversal_cancels_one_movement_and_keeps_the_original(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    got = receive(pg, biz, line(uuid.UUID(p["id"]), quantity="7"))
    path = f"/api/v1/b/{biz}/stock-movements/{got.movement_id}/reversals"
    r = post(pg, path, {"reason": "Wrong quantity typed"})
    assert r.status_code == 201, r.text
    rev = r.json()
    assert (rev["kind"], rev["quantity"], rev["reverses_id"]) == ("reversal", "-7.000", str(got.movement_id))
    assert movements_in_db(pg, biz) == [("purchase_in", D("7.000")), ("reversal", D("-7.000"))]
    assert stock(pg, biz)["SOAP-1"]["on_hand"] == "0.000"
    assert stock(pg, biz)["SOAP-1"]["no_stock"] is True
    again = post(pg, path, {"reason": "Again"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reversed"
    nested = post(pg, f"/api/v1/b/{biz}/stock-movements/{rev['id']}/reversals", {"reason": "Undo the undo"})
    assert nested.status_code == 409 and nested.json()["error"]["code"] == "cannot_reverse_a_reversal"
    assert post(pg, path, {"reason": " "}).status_code == 422
    listed = pg.client.get(f"/api/v1/b/{biz}/products/{p['id']}/stock-movements", headers=as_user("alice")).json()
    by_id = {m["id"]: m for m in listed["items"]}
    assert by_id[str(got.movement_id)]["reversed_by_id"] == rev["id"]
    assert [m["kind"] for m in listed["items"]] == ["reversal", "purchase_in"]  # newest first
    assert audit_actions(pg, biz)[-1] == "stock.reversed"


def test_quantities_add_up_exactly(shop):
    """0.1 + 0.2 is 0.300 in the ledger, with no binary rounding anywhere."""
    pg, biz = shop
    p = make_product(pg, biz)
    for q in ("0.1", "0.2"):
        receive(pg, biz, line(uuid.UUID(p["id"]), quantity=q))
    assert stock(pg, biz)["SOAP-1"]["on_hand"] == "0.300"


def test_a_product_with_no_movements_has_zero_on_hand_and_no_stock(shop):
    pg, biz = shop
    make_product(pg, biz)
    item = stock(pg, biz)["SOAP-1"]
    assert (item["on_hand"], item["no_stock"], item["price_needed"]) == ("0.000", True, False)


# --- Tenant scoping and permissions ----------------------------------------------------------


def test_another_business_sees_none_of_it_and_cannot_write_to_it(shop):
    pg, biz = shop
    p = make_product(pg, biz)
    got = receive(pg, biz, line(uuid.UUID(p["id"]), quantity="5"))
    other = new_business(pg, "mallory")
    set_type(pg, other, "distributor")
    assert stock(pg, other, sub="mallory") == {}
    # Mallory names Alice's business in the path: not a member, so 404.
    assert pg.client.get(f"/api/v1/b/{biz}/stock", headers=as_user("mallory")).status_code == 404
    # Mallory uses her own business with Alice's object ids: the rows are not found.
    mine = f"/api/v1/b/{other}"
    assert pg.client.get(f"{mine}/products/{p['id']}/stock-movements", headers=as_user("mallory")).status_code == 404
    adj = {"quantity": "1", "reason": "x", "occurred_on": "2026-11-18"}
    assert post(pg, f"{mine}/products/{p['id']}/stock-adjustments", adj, sub="mallory").status_code == 404
    assert post(pg, f"{mine}/stock-movements/{got.movement_id}/reversals", {"reason": "x"},
                sub="mallory").status_code == 404
    with pytest.raises(Deny):  # the interface, too, finds neither Alice's product nor movement
        receive(pg, other, line(uuid.UUID(p["id"])), sub="mallory")
    assert movements_in_db(pg, biz) == [("purchase_in", D("5.000"))]


def test_stock_follows_catalog_permissions_billing_may_change_it_and_ca_may_only_read(shop):
    """No new permission: stock reads are catalog.view and writes are catalog.edit (owner, admin, billing)."""
    pg, biz = shop
    p = make_product(pg, biz)
    got = receive(pg, biz, line(uuid.UUID(p["id"])))
    adj = {"quantity": "1", "reason": "x", "occurred_on": "2026-11-18"}
    seed_member(pg, biz, "carl", "ca")
    assert pg.client.get(f"/api/v1/b/{biz}/stock", headers=as_user("carl")).status_code == 200
    assert pg.client.get(f"/api/v1/b/{biz}/products/{p['id']}/stock-movements",
                         headers=as_user("carl")).status_code == 200
    assert post(pg, f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments", adj, sub="carl").status_code == 404
    assert post(pg, f"/api/v1/b/{biz}/stock-movements/{got.movement_id}/reversals", {"reason": "x"},
                sub="carl").status_code == 404
    assert movements_in_db(pg, biz) == [("purchase_in", D("10.000"))]
    seed_member(pg, biz, "bill", "billing")
    assert post(pg, f"/api/v1/b/{biz}/products/{p['id']}/stock-adjustments", adj, sub="bill").status_code == 201
    assert audit_actions(pg, biz)[-1] == "stock.adjusted"


def test_every_stock_route_needs_the_business_type(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 18, 12, tzinfo=IST))
    biz = new_business(pg, "alice")  # none chosen
    p = make_product(pg, biz)
    base = f"/api/v1/b/{biz}"
    adj = {"quantity": "1", "reason": "x", "occurred_on": "2026-11-18"}
    replies = [
        pg.client.get(f"{base}/stock", headers=as_user("alice")),
        pg.client.get(f"{base}/products/{p['id']}/stock-movements", headers=as_user("alice")),
        post(pg, f"{base}/products/{p['id']}/stock-adjustments", adj),
        post(pg, f"{base}/stock-movements/{uuid.uuid4()}/reversals", {"reason": "x"}),
    ]
    assert [(r.status_code, r.json()["error"]["code"]) for r in replies] == [(409, "business_type_required")] * 4
    # The R1 product routes are not behind it: a filing-only business keeps its catalog.
    assert pg.client.get(f"{base}/products", headers=as_user("alice")).status_code == 200
