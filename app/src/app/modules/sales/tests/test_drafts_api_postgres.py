"""Invoice draft routes (LLD-4 §9; AC4-15): create, read, list, PUT with If-Match, delete.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

GSTIN = "27AAPFU0939F1ZV"  # gstin.md's cited example


@pytest.fixture()
def shop(pg):
    biz = new_business(pg, "alice")
    for sub, role in (("bill", "billing"), ("cathy", "ca"), ("adam", "admin")):
        seed_member(pg, biz, sub, role)
    other = new_business(pg, "bob")
    return pg, biz, other


def h(sub="alice", **extra):
    return {**as_user(sub), **extra}


def make_product(pg, biz, code="SOAP-1", sub="alice", **extra):
    body = {"code": code, "name": "Neem soap", "hsn": "3401", "uqc": "PCS", "sale_rate": "45.50",
            "tax_category": "taxable", "rate": {"rate": "18", "valid_from": "2026-04-01"}, **extra}
    r = pg.client.post(f"/api/v1/b/{biz}/products", json=body, headers=h(sub, **{"Idempotency-Key": uuid.uuid4().hex}))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_customer(pg, biz, name="Sharma Stores", sub="alice"):
    body = {"name": name, "gstin": GSTIN, "billing": {"line1": "12 MG Road", "city": "Pune", "pin": "411001"}}
    r = pg.client.post(f"/api/v1/b/{biz}/customers", json=body, headers=h(sub, **{"Idempotency-Key": uuid.uuid4().hex}))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def bare(d):
    return {k: v for k, v in d.items() if k != "computation"}


def draft_body(product, **extra):
    return {"lines": [{"product_id": product, "quantity": "2.500"}], **extra}


def create(pg, biz, body, sub="alice", key=None):
    return pg.client.post(f"/api/v1/b/{biz}/drafts", json=body, headers=h(sub, **{"Idempotency-Key": key or uuid.uuid4().hex}))


def put(pg, biz, d, body, version=None, sub="alice"):
    v = d["version"] if version is None else version
    return pg.client.put(f"/api/v1/b/{biz}/drafts/{d['id']}", json=body, headers=h(sub, **{"If-Match": str(v)}))


def test_create_then_read_with_money_as_strings(shop):
    pg, biz, _ = shop
    p, c = make_product(pg, biz), make_customer(pg, biz)
    r = create(pg, biz, draft_body(p, customer_id=c, invoice_discount="10", charges=[{"label": "Freight", "amount": "150"}]))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["version"] == 1 and d["invoice_discount"] == "10.00" and d["charges"] == [{"label": "Freight", "amount": "150.00"}]
    assert d["lines"][0] | {"id": None} == {"id": None, "line_no": 1, "product_id": p, "quantity": "2.500",
                                            "unit_price": "45.50", "discount_kind": None, "discount_value": None}
    assert d["bill_to"]["name"] == "Sharma Stores" and d["bill_to"]["state_code"] == "27"
    got = pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h("cathy"))
    assert got.status_code == 200 and bare(got.json()) == bare(d)


def test_etag_carries_the_version_and_a_weak_tag_is_stale(shop):  # platform_common.etag
    pg, biz, _ = shop
    p = make_product(pg, biz)
    made = create(pg, biz, draft_body(p))
    assert made.headers["etag"] == '"1"'
    d = made.json()
    got = pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h())
    assert got.headers["etag"] == '"1"'
    for tag in ('W/"1"', "*"):  # strong comparison only, and a blind write is refused
        r = pg.client.put(f"/api/v1/b/{biz}/drafts/{d['id']}", json=draft_body(p), headers=h(**{"If-Match": tag}))
        assert (r.status_code, r.json()["error"]["code"]) == (409, "stale_record")
    r = pg.client.put(f"/api/v1/b/{biz}/drafts/{d['id']}", json=draft_body(p), headers=h(**{"If-Match": '"1"'}))
    assert r.status_code == 200 and r.headers["etag"] == '"2"'
    assert pg.client.put(f"/api/v1/b/{biz}/drafts/{d['id']}", json=draft_body(p, kind="credit_note"),
                         headers=h(**{"If-Match": '"2"'})).status_code == 422


def test_too_many_lines_or_charges_are_refused(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    charges = [{"label": f"C{i}", "amount": "1"} for i in range(21)]
    r = create(pg, biz, draft_body(p, charges=charges))
    assert r.status_code == 422
    lines = [{"product_id": p, "quantity": "1"}] * 201
    assert create(pg, biz, {"lines": lines}).status_code == 422


def test_the_ex_works_flag_is_saved_and_defaults_off(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p)).json()
    assert d["customer_collects"] is False
    assert put(pg, biz, d, draft_body(p, customer_collects=True)).json()["customer_collects"] is True
    assert create(pg, biz, draft_body(p, customer_collects="yes")).status_code == 422


def test_a_json_number_or_bad_decimal_is_refused(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    for body in (
        {"lines": [{"product_id": p, "quantity": 2}]},
        {"lines": [{"product_id": p, "quantity": "2", "unit_price": 45.5}]},
        {"lines": [{"product_id": p, "quantity": "2", "unit_price": "45.555"}]},
        {"lines": [{"product_id": p, "quantity": "0"}]},
        {"lines": [{"product_id": p, "quantity": "1", "unit_price": "-1"}]},
        {"lines": [{"product_id": p, "quantity": "1", "discount_kind": "percent", "discount_value": "101"}]},
        {"lines": [{"product_id": p, "quantity": "1", "discount_kind": "percent"}]},
        {"invoice_discount": 5},
    ):
        assert create(pg, biz, body).status_code == 422, body
    assert scalar(pg.owner, "select count(*) from sales.drafts") == 0


def test_float_noise_never_reaches_the_stored_amount(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p, invoice_discount="0.10")).json()
    assert d["invoice_discount"] == "0.10"
    assert str(scalar(pg.owner, "select invoice_discount from sales.drafts")) == "0.10"


def test_the_buyer_is_a_customer_or_a_cash_sale_never_both(shop):
    pg, biz, other = shop
    p, c = make_product(pg, biz), make_customer(pg, biz)
    both = create(pg, biz, draft_body(p, customer_id=c, cash_buyer={"state_code": "27"}))
    assert both.status_code == 422 and both.json()["error"]["code"] == "buyer_ambiguous"
    cash = create(pg, biz, draft_body(p, cash_buyer={"name": "Walk-in", "state_code": "27"}))
    assert cash.status_code == 201 and cash.json()["cash_buyer"]["state_code"] == "27"
    assert create(pg, biz, draft_body(p, cash_buyer={"state_code": "99"})).status_code == 422
    foreign = make_customer(pg, other, sub="bob")
    r = create(pg, biz, draft_body(p, customer_id=foreign))
    assert r.status_code == 422 and r.json()["error"]["code"] == "customer_not_found"


def test_another_businesss_product_is_not_found(shop):
    pg, biz, other = shop
    theirs = make_product(pg, other, sub="bob")
    r = create(pg, biz, draft_body(theirs))
    assert r.status_code == 422 and r.json()["error"]["code"] == "product_not_found"


def test_create_is_idempotent_per_key_and_refuses_a_different_request(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    a = create(pg, biz, draft_body(p), key="k1")
    b = create(pg, biz, draft_body(p), key="k1")
    assert a.status_code == b.status_code == 201 and a.json()["id"] == b.json()["id"]
    assert scalar(pg.owner, "select count(*) from sales.drafts") == 1
    c = create(pg, biz, draft_body(p, invoice_discount="1"), key="k1")
    assert c.status_code == 409 and c.json()["error"]["code"] == "idempotency_mismatch"


def test_put_replaces_the_whole_draft_under_if_match(shop):
    pg, biz, _ = shop
    p, q = make_product(pg, biz), make_product(pg, biz, "SOAP-2")
    d = create(pg, biz, draft_body(p)).json()
    r = put(pg, biz, d, {"lines": [{"product_id": q, "quantity": "1", "discount_kind": "amount", "discount_value": "5"}]})
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["version"] == 2 and [ln["product_id"] for ln in new["lines"]] == [q]
    assert new["lines"][0]["discount_value"] == "5.00"
    stale = put(pg, biz, d, draft_body(p))  # still version 1
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_record"
    assert put(pg, biz, new, draft_body(p), version="x").status_code == 409
    none = pg.client.put(f"/api/v1/b/{biz}/drafts/{d['id']}", json=draft_body(p), headers=h())
    assert none.status_code == 422 and none.json()["error"]["code"] == "if_match_required"
    assert pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h()).json()["lines"][0]["product_id"] == q


def test_a_failed_put_leaves_the_draft_as_it_was(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p)).json()
    assert put(pg, biz, d, {"lines": [{"product_id": p, "quantity": "nope"}]}).status_code == 422
    assert bare(pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h()).json()) == bare(d)


def test_list_filters_by_buyer_name_and_pages(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz)
    create(pg, biz, draft_body(p, customer_id=make_customer(pg, biz, "Sharma Stores")))
    create(pg, biz, draft_body(p, customer_id=make_customer(pg, biz, "Gupta Traders")))
    r = pg.client.get(f"/api/v1/b/{biz}/drafts?q=sharm&kind=invoice", headers=h())
    assert [d["bill_to"]["name"] for d in r.json()["items"]] == ["Sharma Stores"]
    assert r.json()["items"][0]["lines"] == []
    both = pg.client.get(f"/api/v1/b/{biz}/drafts?limit=1", headers=h()).json()
    assert len(both["items"]) == 1 and both["has_more"] is True


def test_delete_needs_the_current_version_and_removes_lines(shop):
    pg, biz, _ = shop
    d = create(pg, biz, draft_body(make_product(pg, biz))).json()
    url = f"/api/v1/b/{biz}/drafts/{d['id']}"
    assert pg.client.delete(url, headers=h(**{"If-Match": "9"})).status_code == 409
    assert pg.client.delete(url, headers=h(**{"If-Match": "1"})).status_code == 204
    assert pg.client.get(url, headers=h()).status_code == 404
    assert scalar(pg.owner, "select count(*) from sales.draft_lines") == 0
    actions = [r[0] for r in pg.owner.connect().execute(text("select action from platform.audit_log")).all()]
    assert {"draft.created", "draft.deleted"} <= set(actions)


def test_credit_note_drafts_wait_for_their_slice(shop):
    pg, biz, _ = shop
    r = create(pg, biz, {"kind": "credit_note"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "kind_unsupported"


def test_roles_and_tenants(shop):
    pg, biz, other = shop
    d = create(pg, biz, draft_body(make_product(pg, biz))).json()
    url = f"/api/v1/b/{biz}/drafts/{d['id']}"
    assert create(pg, biz, {}, sub="bill").status_code == 201
    assert create(pg, biz, {}, sub="adam").status_code == 201
    # the CA may view, never change: a role denial is the unknown-ID 404
    assert pg.client.get(url, headers=h("cathy")).status_code == 200
    assert create(pg, biz, {}, sub="cathy").status_code == 404
    assert put(pg, biz, d, {}, sub="cathy").status_code == 404
    assert pg.client.delete(url, headers=h("cathy", **{"If-Match": "1"})).status_code == 404
    # bob is not a member of biz; and biz's draft id under bob's own business is unknown
    assert pg.client.get(url, headers=h("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/drafts/{d['id']}", headers=h("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/drafts", headers=h("bob")).json()["items"] == []
    assert put(pg, other, d, {}, sub="bob").status_code == 404


def test_a_save_returns_the_computation(shop):
    from decimal import Decimal as D

    pg, biz, _ = shop
    p = make_product(pg, biz, hsn="340120")
    other_state = create(pg, biz, draft_body(p, cash_buyer={"name": "Walk-in", "state_code": "27"})).json()
    c = other_state["computation"]
    assert c["is_inter_state"] is True and c["supply_class"] == "B2CS" and c["method_version"]
    assert D(c["taxable_total"]) == D("113.75") and c["cgst_total"] == "0.00"
    assert D(c["igst_total"]) in (D("20.47"), D("20.48"))
    assert D(c["doc_total"]) == D(c["taxable_total"]) + D(c["igst_total"]) + D(c["round_off"])
    assert c["lines"][0]["taxes"][0]["component"] == "IGST" and c["blocks"] == []
    same_state = create(pg, biz, draft_body(p, cash_buyer={"state_code": "19"})).json()["computation"]
    assert same_state["is_inter_state"] is False and same_state["igst_total"] == "0.00"
    assert D(same_state["cgst_total"]) == D(same_state["sgst_total"]) > 0
    # reads and lists do not compute
    assert pg.client.get(f"/api/v1/b/{biz}/drafts/{other_state['id']}", headers=h()).json()["computation"] is None


def test_an_incomplete_draft_saves_with_blocks_not_an_error(shop):
    pg, biz, _ = shop
    d = create(pg, biz, draft_body(make_product(pg, biz, hsn="340120"))).json()  # no buyer yet
    assert d["computation"]["supply_class"] is None
    assert "buyer_state_missing" in [b["code"] for b in d["computation"]["blocks"]]
    saved = put(pg, biz, d, {"cash_buyer": {"state_code": "27"}, "lines": draft_body(make_product(pg, biz, "S2", hsn="340120"))["lines"]})
    assert saved.status_code == 200 and saved.json()["computation"]["blocks"] == []


def test_amounts_that_cannot_be_computed_are_a_422_and_change_nothing(shop):
    pg, biz, _ = shop
    p = make_product(pg, biz, hsn="340120")
    d = create(pg, biz, draft_body(p, cash_buyer={"state_code": "27"})).json()
    too_much = draft_body(p, cash_buyer={"state_code": "27"}, invoice_discount="1000")
    r = put(pg, biz, d, too_much)
    assert r.status_code == 422, r.text
    assert pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h()).json()["version"] == 1
    assert create(pg, biz, too_much).status_code == 422
    assert scalar(pg.owner, "select count(*) from sales.drafts") == 1


def test_a_customer_deleted_after_the_draft_was_saved_is_customer_not_found_on_save(shop):
    pg, biz, _ = shop
    p, c = make_product(pg, biz, hsn="340120"), make_customer(pg, biz)
    d = create(pg, biz, draft_body(p, customer_id=c)).json()
    cu = pg.client.get(f"/api/v1/b/{biz}/customers/{c}", headers=h()).json()
    gone = pg.client.delete(f"/api/v1/b/{biz}/customers/{c}", headers=h(**{"If-Match": str(cu["version"])}))
    assert gone.status_code == 204
    r = put(pg, biz, d, draft_body(p, customer_id=c))
    assert r.status_code == 422 and r.json()["error"]["code"] == "customer_not_found"
