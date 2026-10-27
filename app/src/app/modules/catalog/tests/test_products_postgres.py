"""Products and rate history through the API on PostgreSQL, as app_rw with FORCE
row-level security (LLD-3 §12: AC3-1 to AC3-10, AC3-15 to AC3-20 for products).

The clock is frozen at 2026-10-27 IST. Rates and dates come from the GST expert's
table in team/gst/refdata-rates-uqc.md §2. Skipped unless PG_ADMIN_URL is set.
"""

import threading
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import api as app_api
from platform_common.clock import IST, FrozenClock, get_clock

from ..interface import mark_used, product_for_line, products_for_lines, setup_counts
from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, seed_member, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TODAY = date(2026, 10, 27)


@pytest.fixture()
def shop(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    biz = new_business(pg, "alice")
    return pg, biz


def url(biz, path=""):
    return f"/api/v1/b/{biz}/products{path}"


def post(pg, path, body=None, sub="alice", key=None, **headers):
    return pg.client.post(path, json=body or {},
                          headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex, **headers})


def product(code="SOAP-1", rate="18", valid_from="2026-04-01", **extra):
    body = {"code": code, "name": "Neem soap 100 g", "hsn": "3401", "uqc": "PCS", "sale_rate": "45.50",
            "tax_category": "taxable", "rate": {"rate": rate, "valid_from": valid_from}}
    body.update(extra)
    return body


def make(pg, biz, sub="alice", **kw):
    r = post(pg, url(biz), product(**kw), sub=sub)
    assert r.status_code == 201, r.text
    return r.json()


def audit_actions(pg, biz):
    with pg.owner.connect() as c:
        return [a for (a,) in c.execute(text("select action from platform.audit_log where business_id = :b"
                                             " order by at, id"), {"b": biz})]


# --- Create, read, the refdata checks ----------------------------------------------


def test_create_and_read_a_product_with_its_first_rate(shop):
    pg, biz = shop
    p = make(pg, biz, hsn="34011190")
    assert (p["code"], p["sale_rate"], p["uqc"], p["version"], p["in_use"], p["status"]) == (
        "SOAP-1", "45.50", "PCS", 1, False, "active")
    assert p["rate_on"]["rate"] == "18" and p["rate_on"]["valid_from"] == "2026-04-01"
    assert p["rate_on"]["confirmed"] is False
    assert [w["code"] for w in p["warnings"]] == ["rate_unconfirmed"]
    assert [(r["rate"], r["valid_until"], r["voided"]) for r in p["rates"]] == [("18", None, False)]
    got = pg.client.get(url(biz, f"/{p['id']}"), headers=as_user("alice")).json()
    assert got == p
    assert audit_actions(pg, biz)[-2:] == ["product.created", "product.rate_added"]


@pytest.mark.parametrize(
    ("rate", "valid_from", "status", "code"),
    [
        ("18", "2025-10-01", 201, None),
        ("12", "2025-09-21", 201, None),  # the old regime
        ("12", "2025-09-22", 422, "rate_not_allowed"),
        ("40", "2025-09-21", 422, "rate_not_allowed"),
        ("28", "2026-01-31", 201, None),
        ("28", "2026-02-01", 422, "rate_not_allowed"),
        ("1.5", "2022-07-17", 422, "rate_not_allowed"),
        ("0", "2026-04-01", 422, "rate_not_allowed"),  # 0 is a tax category, not a rate
        ("18.00", "2026-04-01", 201, None),  # compared as Decimal
        ("18", "2017-06-30", 422, "valid_from_out_of_range"),  # before gst.regime_start_date
        ("18", "2027-10-28", 201, None),  # 366 days ahead is the limit
        ("18", "2027-10-29", 422, "valid_from_out_of_range"),
    ],
)
def test_rates_are_checked_against_the_dated_refdata_list(shop, rate, valid_from, status, code):
    pg, biz = shop
    r = post(pg, url(biz), product(code=f"P-{uuid.uuid4().hex[:6]}", rate=rate, valid_from=valid_from))
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code and r.json()["error"]["field"] in ("rate", "valid_from")


