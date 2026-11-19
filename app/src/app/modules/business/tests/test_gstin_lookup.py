"""POST /api/v1/gstin-lookup (#249, D-100) on PostgreSQL as app_rw, and the fake provider on its own.

Skipped (the API half) unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text

from app.modules.business import gstin_lookup
from app.modules.business.gstin import check_character, check_gstin

from .conftest import PG_ADMIN_URL, as_user

URL = "/api/v1/gstin-lookup"


def gstin(state="19", pan="AAPFU0939F", case="1") -> str:
    """A well-formed GSTIN whose 13th character (`case`) picks the fake provider's behaviour."""
    first14 = f"{state}{pan}{case}Z"
    return first14 + check_character(first14)


def test_the_helper_makes_well_formed_gstins():
    assert all(check_gstin(gstin(case=c)).ok for c in "1789")


# --- the fake provider on its own ----------------------------------------------------------------------------------


def test_the_fake_gives_the_same_made_up_details_every_time():
    p = gstin_lookup.FakeProvider()
    one, two = p.lookup(gstin()), p.lookup(gstin())
    assert one == two
    assert one.status == "Active"
    assert one.address.state_code == "19" and one.address.pin == "700001" and one.address.city == "Kolkata"
    assert "Demo Traders" in one.legal_name


def test_the_fake_knows_not_found_cancelled_and_down():
    p = gstin_lookup.FakeProvider()
    assert p.lookup(gstin(case="9")) is None
    assert p.lookup(gstin(case="8")).status == "Cancelled"
    with pytest.raises(gstin_lookup.LookupUnavailable):
        p.lookup(gstin(case="7"))


def test_no_setting_means_off(monkeypatch):
    monkeypatch.delenv("GSTIN_LOOKUP_PROVIDER", raising=False)
    gstin_lookup.provider.cache_clear()
    with pytest.raises(gstin_lookup.LookupOff):
        gstin_lookup.provider()


def test_an_unbuilt_vendor_fails_loudly_instead_of_falling_back_to_the_fake(monkeypatch):
    monkeypatch.setenv("GSTIN_LOOKUP_PROVIDER", "some_vendor")
    gstin_lookup.provider.cache_clear()
    with pytest.raises(RuntimeError, match="no such provider"):
        gstin_lookup.provider()
    gstin_lookup.provider.cache_clear()


def test_the_fake_is_refused_outside_debug_environments(monkeypatch):
    monkeypatch.setenv("GSTIN_LOOKUP_PROVIDER", "fake")
    monkeypatch.setattr(gstin_lookup, "debug_env", lambda: False)
    gstin_lookup.provider.cache_clear()
    with pytest.raises(RuntimeError, match="local and test"):
        gstin_lookup.provider()
    gstin_lookup.provider.cache_clear()


# --- the route ------------------------------------------------------------------------------------------------------

api = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def on(monkeypatch):
    monkeypatch.setenv("GSTIN_LOOKUP_PROVIDER", "fake")
    gstin_lookup.provider.cache_clear()
    yield
    gstin_lookup.provider.cache_clear()


def ask(pg, value, sub="alice"):
    return pg.client.post(URL, json={"gstin": value}, headers=as_user(sub))


@api
def test_a_known_gstin_returns_the_details_to_confirm(pg, on):
    r = ask(pg, gstin().lower())  # normalised on the way in
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["found"] is True and out["gstin"] == gstin() and out["source"] == "demo"
    assert out["status"] == "Active"
    assert out["address"]["state_code"] == "19" and out["address"]["pin"] == "700001"
    assert "verified" not in r.text.lower()


@api
def test_a_gstin_the_provider_does_not_know_is_found_false_not_an_error(pg, on):
    r = ask(pg, gstin(case="9"))
    assert r.status_code == 200
    assert r.json() == {"found": False, "gstin": gstin(case="9"), "legal_name": None, "trade_name": None,
                        "status": None, "address": None, "source": "demo"}


@api
def test_a_cancelled_registration_is_reported_as_the_providers_word(pg, on):
    assert ask(pg, gstin(case="8")).json()["status"] == "Cancelled"


@api
def test_a_provider_outage_is_a_503_the_form_can_ignore(pg, on):
    r = ask(pg, gstin(case="7"))
    assert r.status_code == 503 and r.json()["error"]["code"] == "lookup_unavailable"


@api
def test_off_is_a_503_lookup_off(pg, monkeypatch):
    monkeypatch.delenv("GSTIN_LOOKUP_PROVIDER", raising=False)
    gstin_lookup.provider.cache_clear()
    r = ask(pg, gstin())
    assert r.status_code == 503 and r.json()["error"]["code"] == "lookup_off"


@api
@pytest.mark.parametrize("bad, code", [("19AAPFU0939F1Z", "gstin_length"), ("19AAPFU0939F1Z!", "gstin_shape"),
                                         ("19AAPFU0939F1ZA", "gstin_check_char")])
def test_a_malformed_gstin_is_refused_before_the_provider_is_asked(pg, on, monkeypatch, bad, code):
    def boom(self, g):
        raise AssertionError("the provider must not be asked")

    monkeypatch.setattr(gstin_lookup.FakeProvider, "lookup", boom)
    r = ask(pg, bad)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == code and r.json()["error"]["field"] == "gstin"


@api
def test_it_needs_a_signed_in_caller(pg, on):
    assert pg.client.post(URL, json={"gstin": gstin()}).status_code == 401


@api
def test_the_limit_is_per_user_and_answers_429_with_retry_after(pg, on):
    with pg.owner.connect() as c:
        c.execute(text("update refdata.values set value = '3' where key = 'business.gstin_lookup.per_user_per_hour'"))
        c.execute(text("insert into refdata.loads (id, git_sha, files, rows_inserted, rows_closed, rows_updated)"
                       " values (:i, 'test', '{}', 0, 0, 1)"), {"i": uuid.uuid4()})
    assert [ask(pg, gstin()).status_code for _ in range(3)] == [200, 200, 200]
    r = ask(pg, gstin())
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 1
    assert ask(pg, gstin(), sub="bob").status_code == 200  # someone else is not locked out
