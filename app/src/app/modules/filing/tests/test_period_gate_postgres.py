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


def test_a_business_with_own_invoices_exports_gstr1_only_through_the_gate(shop):  # noqa: F811
    """D-095: the gate follows "own invoices exist" (finalized or practice), not the business type."""
    pg, biz = shop
    choose(pg, biz, "monthly")
    inst = press_instances(pg, biz)

    def export():
        return pg.client.post(f"/api/v1/b/{biz}/returns/{inst}/exports", headers=as_user("alice"))

    def gated(r):
        return r.status_code == 409 and r.json()["error"]["code"] == "period_gate_closed"

    # A marketplace seller is not gated (R1 behaviour), whatever types it chose.
    seed(pg, "update business.profiles set business_types = array['retailer','online_seller'] where business_id = :b", b=biz)
    assert not gated(export())
    # The first own invoice of any kind closes it again; no business type is needed.
    seed(pg, "update business.profiles set business_types = '{}' where business_id = :b", b=biz)
    sale(pg, biz, "P-1", date(2026, 11, 3), practice=True)
    assert gated(export())


def test_a_finalized_own_invoice_also_puts_the_business_behind_the_gate(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    inst = press_instances(pg, biz)
    assert pg.client.post(f"/api/v1/b/{biz}/returns/{inst}/exports", headers=as_user("alice")).json().get("error", {}).get(
        "code") != "period_gate_closed"
    sale(pg, biz, "INV-1", date(2026, 11, 3))
    closed = pg.client.post(f"/api/v1/b/{biz}/returns/{inst}/exports", headers=as_user("alice"))
    assert (closed.status_code, closed.json()["error"]["code"]) == (409, "period_gate_closed")


def press_instances(pg, biz) -> uuid.UUID:
    """The GSTR-1 instance of November 2026, made by confirming and pressing the button once."""
    both(pg, biz)
    opened = press(pg, biz).json()
    inst = next(r["instance_id"] for r in opened["gstr1_returns"] if r["form"] == "GSTR1")
    confirm(pg, biz, "purchases_uploaded", yes=False)  # close the gate again
    return inst


# ---- R3-M4: platform files for a business that sells on both ----

def sells_on(pg, biz, **on):
    body = {"amazon": False, "flipkart": False, "meesho": False, "own_invoices": True, **on}
    r = pg.client.put(f"/api/v1/b/{biz}/channels", json=body, headers=as_user("alice"))
    assert r.status_code == 200, r.text


def no_sales(pg, biz, section, month="2026-11"):
    r = pg.client.post(f"/api/v1/b/{biz}/uploads/none-this-month", json={"section": section, "month": month},
                       headers={**as_user("alice")})
    assert r.status_code in (200, 201), r.text


def test_a_seller_on_a_platform_needs_that_platforms_files_or_a_no_sales_note(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    sells_on(pg, biz, amazon=True, meesho=True)
    both(pg, biz)
    g = gate(pg, biz).json()
    assert g["can_file"] is False and g["reasons"] == ["platform_files_missing"]
    assert g["platform_files"] == [{"platform": "amazon", "missing_months": ["2026-11"]},
                                   {"platform": "meesho", "missing_months": ["2026-11"]}]
    assert press(pg, biz).json()["error"]["code"] == "period_gate_closed"
    no_sales(pg, biz, "amazon")
    assert gate(pg, biz).json()["platform_files"] == [{"platform": "meesho", "missing_months": ["2026-11"]}]
    no_sales(pg, biz, "meesho")
    g = gate(pg, biz).json()
    assert (g["can_file"], g["platform_files"]) == (True, [])
    assert press(pg, biz).status_code == 200
    # another month is its own question
    assert gate(pg, biz, start="2026-12-01").json()["platform_files"][0]["missing_months"] == ["2026-12"]


def test_a_business_that_sells_only_here_is_not_asked_for_platform_files(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "monthly")
    both(pg, biz)
    g = gate(pg, biz).json()
    assert g["platform_files"] == [] and g["can_file"] is True


def test_a_quarter_needs_every_month_of_it_for_each_platform(shop):  # noqa: F811
    pg, biz = shop
    choose(pg, biz, "quarterly")
    sells_on(pg, biz, flipkart=True)
    both(pg, biz, kind="quarter", start="2026-10-01")
    no_sales(pg, biz, "flipkart", "2026-10")
    g = gate(pg, biz, kind="quarter", start="2026-10-01").json()
    assert g["platform_files"] == [{"platform": "flipkart", "missing_months": ["2026-11", "2026-12"]}]
    no_sales(pg, biz, "flipkart", "2026-11")
    no_sales(pg, biz, "flipkart", "2026-12")
    assert gate(pg, biz, kind="quarter", start="2026-10-01").json()["can_file"] is True
