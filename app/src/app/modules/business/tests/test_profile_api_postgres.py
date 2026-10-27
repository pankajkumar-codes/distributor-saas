"""The business routes and Home on PostgreSQL as app_rw (LLD-1 §8.2, §8.3, §10;
AC-7, AC-12, AC-13, AC-22).

The clock is frozen at 15 Nov 2026 IST: FY 2026-27, current quarter starting 1 Oct.
Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import logging
import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL, as_user, scalar, user_id
from .test_create_business_postgres import BODY, GSTIN, create

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TODAY = date(2026, 11, 15)


@pytest.fixture()
def biz(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    r = create(pg.client)
    assert r.status_code == 201, r.text
    return pg, r.json()["business_id"]


def url(bid, path):
    return f"/api/v1/b/{bid}{path}"


def add_member(pg, bid, sub, role):
    with pg.owner.connect() as c:
        uid = c.execute(text("select identity.dev_ensure_user(:s)"), {"s": sub}).scalar()
        c.execute(text("insert into identity.memberships (id, business_id, user_id, role, status)"
                       " values (:i, :b, :u, :r, 'active')"), {"i": uuid.uuid4(), "b": bid, "u": uid, "r": role})
    return uid


def choose(client, bid, frequency, effective_from, sub="alice", key=None):
    return client.post(url(bid, "/filing-profile/frequency"),
                       json={"frequency": frequency, "effective_from": effective_from},
                       headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def actions(pg, bid):
    with pg.owner.connect() as c:
        return [a for (a,) in c.execute(text("select action from platform.audit_log where business_id = :b"
                                             " order by id"), {"b": bid})]


def frequency_on(pg, bid, gstin, on):
    from app.modules.business.interface import filing_frequency_on

    with pg.app_rw.begin() as c:
        c.execute(text("select set_config('app.tenant_id', :b, true)"), {"b": bid})
        from sqlalchemy.orm import Session

        row = filing_frequency_on(Session(bind=c), gstin, on)
        return None if row is None else (row.frequency, row.effective_from)


# --- Profile ----------------------------------------------------------------------------

def test_get_profile_shows_the_profile_band_and_readiness(biz):
    pg, bid = biz
    r = pg.client.get(url(bid, "/profile"), headers=as_user("alice"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["registration"] == {"kind": "gstin", "gstin": GSTIN, "enrolment_number": None, "state_code": "19",
                                    "state_name": body["registration"]["state_name"], "locked": False}
    assert body["registration"]["state_name"]  # from refdata.state_codes
    assert body["address"] == {"line1": "12 Park St", "line2": None, "city": "Kolkata", "pin": "700016",
                               "state_code": "19"}
    assert body["turnover_band"] == {"fy": "2026-27", "band": "up_to_threshold", "declared_turnover": None}
    assert body["ready_for_documents"] == {"ok": True, "missing": []}


def test_patch_changes_only_the_fields_sent_and_audits_their_names(biz):
    pg, bid = biz
    r = pg.client.patch(url(bid, "/profile"), headers=as_user("alice"),
                        json={"legal_name": "  ", "address": {"state_code": "27"}})
    assert r.status_code == 200, r.text
    p = r.json()["profile"]
    assert r.json()["warnings"] == ["address_state_mismatch"]
    assert p["legal_name"] is None and p["address"]["line1"] == "12 Park St" and p["address"]["state_code"] == "27"
    assert p["ready_for_documents"] == {"ok": False, "missing": ["legal_name"]}
    with pg.owner.connect() as c:
        data = c.execute(text("select data from platform.audit_log where action = 'business.profile_update'")).scalar()
    assert data == {"fields": ["address_state_code", "legal_name"]}
    # Nothing changed: no audit row.
    assert pg.client.patch(url(bid, "/profile"), headers=as_user("alice"), json={"trade_name": "Vashi Essentials"}
                           ).status_code == 200
    assert actions(pg, bid).count("business.profile_update") == 1
    # null clears the whole address; unknown fields are refused.
    assert pg.client.patch(url(bid, "/profile"), headers=as_user("alice"), json={"address": None}
                           ).json()["profile"]["ready_for_documents"]["missing"] == ["legal_name", "address"]
    assert pg.client.patch(url(bid, "/profile"), headers=as_user("alice"), json={"gstin_locked_at": None}
                           ).status_code == 422


def test_a_registration_change_recomputes_the_state_from_the_gstin(biz):
    from app.modules.business.gstin import check_character

    pg, bid = biz
    other = "27AAPFU0939F1Z"
    other += check_character(other)
    r = pg.client.patch(url(bid, "/profile"), headers=as_user("alice"),
                        json={"registration": {"kind": "gstin", "gstin": other}})
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["registration"]["state_code"] == "27"
    assert r.json()["warnings"] == ["address_state_mismatch"]  # no frequency yet, so nothing carried
    bad = pg.client.patch(url(bid, "/profile"), headers=as_user("alice"),
                          json={"registration": {"kind": "gstin", "gstin": GSTIN[:-1] + "A"}})
    assert (bad.status_code, bad.json()["error"]["code"]) == (422, "gstin_check_char")


# --- AC-13: the GSTIN lock ---------------------------------------------------------------

def test_after_lock_gstin_a_registration_change_is_409_and_the_trigger_backs_it(biz):
    from app.modules.business.interface import lock_gstin
    from platform_common.uow import Principal, unit_of_work

    pg, bid = biz
    alice = user_id(pg.owner, "alice")
    principal = Principal(user_sub="alice", request_id="t", user_id=alice, business_id=uuid.UUID(bid), role="owner")
    for _ in range(2):  # the second call does nothing
        with unit_of_work(principal) as uow:
            lock_gstin(uow)
    assert actions(pg, bid).count("business.gstin_locked") == 1

    enrol = {"registration": {"kind": "enrolment", "enrolment_number": "E1", "state_code": "19"}}
    r = pg.client.patch(url(bid, "/profile"), headers=as_user("alice"), json=enrol)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "gstin_locked")
    # The same registration again is not a change; other fields still edit.
    same = {"registration": {"kind": "gstin", "gstin": GSTIN}, "trade_name": "Vashi"}
    assert pg.client.patch(url(bid, "/profile"), headers=as_user("alice"), json=same).status_code == 200
    assert pg.client.get(url(bid, "/profile"), headers=as_user("alice")).json()["registration"]["locked"] is True

    for sql in ("update business.profiles set gstin = '19AAPFU0939F1ZS', state_code = '19',"
                " registration_kind = 'gstin', enrolment_number = null, gstin_locked_at = null",
                "update business.profiles set registration_kind = 'enrolment', gstin = null, enrolment_number = 'E'"):
        with pytest.raises(DBAPIError) as e, pg.app_rw.begin() as c:
            c.execute(text("select set_config('app.tenant_id', :b, true)"), {"b": bid})
            c.execute(text(sql))
        assert e.value.orig.sqlstate == "BGL01"


# --- AC-12: filing frequency -------------------------------------------------------------

def test_the_first_row_may_start_at_the_fy_start_and_later_ones_not_in_the_past(biz):
    pg, bid = biz
    r = choose(pg.client, bid, "quarterly", "2026-04-01")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["warnings"] == ["window_unknown"] and body["superseded_instances"] == []
    assert body["row"]["gstin"] == GSTIN and body["row"]["warnings"] == ["window_unknown"]

    past = choose(pg.client, bid, "monthly", "2026-07-01")
    assert (past.status_code, past.json()["error"]["code"]) == (422, "effective_from_past")
    odd = choose(pg.client, bid, "monthly", "2027-02-01")
    assert (odd.status_code, odd.json()["error"]["code"]) == (422, "effective_from_not_quarter_start")
    assert choose(pg.client, bid, "monthly", "2026-10-01").status_code == 201  # the current quarter
    assert choose(pg.client, bid, "quarterly", "2027-01-01").status_code == 201

    assert frequency_on(pg, bid, GSTIN, date(2026, 9, 30)) == ("quarterly", date(2026, 4, 1))
    assert frequency_on(pg, bid, GSTIN, TODAY) == ("monthly", date(2026, 10, 1))
    assert frequency_on(pg, bid, GSTIN, date(2027, 3, 31)) == ("quarterly", date(2027, 1, 1))
    assert frequency_on(pg, bid, GSTIN, date(2026, 3, 31)) is None
    with pg.owner.connect() as c:
        stored = c.execute(text("select warnings from business.filing_frequency_history order by chosen_at")).all()
        view = c.execute(text("select frequency, effective_from, valid_to from business.v_filing_profile"
                              " where business_id = :b order by effective_from"), {"b": bid}).all()
    assert [w for (w,) in stored] == [["window_unknown"]] * 3
    assert [tuple(v) for v in view] == [("quarterly", date(2026, 4, 1), date(2026, 10, 1)),
                                        ("monthly", date(2026, 10, 1), date(2027, 1, 1)),
                                        ("quarterly", date(2027, 1, 1), None)]
    assert actions(pg, bid).count("business.frequency_set") == 3

    fp = pg.client.get(url(bid, "/filing-profile"), headers=as_user("alice")).json()
    assert fp["gstin"] == GSTIN and fp["current"] == {"frequency": "monthly", "effective_from": "2026-10-01"}
    assert len(fp["history"]) == 3 and fp["history"][0]["effective_from"] == "2027-01-01"
    assert fp["window"] == {"for_quarter": "2027-01-01", "opens": None, "closes": None}
    assert fp["warnings"] == ["window_unknown"]


def test_a_later_choice_for_the_same_quarter_wins(biz):
    pg, bid = biz
    assert choose(pg.client, bid, "quarterly", "2026-10-01").status_code == 201
    assert choose(pg.client, bid, "monthly", "2026-10-01").status_code == 201
    assert frequency_on(pg, bid, GSTIN, TODAY) == ("monthly", date(2026, 10, 1))
    with pg.owner.connect() as c:
        assert c.execute(text("select count(*) from business.v_filing_profile")).scalar() == 1


def test_window_and_aato_warnings_are_stored_and_never_block(biz, monkeypatch):
    from app.modules.business import frequency

    pg, bid = biz
    monkeypatch.setattr(frequency, "window_offsets", lambda tx, on: (-2, 1))  # test input, not a product value
    assert pg.client.put(url(bid, "/turnover-bands/2025-26"), headers=as_user("alice"),
                         json={"band": "above_threshold"}).status_code == 200
    inside = choose(pg.client, bid, "monthly", "2027-01-01")  # window 1 Nov - 31 Jan
    assert inside.status_code == 201 and inside.json()["warnings"] == []
    outside = choose(pg.client, bid, "quarterly", "2027-04-01")  # window opens 1 Feb; the band is for 2026-27
    assert outside.status_code == 201 and outside.json()["warnings"] == ["outside_window"]
    aato = choose(pg.client, bid, "quarterly", "2026-10-01")
    assert aato.status_code == 201 and aato.json()["warnings"] == ["outside_window", "aato_above_threshold"]
    fp = pg.client.get(url(bid, "/filing-profile"), headers=as_user("alice")).json()
    assert fp["window"] == {"for_quarter": "2027-01-01", "opens": "2026-11-01", "closes": "2027-01-31"}
    assert fp["warnings"] == ["aato_above_threshold"]


def test_a_retry_with_the_same_key_adds_no_second_row(biz):
    pg, bid = biz
    first = choose(pg.client, bid, "quarterly", "2026-10-01", key="k")
    assert choose(pg.client, bid, "quarterly", "2026-10-01", key="k").json() == first.json()
    assert scalar(pg.owner, "select count(*) from business.filing_frequency_history") == 1


def test_an_enrolment_business_has_no_frequency_until_it_has_a_gstin(pg):
    from app import api as app_api
    from platform_common.clock import IST, FrozenClock, get_clock

    app_api.app.dependency_overrides[get_clock] = lambda: FrozenClock(datetime(2026, 11, 15, 12, 0, tzinfo=IST))
    body = {**BODY, "registration": {"kind": "enrolment", "enrolment_number": "E1", "state_code": "19"}}
    bid = create(pg.client, body=body).json()["business_id"]
    r = choose(pg.client, bid, "quarterly", "2026-10-01")
    assert (r.status_code, r.json()["error"]["code"]) == (409, "gstin_required")
    fp = pg.client.get(url(bid, "/filing-profile"), headers=as_user("alice")).json()
    assert (fp["gstin"], fp["current"], fp["history"]) == (None, None, [])
    profile = pg.client.get(url(bid, "/profile"), headers=as_user("alice")).json()
    assert profile["ready_for_documents"]["missing"] == ["gstin"]


# --- AC-22: a GSTIN change carries the frequency --------------------------------------------

def test_a_gstin_change_before_the_lock_keeps_the_frequency(biz):
    from app.modules.business.gstin import check_character

    pg, bid = biz
    assert choose(pg.client, bid, "monthly", "2026-04-01").status_code == 201
    new = "19AAPFU0939F2Z"
    new += check_character(new)
    r = pg.client.patch(url(bid, "/profile"), headers=as_user("alice"),
                        json={"registration": {"kind": "gstin", "gstin": new}})
    assert r.status_code == 200, r.text
    assert r.json()["warnings"] == ["frequency_carried"]
    assert frequency_on(pg, bid, new, TODAY) == frequency_on(pg, bid, GSTIN, TODAY) == ("monthly", date(2026, 4, 1))
    with pg.owner.connect() as c:
        carried = c.execute(text("select warnings from business.filing_frequency_history where gstin = :g"),
                            {"g": new}).scalar()
    assert carried == ["carried_from_gstin_change"]
    fp = pg.client.get(url(bid, "/filing-profile"), headers=as_user("alice")).json()
    assert fp["gstin"] == new and fp["current"]["frequency"] == "monthly" and len(fp["history"]) == 1


# --- Turnover bands and channels ---------------------------------------------------------

def test_turnover_bands_take_the_current_or_previous_fy_and_a_decimal_string(biz):
    pg, bid = biz
    r = pg.client.put(url(bid, "/turnover-bands/2026-27"), headers=as_user("alice"),
                      json={"band": "above_threshold", "declared_turnover": "52000000.50"})
    assert r.json() == {"fy": "2026-27", "band": "above_threshold", "declared_turnover": "52000000.50"}
    assert scalar(pg.owner, "select declared_turnover::text from business.turnover_bands where fy = '2026-27'"
                  ) == "52000000.50"
    old = pg.client.put(url(bid, "/turnover-bands/2024-25"), headers=as_user("alice"), json={"band": "up_to_threshold"})
    assert (old.status_code, old.json()["error"]["code"]) == (422, "fy_not_allowed")
    for bad in (5000, "1e5", "-1", "1.234"):
        assert pg.client.put(url(bid, "/turnover-bands/2026-27"), headers=as_user("alice"),
                             json={"band": "up_to_threshold", "declared_turnover": bad}).status_code == 422


def test_channels_start_unanswered_and_an_answer_is_recorded(biz):
    pg, bid = biz
    assert pg.client.get(url(bid, "/channels"), headers=as_user("alice")).json() == {
        "amazon": False, "flipkart": False, "meesho": False, "answered": False}
    r = pg.client.put(url(bid, "/channels"), headers=as_user("alice"),
                      json={"amazon": True, "flipkart": False, "meesho": True})
    assert r.json() == {"amazon": True, "flipkart": False, "meesho": True, "answered": True}
    none = pg.client.put(url(bid, "/channels"), headers=as_user("alice"),
                         json={"amazon": False, "flipkart": False, "meesho": False})
    assert none.json()["answered"] is True and none.json()["amazon"] is False
    assert pg.client.put(url(bid, "/channels"), headers=as_user("alice"), json={"amazon": True}).status_code == 422
    with pg.owner.connect() as c:
        data = [d for (d,) in c.execute(text("select data from platform.audit_log"
                                             " where action = 'business.channels_update' order by id"))]
    assert data == [{"enabled": ["amazon", "meesho"]}, {"enabled": []}]


# --- Home ---------------------------------------------------------------------------------

def test_home_checklist_follows_setup(biz):
    pg, bid = biz

    def checklist():
        r = pg.client.get(f"/api/v1/b/{bid}/home", headers=as_user("alice"))
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["filing"], body["hub"], body["insights"], body["attention"]) == (None, None, None, [])
        return body["checklist"]

    first = checklist()
    assert [i["key"] for i in first["items"]] == ["business_profile", "filing_frequency", "marketplaces",
                                                  "first_product", "first_customer", "invite_ca_or_teammate"]
    assert first["items"][0] == {"key": "business_profile", "done": True, "href": f"/b/{bid}/settings/company"}
    assert (first["done"], first["total"]) == (1, 6)
    choose(pg.client, bid, "quarterly", "2026-10-01")
    pg.client.put(url(bid, "/channels"), headers=as_user("alice"), json={"amazon": False, "flipkart": False,
                                                                          "meesho": False})
    add_member(pg, bid, "carol", "ca")
    done = {i["key"]: i["done"] for i in checklist()["items"]}
    assert done == {"business_profile": True, "filing_frequency": True, "marketplaces": True,
                    "first_product": False, "first_customer": False, "invite_ca_or_teammate": True}


def test_home_counts_a_pending_invite(biz):
    pg, bid = biz
    r = pg.client.post(url(bid, "/invitations"), headers={**as_user("alice"), "Idempotency-Key": "i1"},
                       json={"email": "carol@example.com", "role": "ca"})
    assert r.status_code in (200, 201), r.text
    items = pg.client.get(f"/api/v1/b/{bid}/home", headers=as_user("alice")).json()["checklist"]["items"]
    assert items[-1]["done"] is True


# --- AC-7: who may call ----------------------------------------------------------------

READS = [("get", "/profile"), ("get", "/filing-profile"), ("get", "/channels"), ("get", "/home")]
WRITES = [
    ("patch", "/profile", {"trade_name": "X"}),
    ("put", "/turnover-bands/2026-27", {"band": "up_to_threshold"}),
    ("post", "/filing-profile/frequency", {"frequency": "quarterly", "effective_from": "2026-10-01"}),
    ("put", "/channels", {"amazon": True, "flipkart": True, "meesho": True}),
]


def _call(client, bid, method, path, body, sub):
    headers = {**as_user(sub), "Idempotency-Key": uuid.uuid4().hex}
    return client.request(method.upper(), url(bid, path), headers=headers, json=body)


def _reasons(caplog):
    return [r.reason for r in caplog.records if getattr(r, "event", None) == "deny"]


def test_a_non_member_or_deactivated_member_gets_404_not_member(biz, caplog):
    pg, bid = biz
    dave = add_member(pg, bid, "dave", "admin")
    with pg.owner.connect() as c:
        c.execute(text("update identity.memberships set status = 'deactivated' where user_id = :u"), {"u": dave})
    create(pg.client, sub="bob")
    caplog.set_level(logging.INFO, logger="platform_common.errors")
    for sub in ("bob", "dave"):
        for method, path, *body in READS + WRITES:
            caplog.clear()
            r = _call(pg.client, bid, method, path, body[0] if body else None, sub)
            assert r.status_code == 404, (sub, path, r.text)
            assert _reasons(caplog) == ["not_member"], (sub, path)


def test_billing_and_ca_read_but_get_404_role_denied_on_writes(biz, caplog):
    pg, bid = biz
    add_member(pg, bid, "bill", "billing")
    add_member(pg, bid, "carl", "ca")
    caplog.set_level(logging.INFO, logger="platform_common.errors")
    for sub in ("bill", "carl"):
        for method, path in READS:
            assert _call(pg.client, bid, method, path, None, sub).status_code == 200, (sub, path)
        for method, path, body in WRITES:
            caplog.clear()
            r = _call(pg.client, bid, method, path, body, sub)
            assert r.status_code == 404, (sub, path, r.text)
            assert _reasons(caplog) == ["role_denied"], (sub, path)
    assert actions(pg, bid) == ["business.create"]
    add_member(pg, bid, "adam", "admin")
    for method, path, body in WRITES:
        assert _call(pg.client, bid, method, path, body, "adam").status_code in (200, 201), path


# --- Onboarding reads ---------------------------------------------------------------------

def test_state_codes_are_exactly_the_loaded_rows(biz):
    pg, _ = biz
    r = pg.client.get("/api/v1/refdata/state-codes", headers=as_user("alice"))
    assert r.status_code == 200, r.text
    with pg.owner.connect() as c:
        loaded = [tuple(x) for x in c.execute(text(
            "select code, name from refdata.state_codes where valid_from <= :d and (valid_to is null or :d < valid_to)"
            " order by code"), {"d": TODAY})]
    assert r.json()["on"] == TODAY.isoformat() and loaded
    assert [(s["code"], s["name"]) for s in r.json()["states"]] == loaded
    before_gst = pg.client.get("/api/v1/refdata/state-codes?on=2017-06-30", headers=as_user("alice")).json()
    assert before_gst == {"on": "2017-06-30", "states": []}
    assert pg.client.get("/api/v1/refdata/state-codes").status_code == 401
