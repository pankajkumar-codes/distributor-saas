"""Runs the real migrations on PostgreSQL and checks row-level security.

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")
MIGRATIONS = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))


@pytest.fixture()
def pg_client(monkeypatch):
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    admin_url = make_url(ADMIN_URL)
    owner = create_engine(admin_url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        for m in MIGRATIONS:
            c.exec_driver_sql(m.read_text())
        c.execute(text("alter role svc_identity password 'test-only'"))
    svc = create_engine(admin_url.set(username="svc_identity", password="test-only", database=dbname))

    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "engine", lambda: svc)
    monkeypatch.setattr("platform_common.db.engine", lambda: svc)
    main._factory.cache_clear()
    yield TestClient(main.app), svc
    main._factory.cache_clear()
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def test_api_flow_on_postgres(pg_client):
    client, _ = pg_client
    r = client.post("/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert client.get(f"/identity/tenants/{tid}", headers={"x-debug-user": "alice"}).status_code == 200
    assert client.get(f"/identity/tenants/{tid}", headers={"x-debug-user": "bob"}).status_code == 404
    r = client.post(f"/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "viewer"}, headers={"x-debug-user": "alice"})
    assert r.status_code == 201
    assert len(client.get(f"/identity/tenants/{tid}/members", headers={"x-debug-user": "bob"}).json()) == 2


def test_rls_hides_other_tenants_even_without_a_filter(pg_client):
    client, svc = pg_client
    client.post("/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    client.post("/identity/tenants", json={"name": "Bob Co"}, headers={"x-debug-user": "bob"})
    with svc.begin() as c:
        c.execute(text("select set_config('app.user_sub', 'bob', true)"))
        tenants = c.execute(text("select name from identity.tenants")).scalars().all()
        audit = c.execute(text("select count(*) from identity.audit_events")).scalar()
        members = c.execute(text("select user_sub from identity.memberships")).scalars().all()
    assert tenants == ["Bob Co"]
    assert audit == 1
    assert members == ["bob"]
    with svc.begin() as c:
        assert c.execute(text("select count(*) from identity.tenants")).scalar() == 0


def test_service_cannot_rewrite_audit(pg_client):
    client, svc = pg_client
    client.post("/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"})
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            c.execute(text("select set_config('app.user_sub', 'alice', true)"))
            c.execute(text("delete from identity.audit_events"))


def test_invitation_flow_under_rls(pg_client):
    client, _ = pg_client
    owner = {"x-debug-user": "alice"}
    tid = client.post("/identity/tenants", json={"name": "Alice Co"}, headers=owner).json()["id"]
    r = client.post(f"/identity/tenants/{tid}/invitations", json={"email": "Priya@Example.com", "role": "sales"},
                    headers=owner)
    assert r.status_code == 201, r.text
    iid = r.json()["id"]

    invitee = {"x-debug-user": "priya", "x-debug-email": "priya@example.com"}
    stranger = {"x-debug-user": "eve", "x-debug-email": "eve@example.com"}
    # The invitee is not a member yet but can see the invitation and the tenant's name.
    assert [i["tenant_name"] for i in client.get("/identity/invitations", headers=invitee).json()] == ["Alice Co"]
    assert client.get("/identity/invitations", headers=stranger).json() == []
    assert client.get(f"/identity/tenants/{tid}", headers=invitee).status_code == 404
    assert client.post(f"/identity/invitations/{iid}/accept", headers=stranger).status_code == 404

    r = client.post(f"/identity/invitations/{iid}/accept", headers=invitee)
    assert r.status_code == 200, r.text
    assert client.get(f"/identity/tenants/{tid}", headers=invitee).json()["role"] == "sales"
    # Once accepted, the invitation no longer exposes the tenant to anyone else holding that email.
    assert client.get("/identity/invitations", headers=invitee).json() == []


def test_invitations_hidden_from_other_tenants_at_db_level(pg_client):
    client, svc = pg_client
    tid = client.post("/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"}).json()["id"]
    client.post(f"/identity/tenants/{tid}/invitations", json={"email": "p@example.com", "role": "viewer"},
                headers={"x-debug-user": "alice"})
    with svc.connect() as c:
        c.execute(text("select set_config('app.user_sub', 'mallory', false)"))
        assert c.execute(text("select count(*) from identity.invitations")).scalar() == 0
        with pytest.raises(Exception, match="row-level security"):
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
    tid = client.post("/identity/tenants", json={"name": "Alice Co"}, headers=alice).json()["id"]
    client.post(f"/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "admin"}, headers=alice)

    last_owner = client.post(f"/identity/tenants/{tid}/members/alice/deactivate", json={"reason": "x"}, headers=alice)
    assert last_owner.status_code == 409
    r = client.post(f"/identity/tenants/{tid}/members/bob/deactivate", json={"reason": "left"}, headers=alice)
    assert r.status_code == 200, r.text
    assert client.get(f"/identity/tenants/{tid}", headers=bob).status_code == 404
    with svc.begin() as c:
        c.execute(text("select set_config('app.user_sub', 'bob', true)"))
        assert c.execute(text("select count(*) from identity.tenants")).scalar() == 0


def test_reactivate_on_postgres(pg_client):
    client, _ = pg_client
    alice, bob = {"x-debug-user": "alice"}, {"x-debug-user": "bob"}
    tid = client.post("/identity/tenants", json={"name": "Alice Co"}, headers=alice).json()["id"]
    client.post(f"/identity/tenants/{tid}/members", json={"user_sub": "bob", "role": "sales"}, headers=alice)
    client.post(f"/identity/tenants/{tid}/members/bob/deactivate", json={"reason": "leave"}, headers=alice)
    assert client.get(f"/identity/tenants/{tid}", headers=bob).status_code == 404
    r = client.post(f"/identity/tenants/{tid}/members/bob/reactivate", json={"reason": "back"}, headers=alice)
    assert r.status_code == 200, r.text
    assert client.get(f"/identity/tenants/{tid}", headers=bob).status_code == 200
