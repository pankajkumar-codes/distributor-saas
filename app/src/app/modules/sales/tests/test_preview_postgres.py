"""Draft preview PDFs (S4, D-042): the API queues one job per draft version, the job
writes the render input and queues its key for the renderer, and the status route says
when the PDF is there. The renderer itself is tested in renderer/tests.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import json
import uuid

import pytest

from app.modules.sales import preview
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
                             "unit_price": "45.50", "discount": "5.00%"}]
    assert doc["charges"] == [{"label": "Freight", "amount": "150.00"}]
    # No tax figures until the computation is wired in (S4-b), and nothing that looks like a number.
    assert doc["totals"] is None and doc["place_of_supply"] is None and doc["note"] == preview.TAX_LATER
    assert "number" not in json.dumps(doc)

    assert _status(pg, biz, d, job_id).json()["status"] == "rendering"
    store.put(biz, f"documents/b/{biz}/{job_id}/document.pdf", b"%PDF-1.7 test", "application/pdf")
    ready = _status(pg, biz, d, job_id, sub="cathy").json()
    assert ready["status"] == "ready" and ready["url"]


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
    assert pg.client.post(f"/api/v1/b/{biz}/drafts/{d['id']}/preview", headers=h("bob")).status_code in (403, 404)


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


def test_a_cash_sale_previews_without_a_customer(shop):
    pg, biz, _, jobs_q, render_q, store = shop
    p = make_product(pg, biz)
    d = create(pg, biz, draft_body(p, cash_buyer={"name": "Walk-in", "state_code": "27", "address": "Shop 4"})).json()
    job_id = _ask(pg, biz, d).json()["job_id"]
    jobs_q.drain(jobs.handle_message)
    doc = json.loads(store.get_bytes(biz, f"render-input/b/{biz}/{job_id}/input.json"))
    assert doc["buyer"]["name"] == "Walk-in" and doc["buyer"]["gstin"] is None and doc["buyer"]["address"] == ["Shop 4"]
    assert doc["ship_to"] is None
