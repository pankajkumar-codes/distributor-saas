"""Customers through the API on PostgreSQL, as app_rw with FORCE row-level security
(LLD-3 §12: AC3-7, AC3-9, AC3-10, AC3-11, AC3-16, AC3-18 and AC3-20 for customers).

GSTINs are gstin.md's cited example (27AAPFU0939F1ZV) and made-up numbers with a
computed check character; none is a real business's. Skipped unless PG_ADMIN_URL is set.
"""

import threading
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import api as app_api
from platform_common.clock import IST, FrozenClock, get_clock
from platform_common.errors import Conflict, Deny

from ..interface import customer_snapshot, mark_used, setup_counts
from .conftest import PG_ADMIN_URL, as_user, ctx, new_business, seed_member, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TODAY = date(2026, 10, 27)
OWN = "19AAPFU0939F1ZS"  # new_business's GSTIN
MH = "27AAPFU0939F1ZV"  # gstin.md's cited example
KA = "29AAGCB7383J1Z4"  # made up, valid check character


@pytest.fixture()
def shop(pg):
    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 10, 27, 12, tzinfo=IST))
    return pg, new_business(pg, "alice")


def url(biz, path=""):
    return f"/api/v1/b/{biz}/customers{path}"


def post(pg, path, body=None, sub="alice", key=None):
    return pg.client.post(path, json=body or {}, headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def customer(name="Sharma Stores", gstin=MH, **extra):
    body = {"name": name, "gstin": gstin, "billing": {"line1": "12 MG Road", "city": "Pune", "pin": "411001"},
            "credit_days": 30}
    body.update(extra)
    return body


def make(pg, biz, sub="alice", **kw):
    r = post(pg, url(biz), customer(**kw), sub=sub)
    assert r.status_code == 201, r.text
    return r.json()


def patch(pg, biz, c, body, version=None, sub="alice"):
    v = c["version"] if version is None else version
    return pg.client.patch(url(biz, f"/{c['id']}"), json=body, headers={**as_user(sub), "If-Match": str(v)})


def err(r):
    return r.status_code, r.json()["error"]["code"]


# --- Create and read ---------------------------------------------------------------


def test_create_derives_the_state_from_the_gstin_and_reads_back(shop):
    pg, biz = shop
    c = make(pg, biz, gstin=" 27aapfu0939f1zv ")
    assert (c["gstin"], c["gstin_state_code"], c["billing"]["state_code"], c["credit_days"]) == (MH, "27", "27", 30)
    assert (c["delivery_same_as_billing"], c["delivery"], c["version"], c["in_use"], c["status"]) == (
        True, None, 1, False, "active")
    assert c["warnings"] == []
    got = pg.client.get(url(biz, f"/{c['id']}"), headers=as_user("alice")).json()
    assert got == c
    assert post(pg, url(biz), customer(colour="red")).status_code == 422  # unknown fields are refused
    assert post(pg, url(biz), customer(billing={"state_code": "27", "country": "IN"})).status_code == 422


def test_an_unregistered_customer_needs_a_billing_state(shop):
    pg, biz = shop
    assert err(post(pg, url(biz), customer(gstin=None))) == (422, "state_code_required")
    c = make(pg, biz, gstin="", billing={"state_code": "19"})
    assert (c["gstin"], c["gstin_state_code"], c["billing"]["state_code"]) == (None, None, "19")


@pytest.mark.parametrize(
    ("gstin", "code", "message"),
    [
        ("27AAPFU0939F1Z", "gstin_invalid", "GSTIN has 14 characters; it needs 15."),
        ("27AAPFU0939F1ZA", "gstin_invalid", "GSTIN check character doesn't match; please re-check the number."),
        ("27AAPFU0939F0ZV", "gstin_invalid", None),
        (OWN, "gstin_is_own", None),
        (" 19aapfu0939f1zs", "gstin_is_own", None),
    ],
)
def test_gstin_checks_block_the_save(shop, gstin, code, message):  # AC3-11
    pg, biz = shop
    r = post(pg, url(biz), customer(gstin=gstin))
    assert err(r) == (422, code) and r.json()["error"]["field"] == "gstin"
    if message:
        assert r.json()["error"]["message"] == message
    assert pg.client.get(url(biz), headers=as_user("alice")).json()["items"] == []


def test_a_gstin_whose_first_two_digits_are_no_state_is_refused(shop):
    pg, biz = shop
    well_formed = "98AAPFU0939F1ZM"  # its check character is right; 98 is no state
    assert err(post(pg, url(biz), customer(gstin=well_formed))) == (422, "state_code_unknown")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"billing": {"pin": "011001", "state_code": "27"}}, "pin_invalid"),
        ({"billing": {"pin": "41100", "state_code": "27"}}, "pin_invalid"),
        ({"billing": {"state_code": "99"}}, "state_code_unknown"),
        ({"billing": {"state_code": "96"}}, "state_code_unknown"),
        ({"credit_days": -1}, "credit_days_invalid"),
        ({"credit_days": 366}, "credit_days_invalid"),
        ({"name": "   "}, "name_invalid"),
        ({"delivery_same_as_billing": False}, "state_code_required"),
        ({"delivery": {"city": "Mumbai"}}, "delivery_not_allowed"),
    ],
)
def test_field_checks(shop, change, code):
    pg, biz = shop
    assert err(post(pg, url(biz), customer(**change))) == (422, code)


