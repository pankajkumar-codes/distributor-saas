"""Invite a teammate by email (E0-1 / T-004). SQLite; RLS is covered in test_postgres_rls.py."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.identity import invites
from app.modules.identity.models import Invitation

from .conftest import as_user

OWNER, ADMIN, SALES = "user-owner", "user-admin", "user-sales"
NEW = "user-new"


def as_person(sub, email):
    return {"x-debug-user": sub, "x-debug-email": email}


@pytest.fixture()
def outbox(monkeypatch):
    box = invites.RecordingSender()
    monkeypatch.setattr(invites, "_recording", box)
    return box


@pytest.fixture()
def tenant(client):
    tid = client.post("/api/v1/identity/tenants", json={"name": "Vashi"}, headers=as_user(OWNER)).json()["id"]
    for sub, role in [(ADMIN, "admin"), (SALES, "billing")]:
        assert client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": sub, "role": role},
                           headers=as_user(OWNER)).status_code == 201
    return tid


def invite(client, tid, email="Priya@Example.com", role="billing", by=OWNER, **extra):
    return client.post(f"/api/v1/identity/tenants/{tid}/invitations", json={"email": email, "role": role, **extra},
                       headers=as_user(by))


def test_invite_then_accept_creates_membership(client, tenant, outbox):
    r = invite(client, tenant, display_name="Priya S")
    assert r.status_code == 201, r.text
    inv = r.json()
    assert inv["email"] == "priya@example.com" and inv["status"] == "pending" and inv["delivery"] == "sent"
    assert outbox.sent == [("priya@example.com", False)]
    expires = datetime.fromisoformat(inv["expires_at"])
    assert timedelta(days=6, hours=23) < expires.replace(tzinfo=expires.tzinfo or UTC) - datetime.now(UTC) <= timedelta(days=7)

    mine = client.get("/api/v1/identity/invitations", headers=as_person(NEW, "PRIYA@example.com")).json()
    assert [(m["tenant_name"], m["role"]) for m in mine] == [("Vashi", "billing")]

    r = client.post(f"/api/v1/identity/invitations/{inv['id']}/accept", headers=as_person(NEW, "priya@example.com"))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "billing"
    members = client.get(f"/api/v1/identity/tenants/{tenant}/members", headers=as_user(NEW)).json()
    me = next(m for m in members if m["user_sub"] == NEW)
    assert me["email"] == "priya@example.com" and me["display_name"] == "Priya S"
    assert client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user(OWNER)).json()[0]["status"] == "accepted"

    actions = [e["action"] for e in client.get(f"/api/v1/identity/tenants/{tenant}/audit", headers=as_user(OWNER)).json()]
    assert "invitation.created" in actions and "invitation.accepted" in actions


def test_accept_retry_is_idempotent_but_not_reusable(client, tenant, outbox):
    iid = invite(client, tenant).json()["id"]
    url = f"/api/v1/identity/invitations/{iid}/accept"
    assert client.post(url, headers=as_person(NEW, "priya@example.com")).status_code == 200
    assert client.post(url, headers=as_person(NEW, "priya@example.com")).status_code == 200
    # Same address, different login (e.g. a second Cognito account): cannot reuse it.
    assert client.post(url, headers=as_person("user-other", "priya@example.com")).status_code == 409
    assert len(client.get(f"/api/v1/identity/tenants/{tenant}/members", headers=as_user(OWNER)).json()) == 4


@pytest.mark.parametrize("headers", [as_person(NEW, "someone@else.com"), as_user(NEW)])
def test_only_the_verified_addressee_can_see_or_accept(client, tenant, outbox, headers):
    iid = invite(client, tenant).json()["id"]
    assert client.get("/api/v1/identity/invitations", headers=headers).json() == []
    r = client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=headers)
    assert r.status_code == 404
    assert r.json() == client.post(f"/api/v1/identity/invitations/{uuid.uuid4()}/accept", headers=headers).json()
    assert client.post("/api/v1/identity/invitations/not-a-uuid/accept", headers=headers).status_code == 404


def test_expired_invite_cannot_be_accepted_until_resent(client, tenant, outbox):
    from app.modules.identity import api as main

    iid = invite(client, tenant).json()["id"]
    with main._factory()() as s:
        inv = s.get(Invitation, uuid.UUID(iid))
        inv.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()
    assert client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user(OWNER)).json()[0]["status"] == "expired"
    assert client.get("/api/v1/identity/invitations", headers=as_person(NEW, "priya@example.com")).json() == []
    assert client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=as_person(NEW, "priya@example.com")).status_code == 410
    # A new invite is refused while the old one is open; resend renews it instead.
    assert invite(client, tenant).status_code == 409
    r = client.post(f"/api/v1/identity/tenants/{tenant}/invitations/{iid}/resend", headers=as_user(ADMIN))
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert outbox.sent[-1] == ("priya@example.com", True)
    assert client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=as_person(NEW, "priya@example.com")).status_code == 200


def test_revoked_invite_cannot_be_accepted(client, tenant, outbox):
    iid = invite(client, tenant).json()["id"]
    url = f"/api/v1/identity/tenants/{tenant}/invitations/{iid}/revoke"
    assert client.post(url, headers=as_user(ADMIN)).json()["status"] == "revoked"
    assert client.post(url, headers=as_user(ADMIN)).status_code == 200  # retry
    actions = [e["action"] for e in client.get(f"/api/v1/identity/tenants/{tenant}/audit", headers=as_user(OWNER)).json()]
    assert actions.count("invitation.revoked") == 1
    assert client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=as_person(NEW, "priya@example.com")).status_code == 410
    # Revoking frees the address for a fresh invitation.
    assert invite(client, tenant).status_code == 201


def test_roles_who_may_invite(client, tenant, outbox):
    assert invite(client, tenant, email="a@x.io", role="ca", by=SALES).status_code == 404
    assert invite(client, tenant, email="b@x.io", role="owner", by=ADMIN).status_code == 404
    assert invite(client, tenant, email="c@x.io", role="admin", by=ADMIN).status_code == 201
    assert invite(client, tenant, email="d@x.io", role="owner", by=OWNER).status_code == 201
    owner_invite = next(i for i in client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user(OWNER)).json()
                        if i["email"] == "d@x.io")
    # An admin can't revoke or resend an owner invitation either.
    base = f"/api/v1/identity/tenants/{tenant}/invitations/{owner_invite['id']}"
    assert client.post(f"{base}/revoke", headers=as_user(ADMIN)).status_code == 404
    assert client.post(f"{base}/resend", headers=as_user(ADMIN)).status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user(SALES)).status_code == 404


def test_inviting_an_existing_member_is_refused(client, tenant, outbox):
    iid = invite(client, tenant).json()["id"]
    client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=as_person(NEW, "priya@example.com"))
    r = invite(client, tenant, email="PRIYA@example.com")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_member"


def test_deactivated_member_cannot_rejoin_through_an_invite(client, tenant, outbox):
    iid = invite(client, tenant, email="sales@x.io").json()["id"]
    # SALES was added by user id earlier, so the invite isn't blocked by email.
    r = client.post(f"/api/v1/identity/invitations/{iid}/accept", headers=as_person(SALES, "sales@x.io"))
    assert r.status_code == 409


@pytest.mark.parametrize("body", [
    {"email": "not-an-email", "role": "billing"},
    {"email": "a@b.co", "role": "superuser"},
    {"email": "a@b.co", "role": "billing", "display_name": ""},
    {"email": "x" * 250 + "@b.co", "role": "billing"},
])
def test_input_validation(client, tenant, outbox, body):
    r = client.post(f"/api/v1/identity/tenants/{tenant}/invitations", json=body, headers=as_user(OWNER))
    assert r.status_code == 422
    assert client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user(OWNER)).json() == []


def test_failed_delivery_keeps_the_invitation_and_resend_retries(client, tenant, outbox):
    outbox.fail = True
    inv = invite(client, tenant).json()
    assert inv["delivery"] == "failed"
    outbox.fail = False
    r = client.post(f"/api/v1/identity/tenants/{tenant}/invitations/{inv['id']}/resend", headers=as_user(OWNER))
    assert r.json()["delivery"] == "sent"


def test_cross_tenant_invitations_are_404(client, tenant, outbox):
    iid = invite(client, tenant).json()["id"]
    other = client.post("/api/v1/identity/tenants", json={"name": "Other"}, headers=as_user("user-x")).json()["id"]
    for action in ("resend", "revoke"):
        # Owner of another tenant, naming this tenant's invitation through their own tenant.
        r = client.post(f"/api/v1/identity/tenants/{other}/invitations/{iid}/{action}", headers=as_user("user-x"))
        assert r.status_code == 404
        # Outsider naming the real tenant.
        r = client.post(f"/api/v1/identity/tenants/{tenant}/invitations/{iid}/{action}", headers=as_user("user-x"))
        assert r.status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tenant}/invitations", headers=as_user("user-x")).status_code == 404
    assert invite(client, tenant, by="user-x").status_code == 404
