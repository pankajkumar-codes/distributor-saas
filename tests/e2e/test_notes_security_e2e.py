"""Credit notes, debit notes, cancel and invoice numbering over HTTP: tenant isolation, roles, races and bad input
(API and security test run 6, #481).

Needs the finalize and live-numbering switches on (tests/e2e/enable-finalize.sql, as CI's e2e job does); skipped
otherwise. Debug sign-in only, for the extra users. Every business here is made up and two of them share one
synthetic GSTIN on purpose: two businesses with the same GSTIN must still never see each other's documents.
"""

import concurrent.futures as cf
import uuid
from decimal import Decimal

import pytest
from conftest import RUN, User, add_member

GSTIN = "19AAPFU0939F1ZS"  # synthetic
BUYER_GSTIN = "27AAPFU0939F1ZV"  # synthetic, another state
MISTAKE = {"reason": "raised_in_error", "declared_not_delivered": True}


def key():
    return {"idempotency-key": uuid.uuid4().hex}


def new_business(user, label):
    r = user.post("/api/v1/b", headers=key(), json={
        "registration": {"kind": "gstin", "gstin": GSTIN},
        "legal_name": f"E2E {RUN} {label} LLP", "trade_name": f"E2E {RUN} {label}",
        "address": {"line1": "1 Test Road", "city": "Kolkata", "pin": "700016", "state_code": "19"},
        "turnover_band": "up_to_threshold", "einvoice_history": "no", "business_type": "retail",
    })
    assert r.status_code == 201, r.text
    biz = r.json()["business_id"]
    r = user.post(f"/api/v1/b/{biz}/filing-profile/frequency", headers=key(),
                  json={"frequency": "monthly", "effective_from": "2026-10-01"})
    assert r.status_code in (200, 201), r.text
    return biz


def issue_invoice(user, biz, qty="3", price="100.00"):
    r = user.post(f"/api/v1/b/{biz}/customers", headers=key(), json={
        "name": "Sharma Stores", "gstin": BUYER_GSTIN, "billing": {"line1": "12 MG Road", "city": "Pune", "pin": "411001"}})
    assert r.status_code == 201, r.text
    customer = r.json()["id"]
    r = user.post(f"/api/v1/b/{biz}/products", headers=key(), json={
        "code": f"P-{uuid.uuid4().hex[:6]}", "name": "Neem soap", "hsn": "340111", "uqc": "PCS", "sale_rate": price,
        "mrp": "118.00", "tax_category": "taxable", "rate": {"rate": "18", "valid_from": "2026-04-01"}})
    assert r.status_code == 201, r.text
    product = r.json()["id"]
    r = user.post(f"/api/v1/b/{biz}/drafts", headers=key(),
                  json={"customer_id": customer, "lines": [{"product_id": product, "quantity": qty, "unit_price": price}]})
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["ready"], draft["computation"]["blocks"]
    r = user.post(f"/api/v1/b/{biz}/drafts/{draft['id']}/finalize", headers={**key(), "if-match": str(draft["version"])})
    assert r.status_code == 200, r.text
    inv = r.json()
    inv["product_id"] = product
    inv["line_id"] = user.get(f"/api/v1/b/{biz}/documents/{inv['id']}/credit").json()["lines"][0]["original_line_id"]
    return inv


def returned(line_id, qty):
    return {"reason": "goods_returned", "stock_treatment": "restock", "lines": [{"original_line_id": line_id, "quantity": qty}]}


def by_value(line_id, taxable, reason="value_too_low"):
    return {"reason": reason, "lines": [{"original_line_id": line_id, "taxable": taxable}]}


def post(user, path, body=None):
    return user.post(f"/api/v1{path}", headers=key(), json=body)


@pytest.fixture(scope="module")
def alice(debug_mode):
    """This file's own owners (the session's alice and bob already own their 5 businesses)."""
    if not debug_mode:
        pytest.skip("needs debug sign-in for the extra users")
    return User("notes-alice")


@pytest.fixture(scope="module")
def bob(debug_mode):
    if not debug_mode:
        pytest.skip("needs debug sign-in for the extra users")
    return User("notes-bob")


@pytest.fixture(scope="module")
def shops(alice, bob):
    a, b = new_business(alice, "Notes A"), new_business(bob, "Notes B")
    if not alice.get(f"/api/v1/b/{a}/numbering").json().get("live_available"):
        pytest.skip("finalize and live numbering are off (run tests/e2e/enable-finalize.sql)")
    return a, b