def test_credit_days_edges_and_a_separate_delivery_address(shop):
    pg, biz = shop
    assert make(pg, biz, credit_days=0)["credit_days"] == 0
    c = make(pg, biz, name="Far Away Traders", credit_days=365, delivery_same_as_billing=False,
             delivery={"line1": "Plot 4", "city": "Bengaluru", "pin": "560001", "state_code": "29"})
    assert c["delivery"] == {"line1": "Plot 4", "line2": None, "city": "Bengaluru", "pin": "560001",
                             "state_code": "29"}


def test_warnings_never_block(shop):
    pg, biz = shop
    a = make(pg, biz, billing={"state_code": "19"})
    assert [w["code"] for w in a["warnings"]] == ["billing_state_differs"]
    b = make(pg, biz, name="Sharma Stores, Nashik branch")  # same GSTIN: branches billed separately
    assert "gstin_shared" in [w["code"] for w in b["warnings"]]
    again = pg.client.get(url(biz, f"/{a['id']}"), headers=as_user("alice")).json()
    assert {"billing_state_differs", "gstin_shared"} <= {w["code"] for w in again["warnings"]}


def test_idempotent_create(shop):
    pg, biz = shop
    key = uuid.uuid4().hex
    first = post(pg, url(biz), customer(), key=key)
    again = post(pg, url(biz), customer(), key=key)
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    assert len(pg.client.get(url(biz), headers=as_user("alice")).json()["items"]) == 1


# --- Edit, archive, delete ---------------------------------------------------------


def test_patch_needs_the_current_version_and_merges_onto_the_row(shop):  # AC3-10
    pg, biz = shop
    c = make(pg, biz)
    assert err(pg.client.patch(url(biz, f"/{c['id']}"), json={"credit_days": 7}, headers=as_user("alice"))) == (
        422, "if_match_required")
    stale = patch(pg, biz, c, {"credit_days": 7}, version=c["version"] + 1)
    assert err(stale) == (409, "stale_record")
    r = patch(pg, biz, c, {"credit_days": 7})
    assert r.status_code == 200 and (r.json()["credit_days"], r.json()["version"], r.json()["gstin"]) == (7, 2, MH)
    assert err(patch(pg, biz, c, {"name": "Old view"})) == (409, "stale_record")
    # A new GSTIN with the old billing state keeps the state and warns.
    r = patch(pg, biz, r.json(), {"gstin": KA})
    assert (r.json()["gstin_state_code"], r.json()["billing"]["state_code"]) == ("29", "27")
    assert "billing_state_differs" in [w["code"] for w in r.json()["warnings"]]
    # Removing the GSTIN keeps the billing state; a no-op PATCH doesn't bump version.
    r = patch(pg, biz, r.json(), {"gstin": None})
    assert (r.json()["gstin"], r.json()["billing"]["state_code"], r.json()["version"]) == (None, "27", 4)
    assert patch(pg, biz, r.json(), {"credit_days": 7}).json()["version"] == 4
    # Back to one address: the delivery fields are cleared.
    r = patch(pg, biz, r.json(), {"delivery_same_as_billing": False,
                                 "delivery": {"city": "Nagpur", "state_code": "27"}})
    assert r.json()["delivery"]["city"] == "Nagpur"
    r = patch(pg, biz, r.json(), {"delivery_same_as_billing": True})
    assert (r.json()["delivery_same_as_billing"], r.json()["delivery"]) == (True, None)


