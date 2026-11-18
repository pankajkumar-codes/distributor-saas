"""The per-period gate and the file button (R3-M1, R3-M2), on PostgreSQL as app_rw. Clock fixed at 15 January 2027, so
November and December 2026 are finished months and January 2027 is not."""

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, new_business, scalar
from .test_period_files_postgres import choose, purchase, sale, seed, shop  # noqa: F401  (a fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def gate(pg, biz, start="2026-11-01", kind="month", sub="alice"):
    return pg.client.get(f"/api/v1/b/{biz}/period-gate?kind={kind}&start={start}", headers=as_user(sub))


def confirm(pg, biz, item, yes=True, start="2026-11-01", kind="month", sub="alice"):
    return pg.client.put(f"/api/v1/b/{biz}/period-gate", json={"kind": kind, "start": start, "item": item, "confirmed": yes},
                         headers=as_user(sub))


def press(pg, biz, start="2026-11-01", kind="month", sub="alice"):
    return pg.client.post(f"/api/v1/b/{biz}/period-gate/file", json={"kind": kind, "start": start}, headers=as_user(sub))


def both(pg, biz, **kw):
    for item in ("purchases_uploaded", "invoices_in_portal"):
        assert confirm(pg, biz, item, **kw).status_code == 200


def test_the_button_is_closed_until_both_confirmations_stand(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    g = gate(pg, biz).json()
    assert (g["can_file"], g["ended"], g["opens_on"]) == (False, True, "2026-12-01")
    assert g["reasons"] == ["purchases_uploaded_missing", "invoices_in_portal_missing"]
    refused = press(pg, biz)
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "period_gate_closed")
    assert confirm(pg, biz, "purchases_uploaded").json()["reasons"] == ["invoices_in_portal_missing"]
    out = confirm(pg, biz, "invoices_in_portal").json()
    assert out["can_file"] is True and out["reasons"] == []
    opened = press(pg, biz)
    assert opened.status_code == 200 and opened.json()["can_file"] is True
    forms = {r["form"] for r in opened.json()["gstr1_returns"]}
    assert "GSTR1" in forms and all(r["period_start"] == "2026-11-01" for r in opened.json()["gstr1_returns"])
    assert scalar(pg.owner, "select count(*) from platform.audit_log where action = 'filing.period_file_opened'") == 1


def test_a_period_that_has_not_ended_cannot_be_confirmed_or_filed(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    g = gate(pg, biz, start="2027-01-01").json()  # January is not over on the 15th
    assert (g["ended"], g["can_file"], g["opens_on"]) == (False, False, "2027-02-01") and "period_not_ended" in g["reasons"]
    r = confirm(pg, biz, "purchases_uploaded", start="2027-01-01")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "period_not_ended")
    assert press(pg, biz, start="2027-01-01").status_code == 409
    assert scalar(pg.owner, "select count(*) from filing.period_confirmations") == 0


def test_a_change_to_the_periods_rows_makes_a_confirmation_stale(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    sale(pg, biz, "INV-1", date(2026, 11, 3))
    both(pg, biz)
    assert gate(pg, biz).json()["can_file"] is True
    purchase(pg, biz, "SUP-LATE", date(2026, 11, 20))  # a purchase confirmed after the business said all were uploaded
    g = gate(pg, biz).json()
    assert g["can_file"] is False
    assert g["reasons"] == ["purchases_uploaded_stale", "invoices_in_portal_stale"]
    assert [c["stale"] for c in g["confirmations"]] == [True, True]
    assert press(pg, biz).json()["error"]["code"] == "period_gate_closed"
    both(pg, biz)  # confirming again, against the rows as they are now, opens it
    assert gate(pg, biz).json()["can_file"] is True
    other_month = gate(pg, biz, start="2026-12-01").json()  # another month is its own gate
    assert other_month["can_file"] is False


def test_taking_a_confirmation_back_closes_the_button_and_every_answer_is_kept(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    both(pg, biz)
    assert confirm(pg, biz, "invoices_in_portal", yes=False).json()["reasons"] == ["invoices_in_portal_missing"]
    assert scalar(pg.owner, "select count(*) from filing.period_confirmations") == 3
    with pytest.raises(Exception, match="insert-only|permission denied|immutable|cannot"):
        with pg.owner.begin() as c:
            c.execute(text("update filing.period_confirmations set confirmed = true"))
    data = scalar(pg.owner, "select string_agg(data::text, ' ') from platform.audit_log where action = 'filing.period_confirmation'")
    assert "invoices_in_portal" in data and "2026-11" in data and "INV" not in data


def test_a_quarter_is_confirmed_for_a_quarterly_filer_only(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "quarterly")
    both(pg, biz, kind="quarter", start="2026-10-01")
    g = gate(pg, biz, kind="quarter", start="2026-10-01").json()
    assert (g["can_file"], g["period_end"]) == (True, "2026-12-31")
    monthly = new_business(pg, "bob")
    choose(pg, monthly, "monthly", sub="bob")
    r = gate(pg, monthly, kind="quarter", start="2026-10-01", sub="bob")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "quarter_not_for_monthly_filer")


def test_the_due_date_is_shown_only_when_confirmed(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    both(pg, biz)
    out = press(pg, biz).json()
    assert out["due_date"] is None and out["due_dates"] == "Check on the GST portal"  # the dates in refdata are provisional


def test_roles_and_other_businesses(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    assert gate(pg, biz, sub="bill").status_code == 404  # billing cannot prepare returns
    assert confirm(pg, biz, "purchases_uploaded", sub="bill").status_code == 404
    assert gate(pg, biz, sub="cathy").status_code == 200
    other = new_business(pg, "bob")
    choose(pg, other, "monthly", sub="bob")
    both(pg, biz)
    assert gate(pg, other, sub="bob").json()["can_file"] is False  # another business's confirmations are not mine
    assert gate(pg, biz, sub="bob").status_code == 404
    assert confirm(pg, biz, "purchases_uploaded", sub="bob").status_code == 404
    bad = pg.client.put(f"/api/v1/b/{biz}/period-gate", json={"kind": "month", "start": "2026-11-01", "item": "x", "confirmed": True},
                        headers=as_user("alice"))
    assert bad.status_code == 422


def test_a_business_that_invoices_here_exports_gstr1_only_through_the_gate(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    seed(pg, "update business.profiles set business_type = 'retail' where business_id = :b", b=biz)
    inst = press_instances(pg, biz)
    closed = pg.client.post(f"/api/v1/b/{biz}/returns/{inst}/exports", headers=as_user("alice"))
    assert (closed.status_code, closed.json()["error"]["code"]) == (409, "period_gate_closed")
    # a marketplace seller who chose no business type is not gated (R1 behaviour)
    seed(pg, "update business.profiles set business_type = null where business_id = :b", b=biz)
    free = pg.client.post(f"/api/v1/b/{biz}/returns/{inst}/exports", headers=as_user("alice"))
    assert free.status_code != 409 or free.json()["error"]["code"] != "period_gate_closed"


def press_instances(pg, biz) -> uuid.UUID:
    """The GSTR-1 instance of November 2026, made by confirming and pressing the button once."""
    both(pg, biz)
    opened = press(pg, biz).json()
    inst = next(r["instance_id"] for r in opened["gstr1_returns"] if r["form"] == "GSTR1")
    confirm(pg, biz, "purchases_uploaded", yes=False)  # close the gate again
    return inst
