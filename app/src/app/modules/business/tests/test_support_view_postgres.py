"""Support access through the two-step business_uow (LLD-0 §3.1 [L0v3-2], LLD-2 §6.2;
AC-22, AC2-10, AC2-15), through the business routes on PostgreSQL as app_rw.

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import json
import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, as_user, scalar, user_id
from .test_create_business_postgres import create

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

SUPPORT = "sam-support"


@pytest.fixture()
def biz(pg):
    r = create(pg.client)
    assert r.status_code == 201, r.text
    return pg, r.json()["business_id"]


def support_user(pg, sub=SUPPORT, *, totp=True):
    with pg.owner.connect() as c:
        uid = c.execute(text("select identity.dev_ensure_user(:s)"), {"s": sub}).scalar()
        c.execute(text("update identity.users set is_support = true,"
                       " totp_enabled_at = case when :t then now() end where id = :u"), {"u": uid, "t": totp})
    return uid


def grant(pg, bid, *, starts="-1 hour", ends="23 hours", revoked=False):
    gid = uuid.uuid4()
    with pg.owner.connect() as c:
        c.execute(
            text("insert into identity.support_grants (id, business_id, granted_by, starts_at, expires_at, revoked_at)"
                 " values (:g, :b, :u, now() + cast(:s as interval), now() + cast(:e as interval),"
                 " case when :rev then now() end)"),
            {"g": gid, "b": bid, "u": user_id(pg.owner, "alice"), "s": starts, "e": ends, "rev": revoked},
        )
    return gid


def views(pg, bid):
    with pg.owner.connect() as c:
        return c.execute(
            text("select user_id, support_grant_id, target_kind, target_id, data from platform.audit_log"
                 " where business_id = :b and action = 'support.view' order by id"),
            {"b": bid},
        ).all()


def get(pg, bid, path, sub=SUPPORT):
    return pg.client.get(f"/api/v1/b/{bid}{path}", headers=as_user(sub))


def test_a_read_under_a_grant_succeeds_and_records_one_view(biz):
    pg, bid = biz
    me, gid = support_user(pg), grant(pg, bid)
    r = get(pg, bid, "/profile")
    assert r.status_code == 200, r.text
    assert r.json()["business_id"] == bid
    [row] = views(pg, bid)
    assert (row.user_id, row.support_grant_id, row.target_kind, row.target_id) == (me, gid, "route", None)
    assert row.data == {"method": "GET", "route_template": "/b/{business_id}/profile", "object_id": None}


def test_a_view_is_recorded_even_when_the_read_then_fails(biz):
    pg, bid = biz
    support_user(pg)
    grant(pg, bid)
    missing = uuid.uuid4()
    assert get(pg, bid, f"/jobs/{missing}").status_code == 404
    [row] = views(pg, bid)
    assert row.target_id == missing
    assert row.data["route_template"] == "/b/{business_id}/jobs/{job_id}"
    assert row.data["object_id"] == str(missing)


def test_a_write_is_refused_before_the_database(biz, caplog):
    pg, bid = biz
    support_user(pg)
    grant(pg, bid)
    before = scalar(pg.owner, "select count(*) from business.marketplace_channels")
    r = pg.client.put(f"/api/v1/b/{bid}/channels", json={"amazon": True, "flipkart": False, "meesho": False},
                      headers=as_user(SUPPORT))
    assert r.status_code == 404
    assert scalar(pg.owner, "select count(*) from business.marketplace_channels") == before
    # The attempt is in the log as what it was.
    assert [v.data["method"] for v in views(pg, bid)] == ["PUT"]


@pytest.mark.parametrize("kind", ["none", "expired", "revoked", "not_started", "other_business"])
def test_without_a_live_grant_for_this_business_support_sees_nothing(biz, kind):
    pg, bid = biz
    support_user(pg)
    if kind == "expired":
        grant(pg, bid, starts="-2 days", ends="-1 day")
    elif kind == "revoked":
        grant(pg, bid, revoked=True)
    elif kind == "not_started":
        grant(pg, bid, starts="1 hour", ends="25 hours")
    elif kind == "other_business":
        r = create(pg.client, sub="bob")
        assert r.status_code == 201, r.text
        grant(pg, r.json()["business_id"])
    r = get(pg, bid, "/profile")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert views(pg, bid) == []


def test_a_support_user_without_totp_is_signed_out_of_business_routes(biz):
    pg, bid = biz
    support_user(pg, totp=False)
    grant(pg, bid)
    assert get(pg, bid, "/profile").status_code == 401
    assert views(pg, bid) == []
    assert pg.client.get("/api/v1/me/businesses", headers=as_user(SUPPORT)).status_code == 200  # can still enrol TOTP


def test_step_two_can_write_nothing(biz, monkeypatch):
    """The planted write (AC2-15): anything the route tries to write in step 2 fails."""
    from app.modules.business import profile

    pg, bid = biz
    support_user(pg)
    grant(pg, bid)
    seen = {}

    def planted(tx):
        seen["role"] = tx.execute(text("select current_user")).scalar()
        seen["read_only"] = tx.execute(text("select current_setting('transaction_read_only')")).scalar()
        tx.execute(text("insert into platform.rate_counters (bucket, window_start, count) values ('x', now(), 1)"))

    monkeypatch.setattr(profile, "channels", planted)
    assert get(pg, bid, "/channels").status_code == 500
    assert seen == {"role": "app_ro", "read_only": "on"}
    assert scalar(pg.owner, "select count(*) from platform.rate_counters where bucket = 'x'") == 0
    assert len(views(pg, bid)) == 1


def test_a_grant_revoked_between_the_steps_is_refused_in_step_two(biz, monkeypatch):
    from platform_common import uow as uow_mod

    pg, bid = biz
    support_user(pg)
    gid = grant(pg, bid)
    record = uow_mod._record_support_view

    def then_revoke(uow, request):
        record(uow, request)
        with pg.owner.connect() as c:
            c.execute(text("update identity.support_grants set revoked_at = now() where id = :g"), {"g": gid})

    monkeypatch.setattr(uow_mod, "_record_support_view", then_revoke)
    assert get(pg, bid, "/profile").status_code == 404
    assert len(views(pg, bid)) == 1  # the view was attempted and recorded


def test_a_member_takes_one_step_and_writes_no_view(biz):
    pg, bid = biz
    assert get(pg, bid, "/profile", sub="alice").status_code == 200
    assert views(pg, bid) == []


def test_each_request_is_one_view_and_the_rows_carry_no_personal_data(biz):
    pg, bid = biz
    support_user(pg)
    grant(pg, bid)
    for path in ("/profile", "/filing-profile", "/channels?x=asha@example.com"):
        assert get(pg, bid, path).status_code == 200
    rows = views(pg, bid)
    assert len(rows) == 3
    assert "@" not in json.dumps([r.data for r in rows])
