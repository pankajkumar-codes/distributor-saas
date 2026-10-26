"""Runs the real migrations on PostgreSQL and checks row-level security (LLD-1 §3.4).

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""


import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, seed_member

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def as_user(conn, sub, tenant=None, email=""):
    """What the API sets for a request: the caller, and the business it is bound to."""
    conn.execute(
        text(
            "select set_config('app.user_id', identity.dev_ensure_user(:s)::text, true), "
            "set_config('app.user_sub', :s, true), set_config('app.user_email', :e, true), "
            "set_config('app.tenant_id', :t, true)"
        ),
        {"s": sub, "e": email, "t": str(tenant or "")},
    )


def test_api_flow_on_postgres(pg_client):
    client, _ = pg_client
    r = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers={"x-debug-user": "alice"}).status_code == 200
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers={"x-debug-user": "bob"}).status_code == 404
    seed_member(tid, "bob", "ca")
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers={"x-debug-user": "bob"}).json()["role"] == "ca"
    assert len(client.get(f"/api/v1/b/{tid}/members", headers={"x-debug-user": "alice"}).json()["members"]) == 2


def test_list_shows_every_business_of_the_caller_and_no_other(pg_client):
    client, _ = pg_client
    alice, bob = {"x-debug-user": "alice"}, {"x-debug-user": "bob"}
    a1 = client.post("/api/v1/identity/tenants", json={"name": "Alice One"}, headers=alice).json()["id"]
    client.post("/api/v1/identity/tenants", json={"name": "Alice Two"}, headers=alice)
    client.post("/api/v1/identity/tenants", json={"name": "Bob Co"}, headers=bob)
    seed_member(a1, "bob", "billing")
    assert [t["name"] for t in client.get("/api/v1/identity/tenants", headers=alice).json()] == ["Alice One", "Alice Two"]
    assert {(t["name"], t["role"]) for t in client.get("/api/v1/identity/tenants", headers=bob).json()} == {
        ("Alice One", "billing"),
        ("Bob Co", "owner"),
    }


def test_rls_shows_only_the_bound_business_even_without_a_filter(pg_client):
    client, svc = pg_client
    client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    bob_tid = client.post("/api/v1/identity/tenants", json={"name": "Bob Co"}, headers={"x-debug-user": "bob"}).json()["id"]
    with svc.begin() as c:
        as_user(c, "bob", bob_tid)
        assert c.execute(text("select name from identity.businesses")).scalars().all() == ["Bob Co"]
        assert c.execute(text("select action from platform.audit_log")).scalars().all() == ["business.create"]
        assert c.execute(text("select user_sub from identity.memberships")).scalars().all() == ["bob"]
    with svc.begin() as c:
        # No business bound: nothing, never everything.
        as_user(c, "bob")
        assert c.execute(text("select count(*) from identity.businesses")).scalar() == 0
        assert c.execute(text("select count(*) from platform.v_audit_log")).scalar() == 0
    with svc.begin() as c:
        assert c.execute(text("select count(*) from identity.businesses")).scalar() == 0
        assert c.execute(text("select count(*) from identity.users")).scalar() == 0


def test_users_see_only_their_own_row_and_auth_tables_are_closed(pg_client):
    client, svc = pg_client
    client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    with svc.begin() as c:
        as_user(c, "bob")
        assert c.execute(text("select cognito_sub from identity.users")).scalars().all() == ["bob"]
    for table in ("sessions", "pending_signups", "verification_codes"):
        with pytest.raises(Exception, match="permission denied"):
            with svc.begin() as c:
                as_user(c, "alice")
                c.execute(text(f"select count(*) from identity.{table}"))


def test_service_cannot_rewrite_audit(pg_client):
    client, svc = pg_client
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"}).json()["id"]
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            as_user(c, "alice", tid)
            c.execute(text("delete from identity.audit_events"))
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            as_user(c, "alice", tid)
            c.execute(text("delete from platform.audit_log"))
