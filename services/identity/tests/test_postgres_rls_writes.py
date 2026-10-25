"""Row-level security on the write paths, as svc_identity, bypassing the API.

The API checks membership before every write; these tests ask whether the database
would still stop a write if an API check were forgotten or bypassed (defense in
depth, docs/SECURITY.md). xfail(strict=True) marks known gaps logged in the QA plan:
when a migration closes one, its test starts passing and pytest fails until the
marker is removed, so the fix cannot land untested.

Skipped unless PG_ADMIN_URL is set (see conftest.py).
"""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def as_sub(conn, sub):
    conn.execute(text("select set_config('app.user_sub', :s, true)"), {"s": sub})


def setup_alice(client, extra=()):
    tid = client.post("/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"}).json()["id"]
    for sub, role in extra:
        r = client.post(f"/identity/tenants/{tid}/members", json={"user_sub": sub, "role": role}, headers={"x-debug-user": "alice"})
        assert r.status_code == 201
    return tid


def memberships(svc, tid):
    with svc.begin() as c:
        as_sub(c, "alice")
        return {
            (u, r, s)
            for u, r, s in c.execute(
                text("select user_sub, role, status from identity.memberships where tenant_id = :t"), {"t": tid}
            )
        }


def test_service_cannot_delete_memberships_or_tenants(pg_client):
    client, svc = pg_client
    setup_alice(client)
    for table in ("memberships", "tenants"):
        with pytest.raises(Exception, match="permission denied"):
            with svc.begin() as c:
                as_sub(c, "alice")
                c.execute(text(f"delete from identity.{table}"))


def test_service_cannot_update_audit(pg_client):
    client, svc = pg_client
    setup_alice(client)
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            as_sub(c, "alice")
            c.execute(text("update identity.audit_events set action = 'x'"))


def test_outsider_update_of_another_tenant_touches_nothing(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    with svc.begin() as c:
        as_sub(c, "bob")
        assert c.execute(text("update identity.tenants set name = 'pwned'")).rowcount == 0
        assert c.execute(text("update identity.memberships set role = 'viewer'")).rowcount == 0
    with svc.begin() as c:
        as_sub(c, "alice")
        assert c.execute(text("select name from identity.tenants where id = :t"), {"t": tid}).scalar() == "Alice Co"


def test_disabled_member_sees_no_tenant_rows(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("dave", "viewer")])
    with svc.begin() as c:
        as_sub(c, "alice")
        c.execute(text("update identity.memberships set status = 'disabled' where user_sub = 'dave'"))
    with svc.begin() as c:
        as_sub(c, "dave")
        assert c.execute(text("select count(*) from identity.tenants")).scalar() == 0
        assert c.execute(text("select count(*) from identity.audit_events")).scalar() == 0
        # Dave still sees his own membership row by design (policy member_rows).
        assert c.execute(text("select user_sub from identity.memberships")).scalars().all() == ["dave"]
    assert client.get(f"/identity/tenants/{tid}", headers={"x-debug-user": "dave"}).status_code == 404


@pytest.mark.xfail(strict=True, reason="QA-DEF-001: memberships insert policy is WITH CHECK (true)")
def test_outsider_cannot_insert_a_membership_into_another_tenant(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_sub(c, "bob")
            c.execute(
                text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, 'bob', 'owner')"),
                {"i": uuid.uuid4(), "t": tid},
            )


@pytest.mark.xfail(strict=True, reason="QA-DEF-002: audit_events insert policy is WITH CHECK (true)")
def test_outsider_cannot_forge_audit_in_another_tenant(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_sub(c, "bob")
            c.execute(
                text(
                    "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id) "
                    "values (:i, :t, 'alice', 'tenant.deleted', 'tenant', :e)"
                ),
                {"i": uuid.uuid4(), "t": tid, "e": tid},
            )


@pytest.mark.xfail(strict=True, reason="QA-DEF-003: member_rows lets a user update their own membership row")
def test_member_cannot_promote_or_reenable_themselves(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("dave", "viewer")])
    with svc.begin() as c:
        as_sub(c, "alice")
        c.execute(text("update identity.memberships set status = 'disabled' where user_sub = 'dave'"))
    try:
        with svc.begin() as c:
            as_sub(c, "dave")
            c.execute(text("update identity.memberships set role = 'owner', status = 'active' where user_sub = 'dave'"))
    except Exception:
        pass  # being refused outright is also a pass
    assert ("dave", "viewer", "disabled") in memberships(svc, tid)
