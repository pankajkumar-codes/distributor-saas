"""load_inputs on PostgreSQL as app_rw: what compute receives from catalog, business and
refdata for a real business (LLD-4 §3). Skipped unless PG_ADMIN_URL is set.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.modules.sales.compute import DraftIn, DraftLineIn, compute, load_inputs
from platform_common.errors import Deny, Invalid

from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

D = Decimal
TODAY = date(2026, 10, 27)
KA_GSTIN = "29AAACX3333C1ZL"  # synthetic, valid check digit (team/gst/gstr1-examples.md)


@pytest.fixture()
def shop(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    biz = new_business(pg, "alice")  # state 19, band up_to_threshold for 2026-27, e-invoicing "no"
    return pg, biz, user_id(pg.owner, "alice")


def post(pg, biz, path, body, sub="alice"):
    r = pg.client.post(
        f"/api/v1/b/{biz}/{path}", json=body, headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex}
    )
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["id"])


def soap(pg, biz, hsn="340111"):
    return post(
        pg,
        biz,
        "products",
        {
            "code": f"SOAP-{uuid.uuid4().hex[:6]}",
            "name": "Soap",
            "hsn": hsn,
            "uqc": "NOS",
            "sale_rate": "50.00",
            "tax_category": "taxable",
            "rate": {"rate": "18", "valid_from": "2026-04-01"},
        },
    )


def run(pg, biz, alice, draft, lines):
    with pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        return compute(load_inputs(c, draft, lines, today=TODAY))


def test_a_registered_customer_in_another_state(shop):
    pg, biz, alice = shop
    pid = soap(pg, biz)
    cid = post(
        pg,
        biz,
        "customers",
        {
            "name": "Bengaluru Stores",
            "gstin": KA_GSTIN,
            "billing": {"line1": "1 MG Road", "city": "Bengaluru", "pin": "560001"},
            "credit_days": 30,
        },
    )
    c = run(pg, biz, alice, DraftIn(doc_date=TODAY, customer_id=cid), [DraftLineIn(1, pid, D(100), D("50.00"))])
    # No ship-to on the draft: case A takes the customer's delivery (= billing) state (Staff, #80).
    assert (c.pos_state_code, c.is_inter_state, c.supply_class) == ("29", True, "B2B")
    assert [(t.component, t.amount) for t in c.lines[0].taxes] == [("IGST", D("900.00"))]
    assert c.doc_total == D("5900.00") and c.rounding_mode == "ROUND_HALF_UP"
    assert c.blocks == ()


def test_a_cash_sale_with_only_a_state(shop):
    pg, biz, alice = shop
    pid = soap(pg, biz)
    draft = DraftIn(doc_date=TODAY, customer_id=None, cash_buyer={"state_code": "19"})
    c = run(pg, biz, alice, draft, [DraftLineIn(1, pid, D(2), D("50.00"))])
    assert (c.pos_state_code, c.supply_class, c.cgst_total, c.sgst_total) == ("19", "B2CS", D("9.00"), D("9.00"))


def test_hsn_digits_come_from_the_preceding_fy_band(shop):
    pg, biz, alice = shop
    pid = soap(pg, biz, hsn="3401")
    draft = DraftIn(doc_date=TODAY, customer_id=None, cash_buyer={"state_code": "19"})
    lines = [DraftLineIn(1, pid, D(1), D("50.00"))]
    # Sign-up set only 2026-27's band, so 2025-26 is unknown: the stricter 6 digits.
    (block,) = run(pg, biz, alice, draft, lines).blocks
    assert (block.code, block.field, block.line_no) == ("hsn_needs_turnover_band", "business.turnover_band", 1)
    assert "FY 2025-26" in block.fix and "4-digit" in block.fix and "6 digits" in block.fix  # both from refdata
    r = pg.client.put(
        f"/api/v1/b/{biz}/turnover-bands/2025-26", json={"band": "up_to_threshold"}, headers=as_user("alice")
    )
    assert r.status_code == 200, r.text
    assert run(pg, biz, alice, draft, lines).blocks == ()


def test_unknown_products_old_dates_and_other_businesses(shop):
    pg, biz, alice = shop
    draft = DraftIn(doc_date=TODAY, customer_id=None, cash_buyer={"state_code": "19"})
    c = run(pg, biz, alice, draft, [DraftLineIn(1, uuid.uuid4(), D(1), D("1.00"))])
    assert [b.code for b in c.blocks] == ["product_unknown"]
    with pytest.raises(Invalid) as e:
        run(pg, biz, alice, DraftIn(doc_date=date(2019, 6, 1), customer_id=None, cash_buyer={"state_code": "19"}), [])
    assert e.value.code == "doc_date_not_supported"
    other = new_business(pg, "bob")
    theirs = post(
        pg,
        other,
        "customers",
        {
            "name": "Theirs",
            "gstin": None,
            "billing": {"line1": "x", "city": "Kolkata", "pin": "700001", "state_code": "19"},
            "credit_days": 0,
        },
        sub="bob",
    )
    with pytest.raises(Deny):
        run(pg, biz, alice, DraftIn(doc_date=TODAY, customer_id=theirs), [])
