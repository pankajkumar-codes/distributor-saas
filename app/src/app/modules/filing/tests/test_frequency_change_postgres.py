"""A filing frequency change replaces the quarter's empty returns (LLD-5 L5-9, AC5-24, AC5-26; issue #476).

Before #476 a switch from monthly to quarterly left the monthly rows of a quarter that had already been shown, and the
quarterly GSTR-1 and GSTR-3B never appeared (their period start clashed with October's). Skipped unless PG_ADMIN_URL
is set.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.modules.filing.periods import ensure_instances, target_return_instance

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar, user_id
from .test_periods_postgres import GSTIN, lock, tx_for

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def api(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 27, 12, 0, tzinfo=IST))
    yield pg, new_business(pg, "alice")
    app_api.app.dependency_overrides.pop(get_clock, None)


def post(pg, b, frequency, effective_from="2026-10-01", sub="alice"):
    return pg.client.post(
        f"/api/v1/b/{b}/filing-profile/frequency",
        json={"frequency": frequency, "effective_from": effective_from},
        headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex},
    )


def returns(pg, b, sub="alice"):
    r = pg.client.get(f"/api/v1/b/{b}/returns", params={"fy": "2026-27"}, headers=as_user(sub))
    assert r.status_code == 200, r.text
    return r.json()


def q3(body, forms=("GSTR1", "GSTR3B")):
    return [(x["form"], x["period_label"], x["due_date"]) for x in body["returns"]
            if x["form"] in forms and x["period_start"] >= "2026-10-01"]


def history_rows(pg, b):
    return scalar(pg.owner, "select count(*) from business.filing_frequency_history where business_id = :b", b=b)


def test_monthly_to_quarterly_mid_quarter_shows_the_quarterly_returns(api):  # the reported case: WB, state 19
    pg, b = api
    assert post(pg, b, "monthly").status_code == 201
    assert len(q3(returns(pg, b))) == 6  # Oct, Nov, Dec x GSTR-1 and GSTR-3B, made on this first read

    r = post(pg, b, "quarterly")
    assert r.status_code == 201, r.text
    assert len(r.json()["superseded_instances"]) == 6

    body = returns(pg, b)
    assert body["filing_frequency"] == "quarterly"
    assert q3(body) == [("GSTR1", "Oct–Dec 2026", "2027-01-13"), ("GSTR3B", "Oct–Dec 2026", "2027-01-24")]
    # IFF (optional, the 13th) and PMT-06 (the 25th) for the quarter's first two months.
    assert q3(body, ("IFF", "PMT06")) == [
        ("IFF", "Oct 2026", "2026-11-13"), ("PMT06", "Oct 2026", "2026-11-25"),
        ("IFF", "Nov 2026", "2026-12-13"), ("PMT06", "Nov 2026", "2026-12-25"),
    ]  # fmt: skip
    # The replaced rows stay, superseded, each with its event.
    assert scalar(pg.owner, "select count(*) from filing.return_instances where business_id = :b"
                            " and status = 'superseded' and filer_frequency = 'monthly'", b=b) == 6
    assert scalar(pg.owner, "select count(*) from filing.instance_events where business_id = :b"
                            " and kind = 'superseded'", b=b) == 6


def test_quarterly_to_monthly_mid_quarter_shows_the_monthly_returns(api):
    pg, b = api
    post(pg, b, "quarterly")
    returns(pg, b)
    r = post(pg, b, "monthly")
    assert r.status_code == 201, r.text
    assert len(r.json()["superseded_instances"]) == 6  # 2 IFF, 2 PMT-06, GSTR-1, GSTR-3B
    assert q3(returns(pg, b)) == [
        ("GSTR1", "Oct 2026", "2026-11-11"), ("GSTR3B", "Oct 2026", "2026-11-20"),
        ("GSTR1", "Nov 2026", "2026-12-11"), ("GSTR3B", "Nov 2026", "2026-12-20"),
        ("GSTR1", "Dec 2026", "2027-01-11"), ("GSTR3B", "Dec 2026", "2027-01-20"),
    ]  # fmt: skip


def test_a_change_from_next_quarter_leaves_this_quarter_alone(api):
    pg, b = api
    post(pg, b, "monthly")
    before = q3(returns(pg, b))
    r = post(pg, b, "quarterly", "2027-01-01")
    assert r.status_code == 201 and r.json()["superseded_instances"] == []
    assert q3(returns(pg, b)) == before


def test_a_filed_return_in_the_quarter_refuses_the_change_and_writes_nothing(api):
    pg, b = api
    post(pg, b, "monthly")
    october = next(x for x in returns(pg, b)["returns"] if x["form"] == "GSTR1" and x["period"] == "2026-10")
    lock(pg, b, uuid.UUID(october["instance_id"]))
    rows_before = history_rows(pg, b)

    r = post(pg, b, "quarterly")
    assert r.status_code == 409 and r.json()["error"]["code"] == "quarter_has_documents", r.text
    assert history_rows(pg, b) == rows_before  # no history row
    assert returns(pg, b)["filing_frequency"] == "monthly"
    assert scalar(pg.owner, "select count(*) from filing.return_instances where business_id = :b"
                            " and status = 'superseded'", b=b) == 0
    assert post(pg, b, "quarterly", "2027-01-01").status_code == 201  # a later quarter is fine


def test_an_iff_holding_an_invoice_refuses_the_change(api):
    pg, b = api
    post(pg, b, "quarterly")
    alice = user_id(pg.owner, "alice")
    # A B2B invoice in October lands in October's IFF and adds to its running total (L5-3).
    tx_for(pg, b, alice, lambda tx: target_return_instance(
        tx, GSTIN, "invoice", date(2026, 10, 20), "B2B", taxable_value=Decimal("1000.00"), today=date(2026, 10, 21)))
    r = post(pg, b, "monthly")
    assert r.status_code == 409 and r.json()["error"]["code"] == "quarter_has_documents", r.text
    assert returns(pg, b)["filing_frequency"] == "quarterly"


def test_a_business_switched_before_the_fix_is_repaired_on_read(api):
    """The demo's state: monthly rows made, then a quarterly history row written by the old route (no superseding)."""
    pg, b = api
    post(pg, b, "monthly")
    returns(pg, b)
    alice = user_id(pg.owner, "alice")
    with pg.owner.begin() as c:
        c.execute(
            text("insert into business.filing_frequency_history (id, business_id, gstin, frequency, effective_from,"
                 " warnings, chosen_by) values (:i, :b, :g, 'quarterly', '2026-10-01', '{}', :u)"),
            {"i": uuid.uuid4(), "b": b, "g": GSTIN, "u": alice},
        )
    assert q3(returns(pg, b)) == [("GSTR1", "Oct–Dec 2026", "2027-01-13"), ("GSTR3B", "Oct–Dec 2026", "2027-01-24")]


