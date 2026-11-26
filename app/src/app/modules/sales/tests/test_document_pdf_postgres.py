"""Finalized-invoice PDFs (R2-M5): the job, its retry after a failure, tenant scoping, and
that the PDF is made from the stored document and says it is a practice one. The renderer
itself is tested in renderer/tests.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import json
from decimal import Decimal
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from platform_common import jobs, render
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL, new_business, seed_member
from .test_drafts_api_postgres import KOLKATA, create, draft_body, h, make_product
from .test_finalize_postgres import fin, ready_draft, switch

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def shop(pg, tmp_path):
    jobs_q, render_q, store = FakeQueue(), FakeQueue(), LocalObjectStore(tmp_path)
    set_queue(jobs_q)
    render.set_render_queue(render_q)
    set_store(store)
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "cathy", "ca")
    other = new_business(pg, "bob")
    switch(pg, True)
    try:
        yield pg, biz, other, jobs_q, render_q, store
    finally:
        switch(pg, False)
        set_queue(None)
        render.set_render_queue(None)
        set_store(None)


def _document(pg, biz):
    d = ready_draft(pg, biz)
    r = fin(pg, biz, d)
    assert r.status_code == 200, r.text
    return r.json()


def _ask(pg, biz, doc, sub="alice"):
    return pg.client.post(f"/api/v1/b/{biz}/documents/{doc['id']}/pdf", headers=h(sub))


def _status(pg, biz, doc, job_id, sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/documents/{doc['id']}/pdf/{job_id}", headers=h(sub))


def _input(store, biz, job_id):
    return json.loads(store.get_bytes(biz, f"render-input/b/{biz}/{job_id}/input.json"))


def test_the_pdf_is_made_from_the_stored_document_and_says_it_is_practice(shop):
    pg, biz, _, jobs_q, render_q, store = shop
    doc = _document(pg, biz)
    r = _ask(pg, biz, doc)
    assert r.status_code == 202 and r.json()["attempt"] == 1
    job_id = r.json()["job_id"]
    assert _status(pg, biz, doc, job_id).json()["status"] == "queued"
    jobs_q.drain(jobs.handle_message)
    assert _status(pg, biz, doc, job_id).json()["status"] == "rendering"
    assert render_q.sent == [{"key": f"render-input/b/{biz}/{job_id}/input.json"}]
    body = _input(store, biz, job_id)
    assert (body["template"], body["practice"], body["number"]) == ("invoice-document", True, doc["doc_number"])
    assert body["totals"]["total"] == doc["doc_total"]
    assert body["lines"] and body["seller"]["gstin"] == doc["gstin"]
    store.put(biz, render.document_key(biz, uuid.UUID(job_id)), b"%PDF-1.7 test", "application/pdf")
    ready = _status(pg, biz, doc, job_id).json()
    assert ready["status"] == "ready" and ready["url"]


def test_asking_twice_gives_one_job_and_one_audit_row(shop):
    pg, biz, _, jobs_q, _, _ = shop
    doc = _document(pg, biz)
    first, second = _ask(pg, biz, doc).json(), _ask(pg, biz, doc).json()
    assert first == second
    with pg.owner.connect() as c:
        n = c.execute(text("select count(*) from platform.audit_log where action = 'document.pdf_requested'")).scalar()
    assert n == 1


def test_a_failed_render_is_retried_as_attempt_two_and_the_first_stays_failed(shop):
    pg, biz, _, jobs_q, _, store = shop
    doc = _document(pg, biz)
    first = _ask(pg, biz, doc).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    store.put(biz, f"documents/b/{biz}/{first}/failed.json", b'{"error_code": "render_failed"}', "application/json")
    assert _status(pg, biz, doc, first).json() == {"status": "failed", "url": None, "error_code": "render_failed"}
    again = _ask(pg, biz, doc).json()
    assert again["attempt"] == 2 and again["job_id"] != first
    assert _status(pg, biz, doc, first).json()["status"] == "failed"  # the record stays
    jobs_q.drain(jobs.handle_message)
    store.put(biz, render.document_key(biz, uuid.UUID(again["job_id"])), b"%PDF-1.7 test", "application/pdf")
    assert _status(pg, biz, doc, again["job_id"]).json()["status"] == "ready"
    assert _ask(pg, biz, doc).json() == again  # a good one is not redone


def test_a_render_that_never_answered_is_retried_after_it_could_have_ended(shop):
    pg, biz, _, jobs_q, _, _ = shop
    doc = _document(pg, biz)
    first = _ask(pg, biz, doc).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    assert _ask(pg, biz, doc).json()["job_id"] == first
    with pg.owner.connect() as c:
        c.execute(text("update platform.jobs set updated_at = now() - :d where id = :id"),
                  {"d": render.GIVE_UP_AFTER + timedelta(minutes=1), "id": first})
    assert _ask(pg, biz, doc).json()["attempt"] == 2


def test_another_business_can_neither_ask_for_nor_poll_a_document_pdf(shop):
    pg, biz, other, jobs_q, _, _ = shop
    doc = _document(pg, biz)
    job_id = _ask(pg, biz, doc).json()["job_id"]
    for r in (_ask(pg, other, doc, sub="bob"), _status(pg, other, doc, job_id, sub="bob")):
        assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    # a business's own job id under another document id is the same 404
    assert _status(pg, biz, {"id": uuid.uuid4()}, job_id).status_code == 404
    assert _ask(pg, biz, {"id": uuid.uuid4()}).status_code == 404


def test_a_ca_can_get_the_pdf_because_it_is_a_view(shop):
    pg, biz, _, jobs_q, _, _ = shop
    doc = _document(pg, biz)
    r = _ask(pg, biz, doc, sub="cathy")
    assert r.status_code == 202
    jobs_q.drain(jobs.handle_message)
    assert _status(pg, biz, doc, r.json()["job_id"], sub="cathy").json()["status"] == "rendering"


def test_a_member_who_lost_access_before_the_job_ran_gets_a_failed_job(shop):
    pg, biz, _, jobs_q, render_q, _ = shop
    doc = _document(pg, biz)
    job_id = _ask(pg, biz, doc, sub="cathy").json()["job_id"]
    with pg.owner.begin() as c:
        c.execute(text("delete from identity.memberships where business_id = :b and user_sub = 'cathy'"), {"b": biz})
    jobs_q.drain(jobs.handle_message)
    assert render_q.sent == []
    view = _status(pg, biz, doc, job_id)
    assert view.status_code in (403, 404) or view.json().get("error_code") == "not_allowed"


def test_the_stored_document_never_changes_and_a_later_profile_edit_does_not_reach_the_pdf(shop):
    pg, biz, _, jobs_q, _, store = shop
    doc = _document(pg, biz)
    with pg.owner.connect() as c:
        c.execute(text("update business.profiles set legal_name = 'Renamed After Finalize' where business_id = :b"),
                  {"b": biz})
    job_id = _ask(pg, biz, doc).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    body = _input(store, biz, job_id)
    assert body["seller"]["name"] != "Renamed After Finalize"
    with pg.app_rw.begin() as c:
        c.execute(text("select set_config('app.tenant_id', :b, true), set_config('app.role', 'admin', true)"), {"b": str(biz)})
        with pytest.raises(Exception, match="permission denied|insert-only"):
            c.execute(text("update sales.documents set doc_total = 0 where id = :d"), {"d": doc["id"]})


def _get(pg, biz, doc_id, sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/documents/{doc_id}", headers=h(sub))


def test_a_reload_finds_the_document_its_pdf_state_and_its_stock_movements(shop):
    pg, biz, _, jobs_q, _, store = shop
    doc = _document(pg, biz)
    one = _get(pg, biz, doc["id"])
    assert one.status_code == 200
    body = one.json()
    assert body["id"] == doc["id"] and body["is_practice"] is True and body["doc_number"] == doc["doc_number"]
    assert body["stock_movements"] == 1  # one line, one sale_out
    assert len(body["lines"]) == 1 and body["buyer"]["name"] and body["place_of_supply"]
    line = body["lines"][0]
    assert line["description"] and line["hsn"] and line["taxes"]  # stored lines carry their tax split
    assert line["total"] == str(Decimal(line["taxable"]) + sum(Decimal(t["amount"]) for t in line["taxes"]))
    assert body["amount_in_words"] and body["gross_total"] and body["charges_total"] == "0.00"
    assert body["pdf"] == {"status": "none", "job_id": None, "attempt": None, "url": None, "error_code": None}
    job_id = _ask(pg, biz, doc).json()["job_id"]
    assert _get(pg, biz, doc["id"]).json()["pdf"]["status"] == "queued"
    jobs_q.drain(jobs.handle_message)
    assert _get(pg, biz, doc["id"]).json()["pdf"]["status"] == "rendering"
    store.put(biz, render.document_key(biz, uuid.UUID(job_id)), b"%PDF-1.7 test", "application/pdf")
    pdf = _get(pg, biz, doc["id"]).json()["pdf"]
    assert (pdf["status"], pdf["job_id"], pdf["attempt"]) == ("ready", job_id, 1) and pdf["url"]
    with pg.owner.connect() as c:  # reading never queues anything
        assert c.execute(text("select count(*) from platform.jobs where type = 'sales.document_pdf'")).scalar() == 1


def test_documents_are_listed_newest_first_for_this_business_only(shop):
    pg, biz, other, _, _, _ = shop
    first, second = _document(pg, biz), _document(pg, biz)
    mine = pg.client.get(f"/api/v1/b/{biz}/documents", headers=h("alice")).json()
    assert [d["id"] for d in mine["documents"]] == [second["id"], first["id"]] and mine["has_more"] is False
    page = pg.client.get(f"/api/v1/b/{biz}/documents?limit=1", headers=h("alice")).json()
    assert len(page["documents"]) == 1 and page["has_more"] is True
    assert pg.client.get(f"/api/v1/b/{other}/documents", headers=h("bob")).json()["documents"] == []


def test_documents_search_matches_number_or_buyer_within_this_business_only(shop):
    pg, biz, other, _, _, _ = shop
    doc = _document(pg, biz)
    other_doc = fin(pg, other, ready_draft(pg, other, sub="bob"), sub="bob").json()

    def search(b, q, sub="alice"):
        r = pg.client.get(f"/api/v1/b/{b}/documents", params={"q": q}, headers=h(sub))
        assert r.status_code == 200, r.text
        return [d["id"] for d in r.json()["documents"]]

    assert search(biz, doc["doc_number"]) == [doc["id"]]
    assert search(biz, doc["doc_number"][-3:].lower()) == [doc["id"]]  # part of the number, any case
    assert search(biz, doc["counterparty_name"][:3]) == [doc["id"]]
    assert search(biz, "no such buyer") == []
    assert search(biz, "%") == [] and search(biz, "_") == []  # wildcards are matched as text
    # Bob's invoice may carry the same practice number and a like-named buyer; it never shows in Alice's business.
    assert other_doc["id"] not in search(biz, other_doc["doc_number"])
    assert other_doc["id"] not in search(biz, other_doc["counterparty_name"][:3])
    assert doc["id"] not in search(other, doc["doc_number"], sub="bob")
    assert pg.client.get(f"/api/v1/b/{biz}/documents", params={"q": "x"}, headers=h("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{biz}/documents", params={"q": "x" * 101}, headers=h("alice")).status_code == 422


def test_another_business_cannot_read_a_document_and_a_ca_can(shop):
    pg, biz, other, _, _, _ = shop
    doc = _document(pg, biz)
    r = _get(pg, other, doc["id"], sub="bob")
    assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    assert _get(pg, biz, doc["id"], sub="bob").status_code == 404  # not a member of that business
    assert _get(pg, biz, doc["id"], sub="cathy").status_code == 200
    assert _get(pg, biz, str(uuid.uuid4())).status_code == 404


@pytest.mark.parametrize(("extra", "basis", "reason"), [
    ({}, "delivery", None),
    ({"ship_to": KOLKATA, "ship_to_third_party": True}, "third_party", None),
    ({"customer_collects": True}, "customer_collects", None),
    ({"pos_override": "19", "pos_override_reason": "Goods handed over in Kolkata"}, "override", "Goods handed over in Kolkata"),
])
def test_the_document_says_why_its_place_of_supply_was_chosen(shop, extra, basis, reason):
    pg, biz, other, _, _, _ = shop
    d = ready_draft(pg, biz, **extra)
    doc = fin(pg, biz, d)
    assert doc.status_code == 200, doc.text
    body = _get(pg, biz, doc.json()["id"]).json()
    assert (body["pos_basis"], body["pos_override_reason"]) == (basis, reason)
    assert _get(pg, other, doc.json()["id"], sub="bob").status_code == 404  # still this business's only


def test_a_buyer_without_a_gstin_is_placed_by_their_address(shop):
    pg, biz, _, _, _, _ = shop
    p = make_product(pg, biz, code="P-CASH", hsn="340111")
    r = create(pg, biz, draft_body(p, cash_buyer={"name": "Walk-in", "state_code": "27"}))
    assert r.status_code == 201 and r.json()["ready"] is True, r.text
    doc = fin(pg, biz, r.json())
    assert doc.status_code == 200, doc.text
    body = _get(pg, biz, doc.json()["id"]).json()
    assert (body["pos_basis"], body["pos_override_reason"]) == ("buyer_address", None)


def test_the_pdf_prints_the_mrp_and_percent_as_finalized_and_an_hsn_summary_that_equals_the_totals(shop):  # #450
    pg, biz, _, jobs_q, _, store = shop
    soap = make_product(pg, biz, code=f"S-{uuid.uuid4().hex[:6]}", hsn="340111")  # MRP 53.69 -> rate 45.50 at 18%
    cream = make_product(pg, biz, code=f"C-{uuid.uuid4().hex[:6]}", hsn="330499", name="Face cream", mrp="413.00",
                         sale_rate="350.00")
    d = ready_draft(pg, biz, lines=[
        {"product_id": soap, "quantity": "2.500", "discount_kind": "percent", "discount_value": "10"},
        {"product_id": cream, "quantity": "12", "discount_kind": "amount", "discount_value": "100.00"},
        {"product_id": soap, "quantity": "1"},
    ])
    r = fin(pg, biz, d)
    assert r.status_code == 200, r.text
    doc = r.json()
    job_id = _ask(pg, biz, doc).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    body = _input(store, biz, job_id)
    first, second, third = body["lines"]
    assert (first["mrp"], first["discount_percent"]) == ("53.69", "10")
    assert (second["mrp"], second["discount_percent"], second["discount"]) == ("413.00", None, "100.00")
    assert third["discount"] is None and third["discount_percent"] is None
    assert all("_rate" not in ln for ln in body["lines"])
    assert body["copy_label"] == "Original for Recipient"
    assert body["seller"]["pan"] == doc["gstin"][2:12]
    # one row per (HSN, rate), in first-seen order, adding up to the stored totals exactly
    summary = body["hsn_summary"]
    assert [(s["hsn"], s["rate"]) for s in summary] == [("340111", "18"), ("330499", "18")]
    assert sum(Decimal(s["taxable"]) for s in summary) == Decimal(body["totals"]["taxable"])
    for comp in body["totals"]["taxes"]:
        assert sum(Decimal(t["amount"]) for s in summary for t in s["taxes"] if t["component"] == comp["component"]) \
            == Decimal(comp["amount"])
    # the snapshot, not the live product: stored on the line
    with pg.owner.connect() as c:
        stored = c.execute(text("select mrp, discount_percent from sales.document_lines l join sales.documents d"
                                " on d.id = l.document_id where d.id = :d order by line_no"), {"d": doc["id"]}).all()
    assert stored == [(Decimal("53.69"), Decimal("10.00")), (Decimal("413.00"), None), (Decimal("53.69"), None)]


def test_pan_is_read_from_a_gstin_only_when_it_has_the_pan_shape():  # #450
    from app.modules.sales.document_pdf import pan_of

    assert pan_of("19AAPFU0939F1ZS") == "AAPFU0939F"
    assert pan_of(None) is None and pan_of("19AAPFU0939F1Z") is None and pan_of("19AAPF10939F1ZS") is None


@pytest.mark.parametrize(("ship", "name"), [
    ({**KOLKATA, "name": "Ghosh Godown"}, "Ghosh Godown"),  # a consignee named on the invoice
    ({**KOLKATA, "name": None}, "Sharma Stores"),  # no consignee named: the buyer's name
])
def test_ship_to_on_the_pdf_carries_a_name(shop, ship, name):  # #452
    pg, biz, _, jobs_q, _, store = shop
    r = fin(pg, biz, ready_draft(pg, biz, ship_to=ship, ship_to_third_party=True))
    assert r.status_code == 200, r.text
    job_id = _ask(pg, biz, r.json()).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    assert _input(store, biz, job_id)["ship_to"]["name"] == name
