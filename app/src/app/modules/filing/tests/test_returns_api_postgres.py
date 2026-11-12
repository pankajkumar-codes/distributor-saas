"""GET /b/{id}/returns (LLD-5 §11): the FY's returns with server-computed due dates."""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, new_business
from .test_periods_postgres import choose

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def api(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    return pg, new_business(pg, "alice")


def add_member(pg, bid, sub, role):
    with pg.owner.connect() as c:
        uid = c.execute(text("select identity.dev_ensure_user(:s)"), {"s": sub}).scalar()
        c.execute(
            text(
                "insert into identity.memberships (id, business_id, user_id, role, status)"
                " values (:i, :b, :u, :r, 'active')"
            ),
            {"i": uuid.uuid4(), "b": bid, "u": uid, "r": role},
        )


def get(pg, bid, sub="alice", fy="2026-27"):
    return pg.client.get(f"/api/v1/b/{bid}/returns", params={"fy": fy}, headers=as_user(sub))


def test_no_frequency_is_an_empty_list(api):
    pg, b = api
    r = get(pg, b)
    assert r.status_code == 200
    assert r.json()["filing_frequency"] is None and r.json()["returns"] == []


def test_quarterly_filer_lists_the_quarter_with_unconfirmed_dates(api):
    pg, b = api
    choose(pg, b, "quarterly")
    body = get(pg, b).json()
    assert body["filing_frequency"] == "quarterly"
    q = [x for x in body["returns"] if x["form"] in ("GSTR1", "GSTR3B") and x["period"] == "2026-Q3"]
    assert [(x["form"], x["period"], x["period_label"], x["due_date"]) for x in q] == [
        ("GSTR1", "2026-Q3", "Oct–Dec 2026", "2027-01-13"),
        ("GSTR3B", "2026-Q3", "Oct–Dec 2026", "2027-01-24"),
    ]
    assert all(x["due_date_confirmed"] is False and x["status"] == "open" for x in body["returns"])
    assert all(x["due_date_source_url"] for x in body["returns"])
    assert {x["period"] for x in body["returns"] if x["form"] == "IFF" and x["period"] < "2026-12"} == {
        "2026-10",
        "2026-11",
    }
    assert get(pg, b).json() == body  # idempotent: the same instances


def test_monthly_filer_lists_each_month(api):
    pg, b = api
    choose(pg, b, "monthly")
    got = [(x["form"], x["period"], x["due_date"]) for x in get(pg, b).json()["returns"] if x["period"] == "2026-10"]
    assert got == [("GSTR1", "2026-10", "2026-11-11"), ("GSTR3B", "2026-10", "2026-11-20")]


def test_a_confirmed_refdata_row_flips_the_marker(api):
    pg, b = api
    choose(pg, b, "monthly")
    with pg.owner.connect() as c:
        c.execute(
            text(
                "update refdata.values set status = 'expert_confirmed', confirmed_by = 'test', confirmed_on = '2026-11-12' where key = 'due.gstr1.monthly.day'"
            )
        )
    from app.modules.refdata.reader import _reset_cache

    _reset_cache()
    rows = {(x["form"], x["period"]): x for x in get(pg, b).json()["returns"]}
    assert rows[("GSTR1", "2026-10")]["due_date_confirmed"] is True
    assert rows[("GSTR3B", "2026-10")]["due_date_confirmed"] is False


def test_a_ca_can_read_and_a_stranger_gets_404(api):
    pg, b = api
    choose(pg, b, "monthly")
    add_member(pg, b, "carol", "ca")
    assert get(pg, b, "carol").status_code == 200
    new_business(pg, "bob")
    assert get(pg, b, "bob").status_code == 404


def test_a_bad_fy_is_refused(api):
    pg, b = api
    assert get(pg, b, fy="2026-29").status_code == 422
    assert get(pg, b, fy="x").status_code == 422
