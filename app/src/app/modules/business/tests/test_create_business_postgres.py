"""POST /api/v1/b and GET /api/v1/me/businesses on PostgreSQL as app_rw (LLD-1 §5.10;
AC-8, AC-10, AC-11, AC-21).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL, as_user, ctx, scalar, user_id

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

GSTIN = "19AAPFU0939F1ZS"  # gstin.md's 27AAPFU0939F1ZV moved to West Bengal, check character recomputed
BODY = {
    "registration": {"kind": "gstin", "gstin": GSTIN.lower()},
    "legal_name": "Vashi Essentials LLP",
    "trade_name": "Vashi Essentials",
    "address": {"line1": "12 Park St", "city": "Kolkata", "pin": "700016", "state_code": "19"},
    "turnover_band": "up_to_threshold",
    "einvoice_history": "no",
}


def create(client, sub="alice", body=None, key=None):
    return client.post("/api/v1/b", json=body or BODY,
                       headers={**as_user(sub), "Idempotency-Key": key or uuid.uuid4().hex})


def test_the_gstin_fixture_is_well_formed():
    from app.modules.business.gstin import check_gstin

    assert check_gstin(GSTIN).ok


def test_creating_a_business_makes_the_caller_its_owner_with_a_profile(pg):
    r = create(pg.client)
    assert r.status_code == 201, r.text
    bid = r.json()["business_id"]
    assert r.json() == {"business_id": bid, "warnings": []}
    alice = user_id(pg.owner, "alice")
    with pg.owner.connect() as c:
        b = c.execute(text("select created_by, status from identity.businesses where id = :b"), {"b": bid}).one()
        assert tuple(b) == (alice, "active")
        members = c.execute(text("select user_id, role, status from identity.memberships where business_id = :b"),
                            {"b": bid}).all()
        assert [tuple(m) for m in members] == [(alice, "owner", "active")]
        p = c.execute(text("select * from business.profiles where business_id = :b"), {"b": bid}).mappings().one()
        assert (p["gstin"], p["state_code"], p["registration_kind"], p["legal_name"], p["pin"]) == (
            GSTIN, "19", "gstin", "Vashi Essentials LLP", "700016"
        )
        assert p["updated_by"] == alice and p["gstin_locked_at"] is None and p["marketplaces_answered_at"] is None
        band = c.execute(text("select fy, band, set_by from business.turnover_bands where business_id = :b"),
                         {"b": bid}).one()
        assert band.band == "up_to_threshold" and band.set_by == alice and len(band.fy) == 7
        audit = c.execute(text("select action, user_id, target_id, data from platform.audit_log where business_id = :b"),
                          {"b": bid}).all()
        assert [tuple(a) for a in audit] == [("business.create", alice, uuid.UUID(bid), {"registration_kind": "gstin"})]

    r = pg.client.get("/api/v1/me/businesses", headers=as_user("alice"))
    assert r.json() == {"businesses": [
        {"business_id": bid, "display_name": "Vashi Essentials", "gstin": GSTIN, "role": "owner"}
    ]}


def test_a_retry_with_the_same_key_returns_the_first_answer_and_creates_nothing(pg):
    first = create(pg.client, key="k1")
    again = create(pg.client, key="k1")
    assert again.status_code == 201 and again.json() == first.json()
    assert scalar(pg.owner, "select count(*) from identity.businesses") == 1
    other = create(pg.client, key="k1", body={**BODY, "trade_name": "Another"})
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_mismatch"
    missing = pg.client.post("/api/v1/b", json=BODY, headers=as_user("alice"))
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "idempotency_key_required"
    # Bob's key space is his own.
    assert create(pg.client, sub="bob", key="k1").json()["business_id"] != first.json()["business_id"]


def test_the_owned_business_limit_holds(pg):
    for _ in range(5):
        assert create(pg.client).status_code == 201
    r = create(pg.client)
    assert r.status_code == 422 and r.json()["error"]["code"] == "business_limit"
    assert scalar(pg.owner, "select count(*) from identity.businesses") == 5
    # The limit is per user.
    assert create(pg.client, sub="bob").status_code == 201


def test_two_concurrent_creates_at_the_limit_minus_one_make_exactly_one_business(pg):  # AC-21
    """A holds its transaction open after creating; B starts meanwhile. With the per-user
    lock B waits, then sees A's business and is refused; without it both would commit."""
    from datetime import date

    from app.modules.business.interface import NewBusinessProfile
    from app.modules.identity.interface import create_business
    from platform_common.errors import Invalid
    from platform_common.uow import Principal, unit_of_work

    for _ in range(4):
        create(pg.client)
    alice = user_id(pg.owner, "alice")
    profile = NewBusinessProfile(**BODY)
    a_created, release = threading.Event(), threading.Event()
    results = {}

    def run(name, hold):
        try:
            with unit_of_work(Principal(user_sub="alice", request_id=name, user_id=alice)) as uow:
                create_business(uow, profile, today=date(2026, 10, 26))
                if hold:
                    a_created.set()
                    release.wait(10)
            results[name] = "created"
        except Invalid as e:
            results[name] = e.code

    a = threading.Thread(target=run, args=("a", True))
    a.start()
    assert a_created.wait(10)
    b = threading.Thread(target=run, args=("b", False))
    b.start()
    b.join(1.5)
    assert b.is_alive(), "B should be waiting on A's lock"
    release.set()
    a.join(10)
    b.join(10)
    assert results == {"a": "created", "b": "business_limit"}
    assert scalar(pg.owner, "select count(*) from identity.businesses") == 5


