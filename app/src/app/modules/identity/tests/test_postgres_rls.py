"""Runs the real migrations on PostgreSQL and checks row-level security (LLD-1 §3.4).

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL

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
    r = client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "ca"}, headers={"x-debug-user": "alice"})
    assert r.status_code == 201
    assert len(client.get(f"/api/v1/identity/tenants/{tid}/members", headers={"x-debug-user": "bob"}).json()) == 2


def test_list_shows_every_business_of_the_caller_and_no_other(pg_client):
    client, _ = pg_client
    alice, bob = {"x-debug-user": "alice"}, {"x-debug-user": "bob"}
    a1 = client.post("/api/v1/identity/tenants", json={"name": "Alice One"}, headers=alice).json()["id"]
    client.post("/api/v1/identity/tenants", json={"name": "Alice Two"}, headers=alice)
    client.post("/api/v1/identity/tenants", json={"name": "Bob Co"}, headers=bob)
    client.post(f"/api/v1/identity/tenants/{a1}/members", json={"user_sub": "bob", "role": "billing"}, headers=alice)
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
        assert c.execute(text("select count(*) from identity.audit_events")).scalar() == 1
        assert c.execute(text("select user_sub from identity.memberships")).scalars().all() == ["bob"]
    with svc.begin() as c:
        # No business bound: nothing, never everything.
        as_user(c, "bob")
        assert c.execute(text("select count(*) from identity.businesses")).scalar() == 0
        assert c.execute(text("select count(*) from identity.audit_events")).scalar() == 0
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


def test_invitation_flow_under_rls(pg_client):
    client, _ = pg_client
    owner = {"x-debug-user": "alice"}
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers=owner).json()["id"]
    r = client.post(f"/api/v1/identity/tenants/{tid}/invitations", json={"email": "Priya@Example.com", "role": "billing"},
                    headers=owner)
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    invitee = {"x-debug-user": "priya", "x-debug-email": "priya@example.com"}
    stranger = {"x-debug-user": "eve", "x-debug-email": "eve@example.com"}
    # The invitee is not a member yet but can see the invitation and the business's name.
    assert [i["tenant_name"] for i in client.get("/api/v1/identity/invitations", headers=invitee).json()] == ["Alice Co"]
    assert client.get("/api/v1/identity/invitations", headers=stranger).json() == []
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=invitee).status_code == 404
    assert client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=stranger).status_code == 404

    r = client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=invitee)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=invitee).json()["role"] == "billing"
    # Once accepted, the invitation no longer exposes the business to anyone else holding that email.
    assert client.get("/api/v1/identity/invitations", headers=invitee).json() == []
    # A retry of the accept gives the same answer.
    assert client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=invitee).status_code == 200


def test_invitations_hidden_from_other_businesses_at_db_level(pg_client):
    client, svc = pg_client
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"}).json()["id"]
    client.post(f"/api/v1/identity/tenants/{tid}/invitations", json={"email": "p@example.com", "role": "ca"},
                headers={"x-debug-user": "alice"})
    with svc.begin() as c:
        as_user(c, "mallory")
        assert c.execute(text("select count(*) from identity.invitations")).scalar() == 0
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "mallory", tid)
            c.execute(
                text(
                    "insert into identity.invitations (id, tenant_id, email, role, invited_by, expires_at) "
                    "values (:id, :t, 'm@example.com', 'owner', 'mallory', now() + interval '7 days')"
                ),
                {"id": str(uuid.uuid4()), "t": tid},
            )


def test_deactivate_on_postgres(pg_client):
    client, svc = pg_client
    alice, bob = {"x-debug-user": "alice"}, {"x-debug-user": "bob"}
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers=alice).json()["id"]
    client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "admin"}, headers=alice)

    last_owner = client.post(f"/api/v1/identity/tenants/{tid}/members/alice/deactivate", json={"reason": "x"}, headers=alice)
    assert last_owner.status_code == 409
    r = client.post(f"/api/v1/identity/tenants/{tid}/members/bob/deactivate", json={"reason": "left"}, headers=alice)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "deactivated"
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=bob).status_code == 404
    with svc.begin() as c:
        as_user(c, "alice", tid)
        row = c.execute(
            text(
                "select m.deactivation_reason, m.deactivated_by = u.id from identity.memberships m, identity.users u "
                "where m.user_sub = 'bob' and u.cognito_sub = 'alice'"
            )
        ).one()
    assert tuple(row) == ("left", True)


def test_reactivate_on_postgres(pg_client):
    client, _ = pg_client
    alice, bob = {"x-debug-user": "alice"}, {"x-debug-user": "bob"}
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers=alice).json()["id"]
    client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "billing"}, headers=alice)
    client.post(f"/api/v1/identity/tenants/{tid}/members/bob/deactivate", json={"reason": "leave"}, headers=alice)
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=bob).status_code == 404
    r = client.post(f"/api/v1/identity/tenants/{tid}/members/bob/reactivate", json={"reason": "back"}, headers=alice)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=bob).status_code == 200
