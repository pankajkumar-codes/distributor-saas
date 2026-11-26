"""The invoice numbering settings (#461) on PostgreSQL as app_rw: defaults, save, the 16-character rule, one prefix per
document type, who may save, and another business's settings out of reach. Live numbering is never switched here.

The clock is frozen at 27 Nov 2026 IST, after the monthly scope (D-114) starts. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import pytest

from .conftest import PG_ADMIN_URL, as_user, scalar
from .test_create_business_postgres import create
from .test_profile_api_postgres import actions, add_member, biz, url  # noqa: F401 (biz is a fixture)

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def nov27(biz):  # noqa: F811
    from datetime import datetime

    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 27, 12, 0, tzinfo=IST))
    return biz


def get(pg, bid, sub="alice"):
    return pg.client.get(url(bid, "/numbering"), headers=as_user(sub))


def put(pg, bid, json, sub="alice"):
    return pg.client.put(url(bid, "/numbering"), headers=as_user(sub), json=json)


def by_kind(r):
    return {s["kind"]: s for s in r.json()["series"]}


def test_defaults_are_pankajs_format_with_nothing_saved(nov27):
    pg, bid = nov27
    r = get(pg, bid)
    assert r.status_code == 200, r.text
    s = by_kind(r)
    assert [(k, v["prefix"], v["next_number"], v["saved"]) for k, v in s.items()] == [
        ("invoice", "INV", "INV/26-11/000001", False),
        ("credit_note", "CN", "CN/26-11/000001", False),
        ("debit_note", "DN", "DN/26-11/000001", False),
    ]
    assert not s["debit_note"]["issued_in_app"] and s["invoice"]["issued_in_app"]
    body = r.json()
    assert (body["max_length"], body["max_prefix_length"], body["live"], body["live_available"]) == (16, 3, False, False)


def test_a_save_is_read_back_and_audited_and_keeps_practice_mode(nov27):
    pg, bid = nov27
    r = put(pg, bid, {"invoice": {"prefix": "si", "first_number": 41}, "credit_note": {"prefix": "SCN"}})
    assert r.status_code == 200, r.text
    s = by_kind(get(pg, bid))
    assert (s["invoice"]["prefix"], s["invoice"]["next_number"], s["invoice"]["saved"]) == ("SI", "SI/26-11/000041", True)
    assert s["credit_note"]["next_number"] == "SCN/26-11/000001"
    assert s["debit_note"]["prefix"] == "DN"  # not sent: kept as it was
    assert scalar(pg.owner, "select count(*) from business.series_settings where business_id = :b and practice_mode",
                  b=bid) == 3
    assert "business.numbering_update" in actions(pg, bid)


@pytest.mark.parametrize(("prefix", "code"), [("INVC", "prefix_too_long"), ("IN/V", "prefix_invalid"),
                                               ("", "prefix_invalid"), ("I V", "prefix_invalid")])
def test_a_prefix_that_breaks_the_16_characters_or_the_charset_is_refused(nov27, prefix, code):
    pg, bid = nov27
    r = put(pg, bid, {"invoice": {"prefix": prefix}})
    assert r.status_code == 422 and r.json()["error"]["code"] == code, r.text
    assert scalar(pg.owner, "select count(*) from business.series_settings where business_id = :b", b=bid) == 0


def test_two_document_types_cannot_share_a_prefix(nov27):
    pg, bid = nov27
    r = put(pg, bid, {"credit_note": {"prefix": "INV"}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "prefix_shared", r.text


def test_a_first_number_beyond_six_digits_is_refused(nov27):
    pg, bid = nov27
    r = put(pg, bid, {"invoice": {"prefix": "INV", "first_number": 1000000}})
    assert r.status_code == 422 and r.json()["error"]["code"] == "first_number_invalid", r.text


def test_live_numbering_cannot_be_switched_from_this_route(nov27):
    pg, bid = nov27
    r = put(pg, bid, {"invoice": {"prefix": "INV"}, "practice_mode": False})
    assert r.status_code == 422, r.text  # an unknown field is refused, never ignored


def test_billing_and_ca_read_but_cannot_save(nov27):
    pg, bid = nov27
    add_member(pg, bid, "carol", "ca")
    add_member(pg, bid, "bill", "billing")
    add_member(pg, bid, "adam", "admin")
    for sub in ("carol", "bill"):
        assert get(pg, bid, sub).status_code == 200
        assert put(pg, bid, {"invoice": {"prefix": "X"}}, sub).status_code == 404
    assert put(pg, bid, {"invoice": {"prefix": "AD"}}, "adam").status_code == 200


def test_another_business_settings_are_out_of_reach(nov27):
    pg, bid = nov27
    assert put(pg, bid, {"invoice": {"prefix": "AAA"}}).status_code == 200
    other = create(pg.client, sub="mallory").json()["business_id"]
    assert by_kind(get(pg, other, "mallory"))["invoice"]["prefix"] == "INV"
    assert get(pg, bid, "mallory").status_code == 404
    assert put(pg, bid, {"invoice": {"prefix": "MAL"}}, "mallory").status_code == 404
    assert by_kind(get(pg, bid))["invoice"]["prefix"] == "AAA"
