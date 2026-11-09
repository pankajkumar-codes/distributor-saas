"""Draft preview PDFs (S4, D-042): the API queues one job per draft version, the job
writes the render input and queues its key for the renderer, and the status route says
when the PDF is there. The renderer itself is tested in renderer/tests.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import json
import uuid
from datetime import timedelta

import pytest

from platform_common import jobs, render
from platform_common.queue import FakeQueue, set_queue
from platform_common.storage import LocalObjectStore, set_store

from .conftest import PG_ADMIN_URL
from .test_drafts_api_postgres import create, draft_body, h, make_customer, make_product, put

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def shop(pg, tmp_path):
    from .conftest import new_business, seed_member

    jobs_q, render_q, store = FakeQueue(), FakeQueue(), LocalObjectStore(tmp_path)
    set_queue(jobs_q)
    render.set_render_queue(render_q)
    set_store(store)
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "cathy", "ca")
    seed_member(pg, biz, "bill", "billing")
    other = new_business(pg, "bob")
    try:
        yield pg, biz, other, jobs_q, render_q, store
    finally:
        set_queue(None)
        render.set_render_queue(None)
        set_store(None)


def _draft(pg, biz, **extra):
    p, c = make_product(pg, biz), make_customer(pg, biz)
    r = create(pg, biz, draft_body(p, customer_id=c, charges=[{"label": "Freight", "amount": "150"}],
                                   lines=[{"product_id": p, "quantity": "2.500", "discount_kind": "percent",
                                           "discount_value": "5"}], **extra))
    assert r.status_code == 201, r.text
    return r.json(), p


def _ask(pg, biz, d, sub="alice"):
    return pg.client.post(f"/api/v1/b/{biz}/drafts/{d['id']}/preview", headers=h(sub))


def _status(pg, biz, d, job_id, sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/drafts/{d['id']}/preview/{job_id}", headers=h(sub))


def test_a_preview_writes_the_render_input_and_queues_only_its_key(shop):
    pg, biz, _, jobs_q, render_q, store = shop
    d, _ = _draft(pg, biz)
    r = _ask(pg, biz, d)
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["draft_version"] == 1
    assert _ask(pg, biz, d).json()["job_id"] == job_id  # one job per version
    assert _status(pg, biz, d, job_id).json() == {"status": "queued", "url": None, "error_code": None}

    assert [o for o in jobs_q.drain(jobs.handle_message)] == [jobs.DONE]
    key = f"render-input/b/{biz}/{job_id}/input.json"
    assert render_q.sent == [{"key": key}]  # the key only, never the document
    doc = json.loads(store.get_bytes(biz, key))
    assert doc["v"] == 1 and doc["template"] == "invoice-draft"
    assert doc["buyer"]["name"] == "Sharma Stores" and doc["buyer"]["gstin"] == "27AAPFU0939F1ZV"
    assert doc["buyer"]["state"].endswith("(27)")
    assert doc["lines"] == [{"no": "1", "description": "Neem soap", "hsn": "3401", "quantity": "2.5", "uqc": "PCS",
                             "unit_price": "45.50", "discount": "5.00%",
                             # 2.5 x 45.50 = 113.75, less 5% = 108.06, plus the 150.00 freight
                             # (charges are taxable with the line) = 258.06; IGST 18% = 46.45.
                             "taxable": "258.06", "rate": "18",
                             "taxes": [{"component": "IGST", "rate": "18", "amount": "46.45"}], "total": "304.51"}]
    assert doc["charges"] == [{"label": "Freight", "amount": "150.00"}]
    # The computation's figures, as a save stores them (drafts.computation).
    assert doc["place_of_supply"] == "Maharashtra (27)"
    assert doc["totals"] == {"taxable": "258.06", "taxes": [{"component": "IGST", "amount": "46.45"}],
                             "round_off": None, "total": "304.51",
                             "in_words": "Rupees Three Hundred Four and Fifty One Paise Only"}
    assert doc["blocks"] == ["Line 1: Tell us last year's turnover band (FY 2025-26) to use 4-digit HSN codes. "
                             "Until then, HSN codes need at least 6 digits."]
    assert "note" not in doc
    assert "number" not in json.dumps(doc)

    assert _status(pg, biz, d, job_id).json()["status"] == "rendering"
    store.put(biz, f"documents/b/{biz}/{job_id}/document.pdf", b"%PDF-1.7 test", "application/pdf")
    ready = _status(pg, biz, d, job_id).json()
    assert ready["status"] == "ready" and ready["url"]


def test_a_ca_can_neither_ask_for_nor_poll_a_draft_preview(shop):  # drafts need documents.create (LLD-4 §9)
    pg, biz, _, jobs_q, render_q, store = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d).json()["job_id"]
    for r in (_ask(pg, biz, d, sub="cathy"), _status(pg, biz, d, job_id, sub="cathy")):
        assert (r.status_code, r.json()["error"]["code"]) == (404, "not_found")
    jobs_q.drain(jobs.handle_message)
    store.put(biz, f"documents/b/{biz}/{job_id}/document.pdf", b"%PDF-1.7 test", "application/pdf")
    assert _status(pg, biz, d, job_id, sub="cathy").status_code == 404  # not even once it's ready


def test_a_preview_job_fails_if_its_asker_became_a_ca_before_it_ran(shop):
    from sqlalchemy import text

    pg, biz, _, jobs_q, render_q, _ = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d, sub="bill").json()["job_id"]
    with pg.owner.begin() as c:
        c.execute(text("update identity.memberships set role = 'ca' where business_id = :b and user_sub = 'bill'"),
                  {"b": biz})
    jobs_q.drain(jobs.handle_message)
    assert render_q.sent == []
    assert _status(pg, biz, d, job_id).json() == {"status": "failed", "url": None, "error_code": "not_allowed"}


def test_a_new_version_gets_a_new_preview_and_a_stale_job_fails(shop):
    pg, biz, _, jobs_q, render_q, _ = shop
    d, p = _draft(pg, biz)
    first = _ask(pg, biz, d).json()["job_id"]
    assert put(pg, biz, d, draft_body(p)).status_code == 200  # saved again before the job ran
    second = _ask(pg, biz, d).json()
    assert second["draft_version"] == 2 and second["job_id"] != first
    jobs_q.drain(jobs.handle_message)
    assert _status(pg, biz, d, first).json() == {"status": "failed", "url": None, "error_code": "draft_changed"}
    assert render_q.sent == [{"key": f"render-input/b/{biz}/{second['job_id']}/input.json"}]


def test_another_business_can_neither_ask_for_nor_poll_a_preview(shop):
    pg, biz, other, jobs_q, render_q, _ = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d).json()["job_id"]
    assert _ask(pg, other, d, sub="bob").status_code == 404
    assert _status(pg, other, d, job_id, sub="bob").status_code == 404
    assert pg.client.post(f"/api/v1/b/{biz}/drafts/{d['id']}/preview", headers=h("bob")).status_code == 404
    assert _status(pg, biz, d, job_id, sub="bob").status_code == 404
    # The preview job through the generic job routes: the same 404 from either business.
    assert pg.client.get(f"/api/v1/b/{biz}/jobs/{job_id}", headers=h("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{other}/jobs/{job_id}", headers=h("bob")).status_code == 404
    assert pg.client.get(f"/api/v1/b/{biz}/jobs/{job_id}", headers=h()).status_code == 200


def test_a_job_that_is_not_this_drafts_preview_is_a_404(shop):
    pg, biz, _, jobs_q, _, _ = shop
    d, p = _draft(pg, biz)
    d2 = create(pg, biz, draft_body(p)).json()
    job_id = _ask(pg, biz, d).json()["job_id"]
    assert _status(pg, biz, d2, job_id).status_code == 404
    assert _status(pg, biz, d, str(uuid.uuid4())).status_code == 404


def test_a_deleted_draft_fails_its_preview_job(shop):
    pg, biz, _, jobs_q, render_q, _ = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d).json()["job_id"]
    assert pg.client.delete(f"/api/v1/b/{biz}/drafts/{d['id']}", headers=h(**{"If-Match": "1"})).status_code == 204
    assert jobs_q.drain(jobs.handle_message) == [jobs.FAILED]
    assert render_q.sent == []
    assert job_id  # the status route 404s with the draft gone; the job row says draft_not_found


def test_a_draft_the_computation_refuses_fails_its_job_with_that_code(shop, monkeypatch):
    from app.modules.sales import drafts
    from platform_common.errors import Invalid

    pg, biz, _, jobs_q, render_q, _ = shop
    d, _ = _draft(pg, biz)

    def refuse(uow, d, *, today):
        raise Invalid("doc_date_not_supported", "The app has no GST rules for this invoice date.", field="doc_date")

    monkeypatch.setattr(drafts, "computation", refuse)  # as for a date before the app's GST rules
    job_id = _ask(pg, biz, d).json()["job_id"]
    assert jobs_q.drain(jobs.handle_message) == [jobs.FAILED]
    assert render_q.sent == []
    assert _status(pg, biz, d, job_id).json() == {"status": "failed", "url": None,
                                                  "error_code": "doc_date_not_supported"}


def test_a_cash_sale_previews_without_a_customer(shop):
    pg, biz, _, jobs_q, render_q, store = shop
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p, cash_buyer={"name": "Walk-in", "state_code": "19", "address": "Shop 4"})).json()
    job_id = _ask(pg, biz, d).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    doc = json.loads(store.get_bytes(biz, f"render-input/b/{biz}/{job_id}/input.json"))
    assert doc["buyer"]["name"] == "Walk-in" and doc["buyer"]["gstin"] is None and doc["buyer"]["address"] == ["Shop 4"]
    assert doc["ship_to"] is None
    # Within West Bengal: CGST and SGST, half the rate each.
    assert doc["place_of_supply"] == "West Bengal (19)"
    assert [t["component"] for t in doc["lines"][0]["taxes"]] == ["CGST", "SGST"]
    assert {t["rate"] for t in doc["lines"][0]["taxes"]} == {"9"}
    assert [t["component"] for t in doc["totals"]["taxes"]] == ["CGST", "SGST"]


def test_a_render_the_renderer_gave_up_on_reports_failed_and_a_later_pdf_still_wins(shop):
    pg, biz, _, jobs_q, _, store = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    assert _status(pg, biz, d, job_id).json()["status"] == "rendering"
    store.put(biz, f"documents/b/{biz}/{job_id}/failed.json", b'{"error_code": "render_failed"}', "application/json")
    assert _status(pg, biz, d, job_id).json() == {"status": "failed", "url": None, "error_code": "render_failed"}
    store.put(biz, f"documents/b/{biz}/{job_id}/document.pdf", b"%PDF-1.7 test", "application/pdf")  # a DLQ redrive
    assert _status(pg, biz, d, job_id).json()["status"] == "ready"


def test_a_render_with_no_word_from_the_renderer_fails_after_its_last_try_could_have_ended(shop):
    """A last try killed by the Lambda timeout or out of memory writes no failed.json."""
    from sqlalchemy import text

    pg, biz, _, jobs_q, _, _ = shop
    d, _ = _draft(pg, biz)
    job_id = _ask(pg, biz, d).json()["job_id"]
    jobs_q.drain(jobs.handle_message)

    def queued_ago(delta):
        with pg.owner.connect() as c:
            c.execute(text("update platform.jobs set updated_at = now() - :d where id = :id"),
                      {"d": delta, "id": job_id})

    queued_ago(render.GIVE_UP_AFTER - timedelta(minutes=1))
    assert _status(pg, biz, d, job_id).json()["status"] == "rendering"
    queued_ago(render.GIVE_UP_AFTER + timedelta(minutes=1))
    assert _status(pg, biz, d, job_id).json() == {"status": "failed", "url": None, "error_code": "render_failed"}
