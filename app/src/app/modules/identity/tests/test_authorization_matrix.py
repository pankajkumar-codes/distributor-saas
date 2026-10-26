"""Role x endpoint authorization matrix and active-tenant scoping.

Complements test_tenant_isolation.py. Every row here is a server-side check: a UI
hiding a button is not authorization.
"""

import uuid

import pytest
from sqlalchemy import update

from app.modules.identity import api as main
from app.modules.identity.models import Membership, MembershipStatus

from .conftest import as_user

OWNER, OTHER = "user-owner", "user-outsider"
ROLES = ["owner", "admin", "billing", "ca"]
CAN_MANAGE = {"owner", "admin"}


def make_tenant(client, user, name="Tenant"):
    r = client.post("/api/v1/identity/tenants", json={"name": name}, headers=as_user(user))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def add(client, tid, by, sub, role):
    return client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": sub, "role": role}, headers=as_user(by))


def tenant_with(client, role):
    """A tenant owned by OWNER with a member 'user-<role>' holding that role."""
    tid = make_tenant(client, OWNER)
    sub = f"user-{role}"
    if role != "owner":
        assert add(client, tid, OWNER, sub, role).status_code == 201
    else:
        sub = OWNER
    return tid, sub


@pytest.mark.parametrize("role", ROLES)
def test_every_active_role_can_read_tenant_and_members(client, role):
    tid, sub = tenant_with(client, role)
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(sub)).json()["role"] == role
    assert client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(sub)).status_code == 200


@pytest.mark.parametrize("role", ROLES)
def test_audit_log_needs_owner_or_admin(client, role):
    tid, sub = tenant_with(client, role)
    expected = 200 if role in CAN_MANAGE else 404
    assert client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(sub)).status_code == expected


@pytest.mark.parametrize("caller", ROLES)
@pytest.mark.parametrize("new_role", ROLES)
def test_who_can_grant_which_role(client, caller, new_role):
    tid, sub = tenant_with(client, caller)
    r = add(client, tid, sub, "user-new", new_role)
    if caller == "owner":
        expected = 201
    elif caller == "admin":
        expected = 404 if new_role == "owner" else 201
    else:
        expected = 404
    assert r.status_code == expected, r.text


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_refused_grant_leaves_no_member_and_no_audit(client, role):
    tid, sub = tenant_with(client, "ca")
    before = client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(OWNER)).json()
    assert add(client, tid, sub, "user-sneaky", role).status_code == 404
    members = [m["user_sub"] for m in client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(OWNER)).json()]
    assert "user-sneaky" not in members
    assert client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(OWNER)).json() == before


def _disable(sub, tid):
    with main._factory()() as s:
        s.execute(
            update(Membership)
            .where(Membership.user_sub == sub, Membership.business_id == uuid.UUID(tid))
            .values(status=MembershipStatus.deactivated)
        )
        s.commit()


@pytest.mark.parametrize("path", ["", "/members", "/audit"])
def test_disabled_member_loses_access_like_an_outsider(client, path):
    tid, sub = tenant_with(client, "admin")
    _disable(sub, tid)
    disabled = client.get(f"/api/v1/identity/tenants/{tid}{path}", headers=as_user(sub))
    outsider = client.get(f"/api/v1/identity/tenants/{tid}{path}", headers=as_user(OTHER))
    assert disabled.status_code == outsider.status_code == 404
    assert disabled.json() == outsider.json()


def test_disabled_member_cannot_add_members_or_list_the_tenant(client):
    tid, sub = tenant_with(client, "admin")
    _disable(sub, tid)
    assert add(client, tid, sub, "user-new", "ca").status_code == 404
    assert client.get("/api/v1/identity/tenants", headers=as_user(sub)).json() == []


def test_disabled_member_cannot_be_readded_silently(client):
    tid, sub = tenant_with(client, "ca")
    _disable(sub, tid)
    # Re-activation must be an explicit, audited operation, not a side effect of "add".
    assert add(client, tid, OWNER, sub, "admin").status_code == 409


def test_role_in_one_tenant_does_not_carry_to_another(client):
    """Owner of T1 who is only a viewer in T2 gets viewer rights in T2."""
    t1 = make_tenant(client, "user-dual", "T1")
    t2 = make_tenant(client, OWNER, "T2")
    assert add(client, t2, OWNER, "user-dual", "ca").status_code == 201
    assert add(client, t2, "user-dual", "user-new", "billing").status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{t2}/audit", headers=as_user("user-dual")).status_code == 404
    assert add(client, t1, "user-dual", "user-new", "billing").status_code == 201


def test_member_list_and_audit_are_scoped_to_the_requested_tenant(client):
    t1 = make_tenant(client, OWNER, "T1")
    t2 = make_tenant(client, OWNER, "T2")
    add(client, t1, OWNER, "only-in-t1", "billing")
    add(client, t2, OWNER, "only-in-t2", "billing")
    m1 = {m["user_sub"] for m in client.get(f"/api/v1/identity/tenants/{t1}/members", headers=as_user(OWNER)).json()}
    assert m1 == {OWNER, "only-in-t1"}
    a1 = client.get(f"/api/v1/identity/tenants/{t1}/audit", headers=as_user(OWNER)).json()
    assert {e["entity_type"] for e in a1} == {"tenant", "membership"}
    assert len(a1) == 2  # tenant.created + one member.added, nothing from T2


def test_outsider_cannot_add_themselves_by_guessing_the_id(client):
    tid = make_tenant(client, OWNER)
    assert add(client, tid, OTHER, OTHER, "owner").status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(OTHER)).status_code == 404


@pytest.mark.parametrize("bad", ["%20", "..", "0", str(uuid.uuid4()).upper(), "00000000-0000-0000-0000-000000000000"])
def test_odd_tenant_ids_never_leak(client, bad):
    make_tenant(client, OWNER)
    assert client.get(f"/api/v1/identity/tenants/{bad}", headers=as_user(OWNER)).status_code == 404


def test_unauthenticated_calls_are_401_on_every_route(client):
    tid = make_tenant(client, OWNER)
    for method, path in [
        ("post", "/api/v1/identity/tenants"),
        ("get", "/api/v1/identity/tenants"),
        ("get", f"/api/v1/identity/tenants/{tid}"),
        ("get", f"/api/v1/identity/tenants/{tid}/members"),
        ("post", f"/api/v1/identity/tenants/{tid}/members"),
        ("get", f"/api/v1/identity/tenants/{tid}/audit"),
    ]:
        assert getattr(client, method)(path).status_code == 401, (method, path)


@pytest.mark.parametrize(
    "body",
    [{"name": ""}, {"name": "x" * 201}, {}, {"name": None}],
)
def test_tenant_name_is_validated(client, body):
    assert client.post("/api/v1/identity/tenants", json=body, headers=as_user(OWNER)).status_code == 422


@pytest.mark.parametrize(
    "body",
    [{"user_sub": "", "role": "ca"}, {"user_sub": "x" * 129, "role": "ca"}, {"user_sub": "a", "role": "superuser"}],
)
def test_member_body_is_validated(client, body):
    tid = make_tenant(client, OWNER)
    assert client.post(f"/api/v1/identity/tenants/{tid}/members", json=body, headers=as_user(OWNER)).status_code == 422