def test_repair_on_read_leaves_a_quarter_with_a_filed_return_whole(api):
    pg, b = api
    post(pg, b, "monthly")
    october = next(x for x in returns(pg, b)["returns"] if x["form"] == "GSTR1" and x["period"] == "2026-10")
    lock(pg, b, uuid.UUID(october["instance_id"]))
    alice = user_id(pg.owner, "alice")
    with pg.owner.begin() as c:
        c.execute(
            text("insert into business.filing_frequency_history (id, business_id, gstin, frequency, effective_from,"
                 " warnings, chosen_by) values (:i, :b, :g, 'quarterly', '2026-10-01', '{}', :u)"),
            {"i": uuid.uuid4(), "b": b, "g": GSTIN, "u": alice},
        )
    got = tx_for(pg, b, alice, lambda tx: ensure_instances(tx, GSTIN, date(2026, 11, 27)))
    assert {(i.form, i.period) for i in got if i.form in ("GSTR1", "GSTR3B")} == {
        ("GSTR1", "2026-10"), ("GSTR3B", "2026-10"), ("GSTR1", "2026-11"), ("GSTR3B", "2026-11"),
        ("GSTR1", "2026-12"), ("GSTR3B", "2026-12"),
    }  # fmt: skip


def test_another_business_cannot_change_or_see_the_frequency(api):
    pg, b = api
    post(pg, b, "monthly")
    returns(pg, b)
    new_business(pg, "mallory")
    r = post(pg, b, "quarterly", sub="mallory")
    assert r.status_code == 404, r.text
    assert returns(pg, b)["filing_frequency"] == "monthly"
    assert scalar(pg.owner, "select count(*) from filing.return_instances where business_id = :b"
                            " and status = 'superseded'", b=b) == 0
