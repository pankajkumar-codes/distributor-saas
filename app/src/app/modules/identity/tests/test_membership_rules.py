"""Role, membership-status and input rules not covered by test_tenant_isolation.py."""

import pytest

from .conftest import as_user
from .test_tenant_isolation import ALICE, BOB, CAROL, make_tenant


def add_member(client, tid, actor, user_sub, role):
    return client.post(
        f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": user_sub, "role": role}, headers=as_user(actor)
    )


def disable(client, tid, user_sub):
    r = client.post(
        f"/api/v1/identity/tenants/{tid}/members/{user_sub}/deactivate", json={"reason": "left"}, headers=as_user(ALICE)
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("role", ["billing", "ca"])
def test_non_admin_roles_cannot_manage_members_or_read_audit(client, role):
    tid = make_tenant(client, ALICE, "Alice Co")
    assert add_member(client, tid, ALICE, BOB, role).status_code == 201
    assert add_member(client, tid, BOB, CAROL, "ca").status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(BOB)).status_code == 404


@pytest.mark.parametrize("role", ["billing", "ca"])
def test_non_admin_roles_can_still_read_tenant_and_members(client, role):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, role)
    r = client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB))
    assert r.status_code == 200
    assert r.json()["role"] == role
    assert client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(BOB)).status_code == 200


def test_admin_can_add_non_owner_members_and_read_audit(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    assert add_member(client, tid, BOB, CAROL, "billing").status_code == 201
    assert client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(BOB)).status_code == 200


def test_owner_can_add_another_owner(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    r = add_member(client, tid, ALICE, BOB, "owner")
    assert r.status_code == 201
    assert r.json() == {"user_sub": BOB, "role": "owner", "status": "active", "email": None, "display_name": None}


def test_disabled_member_is_treated_as_a_non_member(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    disable(client, tid, BOB)

    assert client.get("/api/v1/identity/tenants", headers=as_user(BOB)).json() == []
    for path in ("", "/members", "/audit"):
        assert client.get(f"/api/v1/identity/tenants/{tid}{path}", headers=as_user(BOB)).status_code == 404
    assert add_member(client, tid, BOB, CAROL, "ca").status_code == 404


def test_disabled_member_still_appears_in_member_list_with_status(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    disable(client, tid, BOB)
    members = client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(ALICE)).json()
    assert {m["user_sub"]: m["status"] for m in members} == {ALICE: "active", BOB: "deactivated"}


def test_disabled_member_cannot_be_re_added(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    disable(client, tid, BOB)
    assert add_member(client, tid, ALICE, BOB, "billing").status_code == 409


def test_audit_log_only_contains_this_tenants_events(client):
    alice_tid = make_tenant(client, ALICE, "Alice Co")
    bob_tid = make_tenant(client, BOB, "Bob Co")
    add_member(client, bob_tid, BOB, CAROL, "ca")
    events = client.get(f"/api/v1/identity/tenants/{alice_tid}/audit", headers=as_user(ALICE)).json()
    assert [(e["action"], e["actor_sub"], e["entity_id"]) for e in events] == [
        ("tenant.created", ALICE, alice_tid)
    ]


def test_audit_records_who_added_whom(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    add_member(client, tid, BOB, CAROL, "billing")
    added = [
        e["actor_sub"]
        for e in client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(ALICE)).json()
        if e["action"] == "member.added"
    ]
    assert sorted(added) == [ALICE, BOB]


@pytest.mark.parametrize("name", ["", "x" * 201])
def test_tenant_name_must_be_1_to_200_characters(client, name):
    r = client.post("/api/v1/identity/tenants", json={"name": name}, headers=as_user(ALICE))
    assert r.status_code == 422
    assert client.get("/api/v1/identity/tenants", headers=as_user(ALICE)).json() == []


def test_tenant_name_of_200_characters_is_accepted(client):
    assert client.post("/api/v1/identity/tenants", json={"name": "x" * 200}, headers=as_user(ALICE)).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"user_sub": BOB, "role": "superuser"},
        {"user_sub": "", "role": "ca"},
        {"user_sub": "x" * 129, "role": "ca"},
        {"user_sub": BOB},
        {"role": "ca"},
    ],
)
def test_invalid_member_body_is_rejected_without_side_effects(client, body):
    tid = make_tenant(client, ALICE, "Alice Co")
    r = client.post(f"/api/v1/identity/tenants/{tid}/members", json=body, headers=as_user(ALICE))
    assert r.status_code == 422
    members = client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(ALICE)).json()
    assert [m["user_sub"] for m in members] == [ALICE]


def test_unauthenticated_requests_to_tenant_routes_are_401(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    assert client.post("/api/v1/identity/tenants", json={"name": "x"}).status_code == 401
    for path in ("", "/members", "/audit"):
        assert client.get(f"/api/v1/identity/tenants/{tid}{path}").status_code == 401
    assert client.post(f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": BOB, "role": "ca"}).status_code == 401
