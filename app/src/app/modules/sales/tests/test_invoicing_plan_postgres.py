"""The invoicing plan (R2-M7, D-086): the first 10 finalized invoices are free, the 11th needs the plan unless payments
are still a placeholder; the count is the server's own; a plan change shows prorated figures.

Made-up data. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import pytest
from sqlalchemy import text

from app.modules.filing import interface as filing

from .conftest import PG_ADMIN_URL, as_user, new_business, seed_member
from .test_finalize_postgres import fin, ready_draft, switch

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

FREE = filing.FREE_INVOICES


@pytest.fixture()
def shop(pg, monkeypatch):
    biz = new_business(pg, "alice")
    seed_member(pg, biz, "cathy", "ca")
    other = new_business(pg, "bob")
    switch(pg, True)
    yield pg, biz, other, monkeypatch
    switch(pg, False)
    filing.set_invoice_check(None)


def _issue(pg, biz, n, sub="alice"):
    last = None
    for _ in range(n):
        last = fin(pg, biz, ready_draft(pg, biz, sub=sub), sub=sub)
        if last.status_code != 200:
            break
    return last


def _plan(pg, biz, sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/invoicing-plan", headers=as_user(sub))


def _counts(pg):
    with pg.owner.connect() as c:
        return c.execute(text(
            "select (select count(*) from sales.documents), (select count(*) from catalog.stock_movements"
            " where kind = 'sale_out'), (select coalesce(sum(next_value), 0) from sales.number_series)")).one()


def test_the_eleventh_invoice_needs_the_plan_and_changes_nothing_when_refused(shop):
    pg, biz, _, mp = shop
    mp.setattr(filing.plans, "FREE_FOR_NOW", False)
    filing.set_invoice_check(lambda tx, b: False)  # no plan bought
    assert _issue(pg, biz, FREE).status_code == 200
    body = _plan(pg, biz).json()
    assert (body["used"], body["remaining_free"], body["needs_plan"], body["free_for_now"]) == (FREE, 0, True, False)
    d = ready_draft(pg, biz)
    before = _counts(pg)
    r = fin(pg, biz, d)
    assert (r.status_code, r.json()["error"]["code"]) == (402, "invoice_plan_required")
    assert _counts(pg) == before  # no document, no stock out, no number taken
    with pg.owner.connect() as c:
        assert c.execute(text("select status from sales.drafts where id = :d"), {"d": d["id"]}).scalar() == "open"
    filing.set_invoice_check(lambda tx, b: True)  # the plan is bought
    assert fin(pg, biz, d).status_code == 200
    assert _plan(pg, biz).json()["used"] == FREE + 1


def test_a_finalized_invoice_is_still_returned_on_retry_after_the_free_ones_are_used(shop):
    pg, biz, _, mp = shop
    mp.setattr(filing.plans, "FREE_FOR_NOW", False)
    filing.set_invoice_check(lambda tx, b: False)
    last = _issue(pg, biz, FREE)
    d_id = last.json()["draft_id"]
    again = pg.client.post(f"/api/v1/b/{biz}/drafts/{d_id}/finalize",
                           headers={**as_user("alice"), "Idempotency-Key": "k-retry", "If-Match": "1"})
    assert again.status_code == 200 and again.json()["id"] == last.json()["id"]


def test_while_free_for_now_nothing_is_refused_and_the_screen_says_so(shop):
    pg, biz, _, _ = shop
    assert _issue(pg, biz, FREE + 1).status_code == 200
    body = _plan(pg, biz).json()
    assert body["free_for_now"] is True and body["needs_plan"] is False and body["used"] == FREE + 1
    assert (body["monthly_rupees"], body["quarterly_rupees"], body["remaining_free"]) == (999, 2499, 0)


def test_one_business_never_uses_up_another_ones_free_invoices(shop):
    pg, biz, other, mp = shop
    mp.setattr(filing.plans, "FREE_FOR_NOW", False)
    filing.set_invoice_check(lambda tx, b: False)
    assert _issue(pg, biz, FREE).status_code == 200
    assert _plan(pg, other, sub="bob").json()["used"] == 0
    assert fin(pg, other, ready_draft(pg, other, sub="bob"), sub="bob").status_code == 200
    assert _plan(pg, biz, sub="bob").status_code == 404  # not a member of that business


def test_a_broken_plan_check_closes_the_door(shop):
    pg, biz, _, mp = shop
    mp.setattr(filing.plans, "FREE_FOR_NOW", False)

    def boom(tx, b):
        raise RuntimeError("provider down")

    filing.set_invoice_check(boom)
    _issue(pg, biz, FREE)
    assert fin(pg, biz, ready_draft(pg, biz)).status_code == 402


def test_a_ca_can_see_the_plan_and_the_change_preview(shop):
    pg, biz, _, _ = shop
    assert _plan(pg, biz, sub="cathy").status_code == 200
    q = ("from_plan=invoicing&from_frequency=monthly&to_plan=invoicing&to_frequency=quarterly"
         "&days_left=15&period_days=30")
    r = pg.client.get(f"/api/v1/b/{biz}/plan-change-preview?{q}", headers=as_user("cathy"))
    assert r.status_code == 200
    assert r.json()["unused_credit"] == "499.50" and r.json()["amount_due"] == "1999.50"
    assert r.json()["free_for_now"] is True
    bad = pg.client.get(f"/api/v1/b/{biz}/plan-change-preview?{q.replace('days_left=15', 'days_left=45')}",
                        headers=as_user("cathy"))
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "plan_change_invalid")


def test_proration_is_decimal_and_a_downgrade_leaves_credit():
    one = filing.plans.prorated_change("invoicing", "quarterly", "gst_filing", "monthly", days_left=45, period_days=90)
    assert one == {"current_price": "2499.00", "unused_credit": "1249.50", "new_price": "499.00",
                   "amount_due": "0.00", "credit_left_over": "750.50"}
    third = filing.plans.prorated_change("invoicing", "monthly", "invoicing", "monthly", days_left=10, period_days=30)
    assert third["unused_credit"] == "333.00" and third["amount_due"] == "666.00"
    with pytest.raises(ValueError):  # noqa: PT011
        filing.plans.prorated_change("invoicing", "monthly", "nope", "monthly", days_left=1, period_days=30)