def test_app_rw_cannot_update_businesses_or_delete_anything_here(pg):  # AC-21 catalog
    def has(table, privilege):
        return scalar(pg.owner, "select has_table_privilege('app_rw', :t, :p)", t=table, p=privilege)

    assert not has("identity.businesses", "UPDATE")
    for table in ("business.profiles", "business.turnover_bands", "business.marketplace_channels",
                  "business.filing_frequency_history"):
        assert not has(table, "DELETE") and not has(table, "TRUNCATE")
        assert scalar(pg.owner, "select has_table_privilege('app_ro', :t, 'INSERT')", t=table) is False
    assert not has("business.filing_frequency_history", "UPDATE")


def test_bootstrap_cannot_add_a_second_owner(pg):  # AC-10
    bid = create(pg.client).json()["business_id"]
    create(pg.client, sub="bob")  # bob exists, owns another business
    alice, bob = user_id(pg.owner, "alice"), user_id(pg.owner, "bob")
    for actor, who in ((bob, bob), (alice, alice)):
        with pytest.raises(DBAPIError, match="row-level security|duplicate key"):
            with pg.app_rw.begin() as c:
                ctx(c, actor, tenant=bid)
                c.execute(text("insert into identity.memberships (id, business_id, user_id, role, status)"
                               " values (:i, :b, :u, 'owner', 'active')"), {"i": uuid.uuid4(), "b": bid, "u": who})
    # Even the creator's own business row is not a second bootstrap once a member exists.
    with pytest.raises(DBAPIError, match="row-level security"):
        with pg.app_rw.begin() as c:
            ctx(c, bob, tenant=bid)
            c.execute(text("insert into identity.memberships (id, business_id, user_id, role, status)"
                           " values (:i, :b, :u, 'owner', 'active')"), {"i": uuid.uuid4(), "b": bid, "u": bob})


@pytest.mark.parametrize(
    ("registration", "status", "code", "field"),
    [
        ({"kind": "gstin", "gstin": "19AAPFU0939F1ZT"}, 422, "gstin_check_char", "registration.gstin"),
        ({"kind": "gstin", "gstin": "19AAPFU0939F1Z"}, 422, "gstin_length", "registration.gstin"),
        ({"kind": "gstin"}, 422, "gstin_length", "registration.gstin"),
        ({"kind": "gstin", "gstin": GSTIN, "state_code": "27"}, 422, "state_code_mismatch", "registration.state_code"),
        ({"kind": "gstin", "gstin": GSTIN, "enrolment_number": "X1"}, 422, "registration_mixed",
         "registration.enrolment_number"),
        ({"kind": "enrolment", "enrolment_number": "  ", "state_code": "19"}, 422, "enrolment_number_required",
         "registration.enrolment_number"),
        ({"kind": "enrolment", "enrolment_number": "ENR123"}, 422, "state_code_required", "registration.state_code"),
        ({"kind": "enrolment", "enrolment_number": "ENR123", "gstin": GSTIN, "state_code": "19"}, 422,
         "registration_mixed", "registration.gstin"),
        ({"kind": "pan"}, 422, "invalid", "registration.kind"),
    ],
)
def test_bad_registrations_are_refused_and_nothing_is_created(pg, registration, status, code, field):
    r = create(pg.client, body={**BODY, "registration": registration})
    assert r.status_code == status, r.text
    assert (r.json()["error"]["code"], r.json()["error"].get("field")) == (code, field)
    assert scalar(pg.owner, "select count(*) from identity.businesses") == 0
    assert scalar(pg.owner, "select count(*) from business.profiles") == 0


def test_an_enrolment_number_is_stored_trimmed_with_the_chosen_state(pg):
    body = {**BODY, "registration": {"kind": "enrolment", "enrolment_number": " ENR 0042 ", "state_code": "19"},
            "trade_name": None, "legal_name": None}
    r = create(pg.client, body=body)
    assert r.status_code == 201, r.text
    row = pg.owner.connect().execute(
        text("select gstin, enrolment_number, state_code from business.profiles")).one()
    assert tuple(row) == (None, "ENR 0042", "19")
    cards = pg.client.get("/api/v1/me/businesses", headers=as_user("alice")).json()["businesses"]
    assert [(c["display_name"], c["gstin"]) for c in cards] == [("ENR 0042", None)]