def test_archive_is_idempotent_and_hides_from_the_default_list(shop):
    pg, biz = shop
    c = make(pg, biz)
    a = post(pg, url(biz, f"/{c['id']}/archive")).json()
    assert (a["status"], a["version"]) == ("archived", 2)
    assert post(pg, url(biz, f"/{c['id']}/archive")).json()["version"] == 2
    assert pg.client.get(url(biz), headers=as_user("alice")).json()["items"] == []
    listed = pg.client.get(url(biz, "?status=archived"), headers=as_user("alice")).json()["items"]
    assert [x["id"] for x in listed] == [c["id"]]
    assert post(pg, url(biz, f"/{c['id']}/unarchive")).json()["status"] == "active"


def test_soft_delete_hides_the_customer_everywhere(shop):  # AC3-18 for customers
    pg, biz = shop
    c = make(pg, biz)
    gone = pg.client.delete(url(biz, f"/{c['id']}"), headers={**as_user("alice"), "If-Match": "1"})
    assert gone.status_code == 204
    assert pg.client.get(url(biz, f"/{c['id']}"), headers=as_user("alice")).status_code == 404
    assert pg.client.get(url(biz, "?status=all"), headers=as_user("alice")).json()["items"] == []
    with pg.owner.connect() as conn:
        assert conn.execute(text("select status from catalog.customers where id = :c"), {"c": c["id"]}).scalar() == (
            "deleted")
        actions = [a for (a,) in conn.execute(text(
            "select action from platform.audit_log where business_id = :b and target_kind = 'customer' order by at, id"
        ), {"b": biz})]
        data = conn.execute(text(
            "select data::text from platform.audit_log where business_id = :b and target_kind = 'customer'"
        ), {"b": biz}).scalars().all()
    assert actions == ["customer.created", "customer.deleted"]  # AC3-16
    assert not any(MH in d or "Sharma" in d for d in data)  # no GSTIN or name in audit data (§9)


def test_search_by_name_fragment_and_gstin_prefix(shop):
    pg, biz = shop
    make(pg, biz, name="Sharma Stores")
    make(pg, biz, name="Bose & Sons", gstin=KA)
    make(pg, biz, name="100% Cotton_Co", gstin=None, billing={"state_code": "19"})

    def names(q):
        r = pg.client.get(url(biz), params={"q": q}, headers=as_user("alice"))
        return sorted(x["name"] for x in r.json()["items"])

    assert names("sharma") == ["Sharma Stores"]
    assert names("29aag") == ["Bose & Sons"]
    assert names("%") == ["100% Cotton_Co"] and names("_") == ["100% Cotton_Co"]
    page = pg.client.get(url(biz), params={"limit": 2}, headers=as_user("alice")).json()
    assert len(page["items"]) == 2 and page["has_more"] is True


# --- Roles and tenant isolation ----------------------------------------------------


def test_ca_reads_and_cannot_write(shop):
    pg, biz = shop
    c = make(pg, biz)
    seed_member(pg, biz, "carol", "ca")
    assert pg.client.get(url(biz), headers=as_user("carol")).status_code == 200
    assert post(pg, url(biz), customer(), sub="carol").status_code == 404
    assert patch(pg, biz, c, {"credit_days": 1}, sub="carol").status_code == 404
    assert post(pg, url(biz, f"/{c['id']}/archive"), sub="carol").status_code == 404


def test_another_business_customer_is_not_found(shop):  # AC3-7
    pg, biz = shop
    c = make(pg, biz)
    other = new_business(pg, "bob")
    for r in (
        pg.client.get(f"/api/v1/b/{other}/customers/{c['id']}", headers=as_user("bob")),
        pg.client.patch(f"/api/v1/b/{other}/customers/{c['id']}", json={"credit_days": 1},
                        headers={**as_user("bob"), "If-Match": "1"}),
        post(pg, f"/api/v1/b/{other}/customers/{c['id']}/archive", sub="bob"),
        pg.client.delete(f"/api/v1/b/{other}/customers/{c['id']}", headers={**as_user("bob"), "If-Match": "1"}),
        pg.client.get(url(biz, f"/{c['id']}"), headers=as_user("bob")),
    ):
        assert r.status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/customers", headers=as_user("bob")).json()["items"] == []


