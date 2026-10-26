"""Row-level security on the business tables (LLD-1 §4, LLD-0 §4.2; AC-8).

Each business table: a member reads and writes only the bound business, under app_rw
and app_ro; a request carrying a support grant id matches no tenant policy; a support
user under a live grant reads but never writes; profile_card_ro shows the caller's own
businesses' profiles under app_ro only.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL, ctx, user_id
from .test_create_business_postgres import create

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

TABLES = ("profiles", "turnover_bands", "filing_frequency_history", "marketplace_channels")


@pytest.fixture()
def two(pg):
    """Alice owns A, Bob owns B, each with a row in every business table; Sam is support."""
    a = uuid.UUID(create(pg.client, sub="alice").json()["business_id"])
    b = uuid.UUID(create(pg.client, sub="bob").json()["business_id"])
    alice, bob = user_id(pg.owner, "alice"), user_id(pg.owner, "bob")
    sam = pg.owner.connect().execute(text("select identity.dev_ensure_user('sam')")).scalar()
    with pg.owner.connect() as c:
        c.execute(text("update identity.users set is_support = true where id = :u"), {"u": sam})
        for biz, who in ((a, alice), (b, bob)):
            c.execute(text("insert into business.filing_frequency_history"
                           " (id, business_id, gstin, frequency, effective_from, chosen_by)"
                           " values (:i, :b, '19AAPFU0939F1ZS', 'quarterly', '2026-04-01', :u)"),
                      {"i": uuid.uuid4(), "b": biz, "u": who})
            c.execute(text("insert into business.marketplace_channels (business_id, marketplace, enabled, changed_by)"
                           " values (:b, 'amazon', true, :u)"), {"b": biz, "u": who})
    return pg, a, b, alice, bob, sam


def counts(c):
    return {t: c.execute(text(f"select count(*) from business.{t}")).scalar() for t in TABLES}


ONE = dict.fromkeys(TABLES, 1)
NONE = dict.fromkeys(TABLES, 0)


@pytest.mark.parametrize("role", [None, "app_ro"])
def test_a_member_sees_only_the_bound_business(two, role):
    pg, a, b, alice, *_ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a, role=role)
        assert counts(c) == ONE
        assert {r for (r,) in c.execute(text("select business_id from business.profiles"))} == {a}
    with pg.app_rw.begin() as c:
        # Binding B is the resolver's decision; the database still shows B's rows if bound,
        # so what matters is that nothing of A leaks there and nothing shows unbound.
        ctx(c, alice, role=role)
        expected = {**NONE, "profiles": 1} if role == "app_ro" else NONE  # profile_card_ro: her own A only
        assert counts(c) == expected


def test_writes_to_another_business_are_refused(two):
    pg, a, b, alice, *_ = two
    inserts = {
        "profiles": "insert into business.profiles (business_id, registration_kind, enrolment_number, state_code,"
                    " updated_by) values (:b, 'enrolment', 'E', '19', :u)",
        "turnover_bands": "insert into business.turnover_bands (business_id, fy, band, set_by)"
                          " values (:b, '2025-26', 'up_to_threshold', :u)",
        "filing_frequency_history": "insert into business.filing_frequency_history"
                                    " (id, business_id, gstin, frequency, effective_from, chosen_by)"
                                    " values (gen_random_uuid(), :b, '19AAPFU0939F1ZS', 'monthly', '2026-07-01', :u)",
        "marketplace_channels": "insert into business.marketplace_channels (business_id, marketplace, enabled,"
                                " changed_by) values (:b, 'meesho', true, :u)",
    }
    for table, sql in inserts.items():
        with pytest.raises(DBAPIError, match="row-level security"), pg.app_rw.begin() as c:
            ctx(c, alice, tenant=a)
            c.execute(text(sql), {"b": b if table != "profiles" else uuid.uuid4(), "u": alice})
    with pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a)
        for table in ("profiles", "turnover_bands", "marketplace_channels"):
            assert c.execute(text(f"update business.{table} set business_id = business_id where business_id = :b"),
                             {"b": b}).rowcount == 0
        # Moving one of A's rows to B is refused by the check clause.
    with pytest.raises(DBAPIError, match="row-level security"), pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a)
        c.execute(text("update business.marketplace_channels set business_id = :b"), {"b": b})


def test_the_frequency_history_is_insert_only_for_app_rw(two):
    pg, a, _, alice, *_ = two
    for sql in ("update business.filing_frequency_history set frequency = 'monthly'",
                "delete from business.filing_frequency_history", "delete from business.profiles"):
        with pytest.raises(DBAPIError, match="permission denied"), pg.app_rw.begin() as c:
            ctx(c, alice, tenant=a)
            c.execute(text(sql))


def test_effective_from_must_start_a_quarter(two):
    pg, a, _, alice, *_ = two
    with pytest.raises(DBAPIError, match="check constraint"), pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a)
        c.execute(text("insert into business.filing_frequency_history (id, business_id, gstin, frequency,"
                       " effective_from, chosen_by) values (gen_random_uuid(), :b, '19AAPFU0939F1ZS', 'monthly',"
                       " '2026-05-01', :u)"), {"b": a, "u": alice})


@pytest.mark.parametrize("role", [None, "app_ro"])
def test_a_support_grant_id_turns_the_tenant_policies_off(two, role):
    pg, a, _, alice, *_ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a, grant=uuid.uuid4(), role=role)
        assert counts(c) == NONE
    with pytest.raises(DBAPIError, match="row-level security"), pg.app_rw.begin() as c:
        ctx(c, alice, tenant=a, grant=uuid.uuid4())
        c.execute(text("insert into business.marketplace_channels (business_id, marketplace, enabled, changed_by)"
                       " values (:b, 'flipkart', true, :u)"), {"b": a, "u": alice})


@pytest.mark.parametrize("role", [None, "app_ro"])
def test_support_under_a_live_grant_reads_but_never_writes(two, role):
    pg, a, b, alice, _, sam = two
    gid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with pg.owner.connect() as c:
        c.execute(text("insert into identity.support_grants (id, business_id, granted_by, starts_at, expires_at)"
                       " values (:g, :b, :u, :s, :e)"),
                  {"g": gid, "b": a, "u": alice, "s": now - timedelta(minutes=1), "e": now + timedelta(hours=1)})
    with pg.app_rw.begin() as c:
        ctx(c, sam, tenant=a, grant=gid, role=role)
        assert counts(c) == ONE
        assert c.execute(text("select count(*) from business.profiles where business_id = :b"), {"b": b}).scalar() == 0
    if role is None:
        with pg.app_rw.begin() as c:
            ctx(c, sam, tenant=a, grant=gid)
            assert c.execute(text("update business.profiles set legal_name = 'x'")).rowcount == 0
        with pytest.raises(DBAPIError, match="row-level security"), pg.app_rw.begin() as c:
            ctx(c, sam, tenant=a, grant=gid)
            c.execute(text("insert into business.marketplace_channels (business_id, marketplace, enabled,"
                           " changed_by) values (:b, 'flipkart', true, :u)"), {"b": a, "u": sam})


def test_profile_cards_show_only_the_callers_active_memberships_under_app_ro(two):
    pg, a, b, alice, bob, _ = two
    with pg.app_rw.begin() as c:
        ctx(c, alice, role="app_ro")
        assert c.execute(text("select business_id from business.profiles")).scalars().all() == [a]
    with pg.owner.connect() as c:
        c.execute(text("insert into identity.memberships (id, business_id, user_id, role, status)"
                       " values (:i, :b, :u, 'ca', 'deactivated')"), {"i": uuid.uuid4(), "b": b, "u": alice})
    with pg.app_rw.begin() as c:
        ctx(c, alice, role="app_ro")
        assert c.execute(text("select business_id from business.profiles")).scalars().all() == [a]
    with pg.app_rw.begin() as c:
        ctx(c, alice)  # app_rw unbound: no card policy
        assert c.execute(text("select count(*) from business.profiles")).scalar() == 0
