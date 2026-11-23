"""The local demo's ready-made customers and products (demo/demo_data.py) go in through the real API,
cover the cases the demo promises, and a second seed run adds nothing.

demo/seed.py's own catalog step is run here, with its HTTP call routed to the test client, so the
code the demo runs is the code tested. Skipped unless PG_ADMIN_URL is set.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from app import api as app_api
from app.modules.business.gstin import check_gstin
from platform_common.clock import IST, FrozenClock, get_clock

from .conftest import PG_ADMIN_URL, as_user, new_business

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

DEMO_DIR = Path(__file__).resolve().parents[6] / "demo"
_spec = importlib.util.spec_from_file_location("demo_seed", DEMO_DIR / "seed.py")
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


@pytest.fixture()
def shop(pg, monkeypatch):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 23, 12, tzinfo=IST))
    biz = new_business(pg, "alice")

    def call(base, method, path, body=None, token=None):
        r = pg.client.request(method, "/api/v1" + path, json=body,
                              headers={**as_user("alice"), "Idempotency-Key": seed.uuid.uuid4().hex})
        return r.status_code, (r.json() if r.content else None)

    monkeypatch.setattr(seed, "call", call)
    return pg, biz


def items(pg, biz, what, query=""):
    r = pg.client.get(f"/api/v1/b/{biz}/{what}?status=all&limit=200{query}", headers=as_user("alice"))
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_the_demo_gstins_are_well_formed_and_not_the_demo_business():
    for c in seed.CUSTOMERS:
        if c["gstin"]:
            found = check_gstin(c["gstin"], own=False)
            assert found.ok and not found.warnings, c["gstin"]
            assert c["gstin"] != seed.DEMO_GSTIN


def test_the_seed_adds_five_customers_and_ten_products(shop, capsys):
    pg, biz = shop
    seed._catalog("", str(biz), None)
    assert "15 added" in capsys.readouterr().out

    customers = {c["name"]: c for c in items(pg, biz, "customers")}
    assert len(customers) == 5
    states = {(c["gstin"] is not None, c["billing"]["state_code"]) for c in customers.values()}
    assert states == {(True, "19"), (True, "27"), (False, "19"), (False, "10"), (True, "07")}
    shipped = [c for c in customers.values() if not c["delivery_same_as_billing"]]
    assert [(c["billing"]["state_code"], c["delivery"]["state_code"]) for c in shipped] == [("07", "19")]

    products = {p["code"]: p for p in items(pg, biz, "products")}
    assert len(products) == 10
    assert {p["tax_category"] for p in products.values()} == {"taxable", "exempt", "nil_rated", "non_gst"}
    assert [p["code"] for p in items(pg, biz, "products", "&filter=no_hsn")] == ["DEMO-HAMPER"]
    assert len({p["uqc"] for p in products.values()}) >= 8


def test_a_second_run_adds_nothing(shop, capsys):
    pg, biz = shop
    seed._catalog("", str(biz), None)
    seed._catalog("", str(biz), None)
    assert capsys.readouterr().out.splitlines()[-1] == "demo customers and products: 0 added"
    assert len(items(pg, biz, "customers")) == 5 and len(items(pg, biz, "products")) == 10