def test_app_rw_cannot_delete_or_write_into_another_business(shop):
    pg, biz = shop
    c = make(pg, biz)
    other = new_business(pg, "bob")
    with pg.app_rw.connect() as conn, conn.begin():
        ctx(conn, user_id(pg.owner, "bob"), other)
        with pytest.raises(DBAPIError) as e, conn.begin_nested():
            conn.execute(text("delete from catalog.customers"))
        assert e.value.orig.sqlstate == "42501"
        assert conn.execute(text("update catalog.customers set credit_days = 1 where id = :c"),
                            {"c": c["id"]}).rowcount == 0
        with pytest.raises(DBAPIError) as e, conn.begin_nested():
            conn.execute(text("insert into catalog.customers (id, business_id, name, billing_state_code, created_by,"
                              " updated_by) values (:i, :b, 'X', '19', :u, :u)"),
                         {"i": uuid.uuid4(), "b": biz, "u": user_id(pg.owner, "bob")})
        assert e.value.orig.sqlstate == "42501"  # RLS with check


# --- Interface for sales and Home --------------------------------------------------


def test_snapshot_mark_used_and_counts(shop):
    pg, biz = shop
    a = make(pg, biz)
    b = make(pg, biz, name="Bose & Sons", gstin=KA, delivery_same_as_billing=False,
             delivery={"line1": "Plot 4", "city": "Bengaluru", "pin": "560001", "state_code": "29"})
    with pg.app_rw.connect() as conn, conn.begin():
        ctx(conn, user_id(pg.owner, "alice"), biz)
        snap = customer_snapshot(conn, uuid.UUID(a["id"]))
        assert (snap.gstin, snap.gstin_state_code, snap.billing.city, snap.delivery, snap.credit_days) == (
            MH, "27", "Pune", snap.billing, 30)
        assert customer_snapshot(conn, uuid.UUID(b["id"])).delivery.state_code == "29"
        with pytest.raises(Deny):
            customer_snapshot(conn, uuid.uuid4())
        mark_used(conn, [], uuid.UUID(a["id"]))
        assert setup_counts(conn, TODAY).active_customers == 2
    r = pg.client.delete(url(biz, f"/{a['id']}"), headers={**as_user("alice"), "If-Match": "1"})
    assert err(r) == (409, "customer_in_use")
    assert pg.client.get(url(biz, f"/{a['id']}"), headers=as_user("alice")).json()["version"] == 1  # unchanged
    assert post(pg, url(biz, f"/{a['id']}/archive")).json()["status"] == "archived"  # archive works either way


def test_delete_then_finalize_raises_customer_deleted(shop):  # AC3-20, delete first
    pg, biz = shop
    c = make(pg, biz)
    assert pg.client.delete(url(biz, f"/{c['id']}"), headers={**as_user("alice"), "If-Match": "1"}).status_code == 204
    with pg.app_rw.connect() as conn, conn.begin():
        ctx(conn, user_id(pg.owner, "alice"), biz)
        with pytest.raises(Conflict) as e:
            mark_used(conn, [], uuid.UUID(c["id"]))
        assert e.value.code == "customer_deleted"


def test_finalize_first_makes_a_waiting_delete_answer_in_use(shop):  # AC3-20, mark_used first
    pg, biz = shop
    c = make(pg, biz)
    alice = user_id(pg.owner, "alice")
    result = {}
    with pg.app_rw.connect() as conn:
        tx = conn.begin()
        ctx(conn, alice, biz)
        mark_used(conn, [], uuid.UUID(c["id"]))  # holds the row lock until commit

        def delete():
            result["r"] = pg.client.delete(url(biz, f"/{c['id']}"), headers={**as_user("alice"), "If-Match": "1"})

        t = threading.Thread(target=delete)
        t.start()
        t.join(timeout=1)
        assert t.is_alive()  # waiting on the lock
        tx.commit()
    t.join(timeout=10)
    assert err(result["r"]) == (409, "customer_in_use")