def test_warnings_never_block(pg):
    from app.modules.business.gstin import check_character

    not_z = "19AAPFU0939F1C"
    not_z += check_character(not_z)
    body = {**BODY, "registration": {"kind": "gstin", "gstin": not_z},
            "address": {**BODY["address"], "state_code": "27"}}
    r = create(pg.client, body=body)
    assert r.status_code == 201 and r.json()["warnings"] == ["gstin_not_z", "address_state_mismatch"]


def test_state_codes_are_checked_against_refdata(pg, monkeypatch):
    from app.modules.business import registration

    known = {"19": "West Bengal", "27": "Maharashtra", "96": "Other Country", "97": "Other Territory"}
    monkeypatch.setattr(registration, "state_name", lambda tx, code, on: known.get(code))
    from app.modules.business.gstin import check_character

    def gstin(state):
        first = state + "AAPFU0939F1Z"
        return first + check_character(first)

    for state in ("25", "28", "96"):  # merged, retired, and place-of-supply only (gstin.md §3)
        r = create(pg.client, body={**BODY, "registration": {"kind": "gstin", "gstin": gstin(state)}, "address": None})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "state_code_unknown"), state
    bad_address = {**BODY, "address": {**BODY["address"], "state_code": "99"}}
    assert create(pg.client, body=bad_address).json()["error"]["field"] == "address.state_code"
    enrol = {**BODY, "registration": {"kind": "enrolment", "enrolment_number": "E1", "state_code": "96"}}
    assert create(pg.client, body=enrol).json()["error"]["code"] == "state_code_unknown"
    assert create(pg.client, body={**BODY, "registration": {"kind": "gstin", "gstin": gstin("97")},
                                   "address": None}).status_code == 201


def test_a_caller_without_a_session_gets_401(pg):
    r = pg.client.post("/api/v1/b", json=BODY, headers={"Idempotency-Key": "k"})
    assert r.status_code == 401
    assert pg.client.get("/api/v1/me/businesses").status_code == 401


def test_me_businesses_lists_exactly_the_callers_active_memberships(pg):  # AC-8
    a1 = create(pg.client, body={**BODY, "trade_name": "Zeta"}).json()["business_id"]
    a2 = create(pg.client, body={**BODY, "trade_name": "alpha"}).json()["business_id"]
    b1 = create(pg.client, sub="bob", body={**BODY, "trade_name": "Bob Co"}).json()["business_id"]
    alice = user_id(pg.owner, "alice")
    with pg.owner.connect() as c:
        c.execute(text("insert into identity.memberships (id, business_id, user_id, role, status)"
                       " values (:i, :b, :u, 'ca', 'deactivated')"), {"i": uuid.uuid4(), "b": b1, "u": alice})
    cards = pg.client.get("/api/v1/me/businesses", headers=as_user("alice")).json()["businesses"]
    assert [(c["business_id"], c["display_name"], c["role"]) for c in cards] == [(a2, "alpha", "owner"),
                                                                                 (a1, "Zeta", "owner")]
    with pg.owner.connect() as c:
        c.execute(text("update identity.memberships set status = 'active' where business_id = :b and user_id = :u"),
                  {"b": b1, "u": alice})
        c.execute(text("update identity.businesses set status = 'closed' where id = :b"), {"b": a1})
    cards = pg.client.get("/api/v1/me/businesses", headers=as_user("alice")).json()["businesses"]
    assert [(c["display_name"], c["role"]) for c in cards] == [("alpha", "owner"), ("Bob Co", "ca")]


def test_list_my_businesses_refuses_to_run_as_app_rw(pg):
    from app.modules.identity.interface import list_my_businesses

    with pg.app_rw.begin() as c, pytest.raises(RuntimeError, match="app_ro"):
        from sqlalchemy.orm import Session

        list_my_businesses(Session(bind=c), uuid.uuid4())


def test_display_name_reads_only_the_bound_business(pg):
    from sqlalchemy.orm import Session

    from app.modules.business.interface import display_name

    a = create(pg.client).json()["business_id"]
    b = create(pg.client, sub="bob", body={**BODY, "trade_name": None}).json()["business_id"]
    alice, bob = user_id(pg.owner, "alice"), user_id(pg.owner, "bob")
    with pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a)
        assert display_name(Session(bind=c)) == "Vashi Essentials"
    with pg.app_rw.begin() as c:
        ctx(c, bob, tenant=b)
        assert display_name(Session(bind=c)) == "Vashi Essentials LLP"  # legal name when no trade name
    with pg.app_rw.begin() as c:
        ctx(c, alice)
        assert display_name(Session(bind=c)) is None


def test_state_codes_come_from_the_loaded_refdata(pg):
    """No stub: the state codes S0b loads from gstin.md §3."""
    from app.modules.business.gstin import check_character

    first = "28AAPFU0939F1Z"  # Andhra Pradesh before 2014; not in the e-invoice master
    r = create(pg.client, body={**BODY, "registration": {"kind": "gstin", "gstin": first + check_character(first)},
                                "address": None})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "state_code_unknown")
    assert create(pg.client).status_code == 201  # 19, West Bengal