def test_another_business_s_documents_are_404_whichever_business_id_is_used(alice, bob, shops):
    a, b = shops
    inv = issue_invoice(alice, a)
    mine = issue_invoice(bob, b)  # same GSTIN, other business
    doc, line = inv["id"], inv["line_id"]
    calls = [
        ("GET", "credit", None), ("POST", "credit-notes", returned(line, "1")),
        ("POST", "debit-notes", by_value(line, "1.00")), ("POST", "cancel", MISTAKE),
    ]
    for biz in (a, b):  # bob names alice's business, then his own with alice's document
        for method, tail, body in calls:
            path = f"/api/v1/b/{biz}/documents/{doc}/{tail}"
            r = bob.get(path) if method == "GET" else bob.post(path, headers=key(), json=body)
            assert r.status_code == 404 and r.json() == {"error": {"code": "not_found", "message": "not found"}}, (biz, tail)
    for method, tail in (("GET", "numbering"), ("PUT", "numbering"), ("POST", "numbering/live")):
        r = bob.request(method, f"/api/v1/b/{a}/{tail}", headers=key(), json={"invoice": {"prefix": "HACK"}}
                        if method == "PUT" else None)
        assert r.status_code == 404, tail
    # Nothing happened to alice's invoice, and bob can't borrow her line or her invoice number either.
    assert alice.get(f"/api/v1/b/{a}/documents/{doc}/credit").json()["notes"] == []
    r = post(bob, f"/b/{b}/documents/{mine['id']}/credit-notes", returned(line, "1"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "line_not_on_invoice"
    r = post(bob, f"/b/{b}/documents/{mine['id']}/cancel", {"reason": "duplicate", "duplicate_of": inv["doc_number"]}
             if inv["doc_number"] != mine["doc_number"] else {"reason": "duplicate", "duplicate_of": "PR-9999"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "duplicate_of_not_found"


def test_roles_ca_reads_billing_issues_only_the_owner_turns_on_live(alice, shops, debug_user):
    a, _ = shops
    adam, bill, cathy = debug_user("adam"), debug_user("bill"), debug_user("cathy")
    for member, role in ((adam, "admin"), (bill, "billing"), (cathy, "ca")):
        add_member(alice, a, member, role)
    inv = issue_invoice(alice, a, qty="10")
    doc, line = inv["id"], inv["line_id"]
    assert cathy.get(f"/api/v1/b/{a}/documents/{doc}/credit").status_code == 200
    for body, tail in ((returned(line, "1"), "credit-notes"), (by_value(line, "1.00"), "debit-notes"), (MISTAKE, "cancel")):
        assert post(cathy, f"/b/{a}/documents/{doc}/{tail}", body).status_code == 404, tail
    assert post(bill, f"/b/{a}/documents/{doc}/credit-notes", returned(line, "1")).status_code == 201
    assert bill.get(f"/api/v1/b/{a}/numbering").status_code == 200
    for user in (bill, cathy):
        assert user.put(f"/api/v1/b/{a}/numbering", headers=key(), json={"invoice": {"prefix": "XYZ"}}).status_code == 404
        assert post(user, f"/b/{a}/numbering/live").status_code == 404
    r = post(adam, f"/b/{a}/numbering/live")
    assert r.status_code == 409 and r.json()["error"]["code"] == "owner_rule"
    assert alice.get(f"/api/v1/b/{a}/numbering").json()["live"] is False


@pytest.mark.parametrize("body, code", [
    ({"reason": "goods_returned", "stock_treatment": "restock", "lines": [], "is_practice": False}, "invalid"),
    ({**returned("L", "1"), "doc_date": "2099-01-01"}, "date_in_future"),
    ({**returned("L", "1"), "doc_date": "2020-01-01"}, "date_before_invoice"),
    (returned("L", "-1"), "quantity_invalid"),
    (returned("L", "1e0"), "quantity_invalid"),
    (returned("L", "4"), "credit_quantity_too_high"),
    ({**returned("L", "1"), "lines": [{"original_line_id": "L", "quantity": "1"}] * 2}, "line_repeated"),
    (returned("' or 1=1 --", "1"), "line_not_on_invoice"),
    (by_value("L", "354.01", "value_too_high"), "credit_value_too_high"),
])
def test_bad_credit_notes_are_refused(alice, shops, body, code):
    a, _ = shops
    inv = issue_invoice(alice, a)
    body = {**body, "lines": [{**ln, "original_line_id": inv["line_id"] if ln["original_line_id"] == "L"
                               else ln["original_line_id"]} for ln in body["lines"]]}
    r = post(alice, f"/b/{a}/documents/{inv['id']}/credit-notes", body)
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert alice.get(f"/api/v1/b/{a}/documents/{inv['id']}/credit").json()["notes"] == []


def test_amounts_too_large_to_store_are_422_not_500(alice, shops):
    """#481: these used to be 500 (decimal InvalidOperation, numeric field overflow)."""
    a, _ = shops
    inv = issue_invoice(alice, a)
    product = inv["product_id"]
    huge = {"customer_id": inv["customer_id"], "lines": [
        {"product_id": product, "quantity": "999999999999999.999", "unit_price": "9999999999999999.99"}]}
    for path in (f"/b/{a}/drafts", f"/b/{a}/drafts/estimate"):
        r = post(alice, path, huge)
        assert r.status_code == 422 and r.json()["error"]["code"] == "amount_too_large", (path, r.text)
    r = post(alice, f"/b/{a}/documents/{inv['id']}/debit-notes", by_value(inv["line_id"], "9999999999999999.99"))
    assert r.status_code == 422 and r.json()["error"] == {
        "code": "amount_too_large", "message": "This amount is too large. Check the quantity or amount.", "field": "lines"}


def test_parallel_credit_notes_never_credit_more_than_the_invoice(alice, shops):
    a, _ = shops
    inv = issue_invoice(alice, a, qty="10")
    with cf.ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: post(alice, f"/b/{a}/documents/{inv['id']}/credit-notes",
                                               returned(inv["line_id"], "3")), range(8)))
    made = [r for r in results if r.status_code == 201]
    assert len(made) == 3, [r.text for r in results]
    assert {r.json()["error"]["code"] for r in results if r.status_code != 201} == {"credit_quantity_too_high"}
    left = alice.get(f"/api/v1/b/{a}/documents/{inv['id']}/credit").json()
    assert left["lines"][0]["remaining_quantity"] == "1"
    assert Decimal(left["remaining_total"]) == Decimal(inv["doc_total"]) / 10


def test_cancel_and_note_at_once_only_one_wins_and_cancel_happens_once(alice, shops):
    a, _ = shops
    inv = issue_invoice(alice, a)
    with cf.ThreadPoolExecutor(2) as pool:
        cancel = pool.submit(post, alice, f"/b/{a}/documents/{inv['id']}/cancel", MISTAKE)
        note = pool.submit(post, alice, f"/b/{a}/documents/{inv['id']}/credit-notes",
                           by_value(inv["line_id"], "1.00", "value_too_high"))
    assert sorted([cancel.result().status_code, note.result().status_code]) in ([200, 422], [201, 409])
    other = issue_invoice(alice, a)
    with cf.ThreadPoolExecutor(4) as pool:
        codes = sorted(r.status_code for r in pool.map(
            lambda _: post(alice, f"/b/{a}/documents/{other['id']}/cancel", MISTAKE), range(4)))
    assert codes == [200, 409, 409, 409]


def test_the_same_key_gives_one_note_and_another_body_is_refused(alice, shops):
    a, _ = shops
    inv = issue_invoice(alice, a)
    k = {"idempotency-key": uuid.uuid4().hex}
    path = f"/api/v1/b/{a}/documents/{inv['id']}/credit-notes"
    first = alice.post(path, headers=k, json=returned(inv["line_id"], "1"))
    again = alice.post(path, headers=k, json=returned(inv["line_id"], "1"))
    other = alice.post(path, headers=k, json=returned(inv["line_id"], "2"))
    assert first.status_code == again.status_code == 201 and first.json()["id"] == again.json()["id"]
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_mismatch"


def test_live_numbering_is_per_business_even_with_the_same_gstin(alice, bob, shops):
    """Runs last in this file: it turns alice's business live, which can't be undone."""
    a, b = shops
    practice = issue_invoice(alice, a)
    r = post(alice, f"/b/{a}/numbering/live")
    assert r.status_code == 200 and r.json()["live"] is True
    assert post(alice, f"/b/{a}/numbering/live").json()["live"] is True  # again: no change
    assert bob.get(f"/api/v1/b/{b}/numbering").json()["live"] is False
    live = issue_invoice(alice, a, qty="5")
    assert not live["is_practice"] and live["doc_number"].startswith("INV/") and live["doc_number"].endswith("/000001")
    assert issue_invoice(bob, b)["is_practice"]  # bob's business, same GSTIN, still practice
    cn = post(alice, f"/b/{a}/documents/{live['id']}/credit-notes", returned(live["line_id"], "1"))
    assert cn.status_code == 201 and cn.json()["doc_number"].startswith("CN/") and not cn.json()["is_practice"]
    old = post(alice, f"/b/{a}/documents/{practice['id']}/credit-notes", returned(practice["line_id"], "1"))
    assert old.status_code == 201 and old.json()["is_practice"]  # a practice invoice keeps practice notes
    # Bob's returns never show alice's live documents, though the GSTIN is the same.
    month = live["doc_date"][:7]
    returns = bob.get(f"/api/v1/b/{b}/returns").json()["returns"]
    gstr1 = next(x["instance_id"] for x in returns if x["form"] == "GSTR1" and x["period"] == month)
    for section in ("b2b", "cdnr"):
        rows = bob.get(f"/api/v1/b/{b}/returns/{gstr1}/sections/{section}").json()["rows"]
        assert rows == [], section  # bob has only practice invoices, which never reach a return


def test_new_routes_need_credentials(anon):
    b, d = uuid.uuid4(), uuid.uuid4()
    for method, path in (("GET", f"/b/{b}/documents/{d}/credit"), ("POST", f"/b/{b}/documents/{d}/credit-notes"),
                         ("POST", f"/b/{b}/documents/{d}/debit-notes"), ("POST", f"/b/{b}/documents/{d}/cancel"),
                         ("GET", f"/b/{b}/numbering"), ("PUT", f"/b/{b}/numbering"), ("POST", f"/b/{b}/numbering/live")):
        for headers in ({}, {"authorization": "Bearer not.a.jwt"}):
            assert anon.request(method, f"/api/v1{path}", headers=headers, json={}).status_code == 401, (method, path)