def test_the_app_never_fills_a_rate(shop):
    """AC3-4: a taxable product without a rate is refused, cess or not; other categories
    can't carry one."""
    pg, biz = shop
    for extra in ({}, {"has_cess": True}):
        body = product(code=f"N-{uuid.uuid4().hex[:6]}", **extra)
        body.pop("rate")
        r = post(pg, url(biz), body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "rate_required"
    r = post(pg, url(biz), product(code="EX-1", tax_category="exempt"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "rate_not_allowed"
    body = product(code="EX-1", tax_category="exempt")
    body.pop("rate")
    ex = post(pg, url(biz), body)
    assert ex.status_code == 201 and ex.json()["rate_on"] is None and ex.json()["rates"] == []
    assert "not_taxable" in [w["code"] for w in ex.json()["warnings"]]
    cess = make(pg, biz, code="CESS-1", has_cess=True)
    assert "cess_not_supported" in [w["code"] for w in cess["warnings"]]


@pytest.mark.parametrize(
    ("hsn", "ok"),
    [("3401", True), ("340111", True), ("34011190", True), ("0000", True), ("", True), (None, True),
     ("340", False), ("34011", False), ("3401119", False), ("340111901", False), ("34O1", False),
     ("85 17", False), ("３４０１", False)],
)
def test_hsn_shape_comes_from_refdata(shop, hsn, ok):
    pg, biz = shop
    r = post(pg, url(biz), product(code=f"H-{uuid.uuid4().hex[:6]}", hsn=hsn))
    assert (r.status_code == 201) is ok, r.text
    if not ok:
        assert r.json()["error"]["code"] == "hsn_invalid"
    elif not hsn:
        assert "hsn_missing" in [w["code"] for w in r.json()["warnings"]]


def test_field_checks(shop):
    pg, biz = shop
    cases = [
        ({"uqc": "XYZ"}, "uqc_unknown"),
        ({"uqc": "pcs"}, None),  # stored upper-case
        ({"sale_rate": "12.345"}, "sale_rate_invalid"),
        ({"sale_rate": "-1"}, "sale_rate_invalid"),
        ({"code": "has space"}, "code_invalid"),
        ({"code": "x" * 41}, "code_invalid"),
        ({"name": "   "}, "name_invalid"),
    ]
    for extra, code in cases:
        body = product(**{"code": f"F-{uuid.uuid4().hex[:6]}", **extra})
        r = post(pg, url(biz), body)
        if code is None:
            assert r.status_code == 201 and r.json()["uqc"] == "PCS"
        else:
            assert r.status_code == 422 and r.json()["error"]["code"] == code, (extra, r.text)
    # AC3-15: money is a decimal string, never a JSON number.
    r = post(pg, url(biz), product(code="F-NUM", sale_rate=45.5))
    assert r.status_code == 422
    r = post(pg, url(biz), product(code="F-NUM", rate=18))
    assert r.status_code == 422
    units = pg.client.get(f"/api/v1/b/{biz}/units", headers=as_user("alice")).json()
    assert {"code": "NOS", "name": "Numbers"} in units and len(units) == 45


def test_code_is_unique_ignoring_case_including_archived_and_barcode_among_active(shop):
    """AC3-8."""
    pg, biz = shop
    a = make(pg, biz, code="ABC-1", barcode="8901")
    r = post(pg, url(biz), product(code="abc-1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "code_taken"
    assert post(pg, url(biz, f"/{a['id']}/archive")).status_code == 200
    r = post(pg, url(biz), product(code="Abc-1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "code_taken"
    # The barcode is free once its product is archived, and unarchive then refuses.
    b = make(pg, biz, code="ABC-2", barcode="8901")
    r = post(pg, url(biz, f"/{a['id']}/unarchive"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "barcode_taken"
    r = post(pg, url(biz), product(code="ABC-3", barcode="8901"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "barcode_taken"
    assert b["barcode"] == "8901"


def test_a_retry_with_the_same_key_creates_one_product(shop):
    pg, biz = shop
    key = uuid.uuid4().hex
    first = post(pg, url(biz), product(code="RETRY"), key=key)
    again = post(pg, url(biz), product(code="RETRY"), key=key)
    assert first.status_code == 201 and again.json()["id"] == first.json()["id"]
    with pg.owner.connect() as c:
        assert c.execute(text("select count(*) from catalog.products where business_id = :b"), {"b": biz}).scalar() == 1


# --- Rate history -----------------------------------------------------------------


def test_rate_history_add_void_and_the_last_rate_rule(shop):
    pg, biz = shop
    p = make(pg, biz, rate="12", valid_from="2025-04-01")
    pid = p["id"]
    r = post(pg, url(biz, f"/{pid}/rates"), {"rate": "18", "valid_from": "2025-09-22"})
    assert r.status_code == 201 and r.json()["version"] == 2  # a rate add bumps version [RM43-6]
    assert r.json()["rate_on"]["rate"] == "18"
    assert r.json()["rate_changed_within_warning_window"] is False  # 400 days ago
    r = post(pg, url(biz, f"/{pid}/rates"), {"rate": "5", "valid_from": "2026-10-20"})
    assert r.json()["rate_changed_within_warning_window"] is True  # 7 days ago
    rates = r.json()["rates"]
    assert [(x["rate"], x["valid_from"], x["valid_until"]) for x in rates] == [
        ("12", "2025-04-01", "2025-09-22"), ("18", "2025-09-22", "2026-10-20"), ("5", "2026-10-20", None)]
    r = post(pg, url(biz, f"/{pid}/rates"), {"rate": "18", "valid_from": "2026-10-20"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "rate_exists_on_date"

    middle = rates[1]["id"]
    for reason in (None, "", "   "):
        r = post(pg, url(biz, f"/{pid}/rates/{middle}/void"), {"reason": reason})
        assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = post(pg, url(biz, f"/{pid}/rates/{middle}/void"), {"reason": "typed the wrong date"})
    assert r.status_code == 201
    assert [(x["rate"], x["voided"], x["valid_until"]) for x in r.json()["rates"]] == [
        ("12", False, "2026-10-20"), ("18", True, None), ("5", False, None)]
    on = pg.client.get(url(biz, f"/{pid}?on=2026-01-01"), headers=as_user("alice")).json()
    assert on["rate_on"]["rate"] == "12"  # the earlier row now covers the gap

    # Voiding down to one live row is fine; the last one is refused.
    assert post(pg, url(biz, f"/{pid}/rates/{rates[0]['id']}/void"), {"reason": "wrong"}).status_code == 201
    r = post(pg, url(biz, f"/{pid}/rates/{rates[2]['id']}/void"), {"reason": "wrong"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "last_rate"
    with pg.owner.connect() as c:
        reasons = c.execute(text("select action, reason from platform.audit_log where business_id = :b"
                                 " and action = 'product.rate_voided' order by at"), {"b": biz}).all()
    assert [tuple(x) for x in reasons] == [("product.rate_voided", "typed the wrong date"),
                                           ("product.rate_voided", "wrong")]


def test_rate_tables_are_insert_only_for_app_rw(shop):
    """AC3-2."""
    pg, biz = shop
    p = make(pg, biz)
    alice = user_id(pg.owner, "alice")
    for sql in (
        "update catalog.product_rates set rate = 5",
        "delete from catalog.product_rates",
        "update catalog.product_rate_voids set reason = 'x'",
        "delete from catalog.product_rate_voids",
        "update catalog.product_rate_confirmations set note = 'x'",
        "delete from catalog.product_rate_confirmations",
        "delete from catalog.products",
    ):
        with pytest.raises(DBAPIError) as e, pg.app_rw.begin() as c:
            ctx(c, alice, biz)
            c.execute(text(sql))
        assert e.value.orig.sqlstate == "42501", sql
    assert p["id"]


def test_two_concurrent_adds_on_one_date_make_one_row(shop):
    """AC3-3, on two connections: the second waits on the product's row lock."""
    pg, biz = shop
    pid = make(pg, biz)["id"]
    results = []

    def add():
        results.append(post(pg, url(biz, f"/{pid}/rates"), {"rate": "5", "valid_from": "2026-11-01"}).status_code)

    threads = [threading.Thread(target=add) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [201, 409]
    with pg.owner.connect() as c:
        n = c.execute(text("select count(*) from catalog.product_rates where product_id = :p"
                           " and valid_from = '2026-11-01'"), {"p": pid}).scalar()
    assert n == 1


def test_confirm_is_owner_and_admin_only_and_keeps_its_history(shop):
    """AC3-5, L3-3: billing and CA get the unknown-ID 404 on confirm and unconfirm."""
    pg, biz = shop
    seed_member(pg, biz, "ada", "admin")
    seed_member(pg, biz, "bill", "billing")
    seed_member(pg, biz, "cara", "ca")
    p = make(pg, biz)
    rid = p["rates"][0]["id"]
    for sub in ("bill", "cara"):
        for action, body in (("confirm", {}), ("unconfirm", {"reason": "x"})):
            r = post(pg, url(biz, f"/{p['id']}/rates/{rid}/{action}"), body, sub=sub)
            assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", (sub, action)
    r = post(pg, url(biz, f"/{p['id']}/rates/{rid}/confirm"), {"note": "CA said 18% on 20 Oct"}, sub="ada")
    assert r.status_code == 201 and r.json()["rate_on"]["confirmed"] is True and r.json()["warnings"] == []
    assert r.json()["version"] == 1  # confirm doesn't bump version (§3)
    r = post(pg, url(biz, f"/{p['id']}/rates/{rid}/unconfirm"), {"reason": "  "}, sub="alice")
    assert r.status_code == 422 and r.json()["error"]["code"] == "reason_required"
    r = post(pg, url(biz, f"/{p['id']}/rates/{rid}/unconfirm"), {"reason": "CA withdrew it"}, sub="alice")
    conf = r.json()["rates"][0]["confirmation"]
    assert conf["state"] == "unconfirmed" and conf["note"] == "CA withdrew it"
    with pg.owner.connect() as c:
        events = c.execute(text("select action from catalog.product_rate_confirmations order by created_at")).all()
    assert [e for (e,) in events] == ["confirm", "unconfirm"]
    # The filter and the setup counts see it.
    unconfirmed = pg.client.get(url(biz, "?filter=rate_unconfirmed"), headers=as_user("bill")).json()
    assert [i["code"] for i in unconfirmed["items"]] == ["SOAP-1"]


def test_ca_reads_but_never_writes(shop):
    """AC3-6 for the product routes."""
    pg, biz = shop
    seed_member(pg, biz, "cara", "ca")
    p = make(pg, biz)
    pid, rid = p["id"], p["rates"][0]["id"]
    assert pg.client.get(url(biz), headers=as_user("cara")).status_code == 200
    assert pg.client.get(url(biz, f"/{pid}"), headers=as_user("cara")).status_code == 200
    writes = [
        post(pg, url(biz), product(code="CA-1"), sub="cara"),
        pg.client.patch(url(biz, f"/{pid}"), json={"name": "x"}, headers={**as_user("cara"), "If-Match": "1"}),
        post(pg, url(biz, f"/{pid}/archive"), sub="cara"),
        post(pg, url(biz, f"/{pid}/rates"), {"rate": "5", "valid_from": "2026-11-01"}, sub="cara"),
        post(pg, url(biz, f"/{pid}/rates/{rid}/void"), {"reason": "x"}, sub="cara"),
        pg.client.delete(url(biz, f"/{pid}"), headers={**as_user("cara"), "If-Match": "1"}),
    ]
    assert [w.status_code for w in writes] == [404] * 6


def test_another_business_ids_look_unknown(shop):
    """AC3-7 for products and rates: every route with B's IDs, as A's owner, is 404."""
    pg, biz = shop
    other = new_business(pg, "bob")
    theirs = make(pg, other, sub="bob")
    pid, rid = theirs["id"], theirs["rates"][0]["id"]
    calls = [
        pg.client.get(url(biz, f"/{pid}"), headers=as_user("alice")),
        pg.client.patch(url(biz, f"/{pid}"), json={"name": "x"}, headers={**as_user("alice"), "If-Match": "1"}),
        post(pg, url(biz, f"/{pid}/archive")),
        post(pg, url(biz, f"/{pid}/rates"), {"rate": "5", "valid_from": "2026-11-01"}),
        post(pg, url(biz, f"/{pid}/rates/{rid}/void"), {"reason": "x"}),
        post(pg, url(biz, f"/{pid}/rates/{rid}/confirm")),
        pg.client.delete(url(biz, f"/{pid}"), headers={**as_user("alice"), "If-Match": "1"}),
        # A's own product with B's rate ID.
        post(pg, url(biz, f"/{make(pg, biz)['id']}/rates/{rid}/void"), {"reason": "x"}),
        # And alice in B's URL, where she isn't a member.
        pg.client.get(url(other), headers=as_user("alice")),
    ]
    assert [c.status_code for c in calls] == [404] * len(calls)
    assert pg.client.get(url(biz), headers=as_user("alice")).json()["items"][0]["code"] == "SOAP-1"


def test_a_rate_row_cant_point_at_another_business_product(shop):
    """The composite foreign key: RLS doesn't apply to foreign key checks."""
    pg, biz = shop
    other = new_business(pg, "bob")
    theirs = make(pg, other, sub="bob")
    alice = user_id(pg.owner, "alice")
    with pytest.raises(DBAPIError) as e, pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        c.execute(text("insert into catalog.product_rates (id, business_id, product_id, rate, valid_from, source,"
                       " created_by) values (gen_random_uuid(), :b, :p, 18, '2026-01-01', 'manual', :u)"),
                  {"b": biz, "p": theirs["id"], "u": alice})
    assert e.value.orig.sqlstate == "23503"


# --- Edit, archive, delete ---------------------------------------------------------


def test_patch_needs_the_current_version(shop):
    """AC3-10, L3-9."""
    pg, biz = shop
    p = make(pg, biz)
    h = as_user("alice")
    r = pg.client.patch(url(biz, f"/{p['id']}"), json={"name": "Neem soap 125 g"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "if_match_required"
    r = pg.client.patch(url(biz, f"/{p['id']}"), json={"name": "Neem soap 125 g", "hsn": None},
                        headers={**h, "If-Match": "1"})
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["hsn"] is None
    r = pg.client.patch(url(biz, f"/{p['id']}"), json={"name": "Lost edit"}, headers={**h, "If-Match": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_record"
    assert pg.client.get(url(biz, f"/{p['id']}"), headers=h).json()["name"] == "Neem soap 125 g"
    r = pg.client.patch(url(biz, f"/{p['id']}"), json={"tax_category": "exempt"}, headers={**h, "If-Match": "2"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "tax_category_locked"
    # Archive takes no If-Match and is a no-op the second time, but bumps version [RM43-7].
    assert post(pg, url(biz, f"/{p['id']}/archive")).json()["version"] == 3
    assert post(pg, url(biz, f"/{p['id']}/archive")).json()["version"] == 3
    assert audit_actions(pg, biz).count("product.archived") == 1
    assert pg.client.get(url(biz), headers=h).json()["items"] == []
    assert len(pg.client.get(url(biz, "?status=archived"), headers=h).json()["items"]) == 1


def test_delete_is_a_soft_delete_that_keeps_the_rate_history(shop):
    """AC3-18 [RM43-1], AC3-9."""
    pg, biz = shop
    p = make(pg, biz, code="GONE-1", rate="12", valid_from="2025-04-01")
    pid = p["id"]
    post(pg, url(biz, f"/{pid}/rates"), {"rate": "18", "valid_from": "2025-09-22"})
    second = pg.client.get(url(biz, f"/{pid}"), headers=as_user("alice")).json()
    post(pg, url(biz, f"/{pid}/rates/{second['rates'][0]['id']}/void"), {"reason": "wrong"})
    post(pg, url(biz, f"/{pid}/rates/{second['rates'][1]['id']}/confirm"))
    version = pg.client.get(url(biz, f"/{pid}"), headers=as_user("alice")).json()["version"]
    h = {**as_user("alice")}
    r = pg.client.delete(url(biz, f"/{pid}"), headers={**h, "If-Match": str(version - 1)})
    assert r.status_code == 409 and r.json()["error"]["code"] == "stale_record"
    assert pg.client.delete(url(biz, f"/{pid}"), headers={**h, "If-Match": str(version)}).status_code == 204
    assert pg.client.get(url(biz, f"/{pid}"), headers=h).status_code == 404
    assert pg.client.get(url(biz, "?status=all&q=gone"), headers=h).json()["items"] == []
    assert pg.client.delete(url(biz, f"/{pid}"), headers={**h, "If-Match": str(version + 1)}).status_code == 404
    with pg.owner.connect() as c:
        kept = [c.execute(text(f"select count(*) from catalog.{t}")).scalar()
                for t in ("product_rates", "product_rate_voids", "product_rate_confirmations")]
    assert kept == [2, 1, 1]
    assert make(pg, biz, code="gone-1")["code"] == "gone-1"  # the code is free again
    assert "product.deleted" in audit_actions(pg, biz)


def test_a_used_product_can_be_archived_but_not_deleted(shop):
    """AC3-9 with mark_used, and mark_used counts one product on two lines once."""
    pg, biz = shop
    p = make(pg, biz)
    alice = user_id(pg.owner, "alice")
    with pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        mark_used(c, [uuid.UUID(p["id"]), uuid.UUID(p["id"])])
    r = pg.client.delete(url(biz, f"/{p['id']}"), headers={**as_user("alice"), "If-Match": "1"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "product_in_use"
    got = pg.client.get(url(biz, f"/{p['id']}"), headers=as_user("alice")).json()
    assert got["in_use"] is True and got["version"] == 1  # mark_used doesn't bump version
    assert post(pg, url(biz, f"/{p['id']}/archive")).status_code == 200


def test_delete_and_finalize_serialise_on_the_row_lock(shop):
    """AC3-20, both orders, two connections."""
    pg, biz = shop
    alice = user_id(pg.owner, "alice")
    # Delete first: mark_used then raises product_deleted.
    first = make(pg, biz, code="ORDER-1")
    assert pg.client.delete(url(biz, f"/{first['id']}"),
                            headers={**as_user("alice"), "If-Match": "1"}).status_code == 204
    from platform_common.errors import Conflict

    with pytest.raises(Conflict) as e, pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        mark_used(c, [uuid.UUID(first["id"])])
    assert e.value.code == "product_deleted"
    # mark_used first, holding its transaction open: the delete waits, then sees it used.
    second = make(pg, biz, code="ORDER-2")
    outcome = {}
    started = threading.Event()
    with pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        mark_used(c, [uuid.UUID(second["id"])])

        def delete():
            started.set()
            outcome["r"] = pg.client.delete(url(biz, f"/{second['id']}"),
                                            headers={**as_user("alice"), "If-Match": "1"})

        t = threading.Thread(target=delete)
        t.start()
        started.wait()
        t.join(timeout=1)
        assert t.is_alive()  # blocked on the row lock until this commits
    t.join()
    assert outcome["r"].status_code == 409 and outcome["r"].json()["error"]["code"] == "product_in_use"


# --- Search, current_rates and the interface ---------------------------------------


def test_search_by_name_fragment_code_prefix_and_exact_barcode(shop):
    """AC3-17 (integration half)."""
    pg, biz = shop
    make(pg, biz, code="SOAP-1", name="Neem soap 100 g", barcode="8901234")
    make(pg, biz, code="OIL-1", name="Coconut oil 1 L")
    make(pg, biz, code="SOAP-2", name="Rose soap", hsn=None)
    h = as_user("alice")

    def codes(query):
        return [i["code"] for i in pg.client.get(url(biz, query), headers=h).json()["items"]]

    assert codes("?q=SOAP") == ["SOAP-1", "SOAP-2"]
    assert codes("?q=conut") == ["OIL-1"]
    assert codes("?q=8901234") == ["SOAP-1"]
    assert codes("?q=890") == []  # barcode is exact
    assert codes("?q=50%25") == []  # a literal %, not a wildcard
    assert codes("?filter=no_hsn") == ["SOAP-2"]
    page = pg.client.get(url(biz, "?limit=2"), headers=h).json()
    assert len(page["items"]) == 2 and page["has_more"] is True
    other = new_business(pg, "bob")
    make(pg, other, sub="bob", code="SOAP-9")
    assert codes("?q=soap") == ["SOAP-1", "SOAP-2"]


def test_current_rates_on_a_date_for_the_callers_business_only(shop):
    """AC3-19: the date is the caller's, and RLS limits the rows."""
    pg, biz = shop
    p = make(pg, biz, rate="12", valid_from="2025-04-01")
    post(pg, url(biz, f"/{p['id']}/rates"), {"rate": "18", "valid_from": "2025-09-22"})
    other = new_business(pg, "bob")
    make(pg, other, sub="bob")
    alice = user_id(pg.owner, "alice")
    with pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        on = lambda d: [(r.rate, r.valid_from) for r in c.execute(  # noqa: E731
            text("select rate, valid_from from catalog.current_rates(:d)"), {"d": d})]
        assert on(date(2025, 9, 21)) == [(Decimal("12.00"), date(2025, 4, 1))]
        assert on(date(2025, 9, 22)) == [(Decimal("18.00"), date(2025, 9, 22))]
        assert on(date(2025, 3, 31)) == []


def test_the_interface_for_sales(shop):
    pg, biz = shop
    p = make(pg, biz, rate="12", valid_from="2025-04-01")
    post(pg, url(biz, f"/{p['id']}/rates"), {"rate": "18", "valid_from": "2026-10-20"})
    body = product(code="EX-2", tax_category="exempt", hsn=None)
    body.pop("rate")
    ex = post(pg, url(biz), body).json()
    alice = user_id(pg.owner, "alice")
    with pg.app_rw.begin() as c:
        ctx(c, alice, biz)
        line = product_for_line(c, uuid.UUID(p["id"]), TODAY)
        assert (line.rate, line.rate_valid_from, line.rate_changed_within_warning_window) == (
            Decimal("18.00"), date(2026, 10, 20), True)
        assert isinstance(line.sale_rate, Decimal) and line.sale_rate == Decimal("45.50")
        assert product_for_line(c, uuid.UUID(p["id"]), date(2025, 1, 1)).rate is None  # no_rate_on_date
        both = products_for_lines(c, [uuid.UUID(p["id"]), uuid.UUID(ex["id"]), uuid.uuid4()], TODAY)
        assert set(both) == {uuid.UUID(p["id"]), uuid.UUID(ex["id"])}
        assert both[uuid.UUID(ex["id"])].rate is None
        counts = setup_counts(c, TODAY)
        assert (counts.active_products, counts.products_missing_hsn, counts.products_unconfirmed_rate) == (2, 1, 1)
        from platform_common.errors import Deny

        with pytest.raises(Deny):
            product_for_line(c, uuid.uuid4(), TODAY)
    assert TODAY - timedelta(days=7) == date(2026, 10, 20)
