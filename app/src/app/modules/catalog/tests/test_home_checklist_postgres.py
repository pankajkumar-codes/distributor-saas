"""Home's setup checklist reads the catalog: a business with an active product or customer
sees those two rows done, and another business's data never counts (R1 retest bug #1).
Skipped unless PG_ADMIN_URL is set."""

import uuid
from datetime import datetime

import pytest

from app import api as app_api
from platform_common.clock import IST, FrozenClock, get_clock

from .conftest import PG_ADMIN_URL, as_user, new_business
from .test_customers_postgres import KA, customer
from .test_products_postgres import product

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def shop(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    return pg, new_business(pg, "alice")


def post(pg, path, body, sub="alice"):
    r = pg.client.post(path, json=body, headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text


def rows(pg, biz, sub="alice"):
    r = pg.client.get(f"/api/v1/b/{biz}/home", headers=as_user(sub))
    assert r.status_code == 200, r.text
    items = {i["key"]: i["done"] for i in r.json()["checklist"]["items"]}
    return items["first_product"], items["first_customer"]


def test_adding_a_product_and_a_customer_marks_their_rows_done(shop):
    pg, biz = shop
    assert rows(pg, biz) == (False, False)
    post(pg, f"/api/v1/b/{biz}/products", product())
    assert rows(pg, biz) == (True, False)
    post(pg, f"/api/v1/b/{biz}/customers", customer())
    assert rows(pg, biz) == (True, True)


def test_another_business_with_catalog_data_does_not_count(shop):
    pg, biz = shop
    other = pg.client.post(
        "/api/v1/b",
        json={
            "registration": {"kind": "gstin", "gstin": "27AAPFU0939F1ZV"},
            "legal_name": "Other Traders LLP",
            "trade_name": "Other Traders",
            "address": {"line1": "2 Other Road", "city": "Pune", "pin": "411001", "state_code": "27"},
            "turnover_band": "up_to_threshold",
            "einvoice_history": "no",
        },
        headers={**as_user("bob"), "Idempotency-Key": uuid.uuid4().hex},
    )
    assert other.status_code == 201, other.text
    other_biz = other.json()["business_id"]
    post(pg, f"/api/v1/b/{other_biz}/products", product(), sub="bob")
    post(pg, f"/api/v1/b/{other_biz}/customers", customer(gstin=KA), sub="bob")
    assert rows(pg, other_biz, sub="bob") == (True, True)
    assert rows(pg, biz) == (False, False)  # alice's business has nothing of its own
