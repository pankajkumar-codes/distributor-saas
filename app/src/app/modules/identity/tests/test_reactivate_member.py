"""T-012: reactivate a deactivated member (inverse of T-003)."""

import uuid

import pytest

from .conftest import as_user
from .test_tenant_isolation import ALICE, BOB, CAROL, make_tenant


def add_member(client, tid, actor, user_sub, role):
    r = client.post(
        f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": user_sub, "role": role}, headers=as_user(actor)
    )
    assert r.status_code == 201, r.text


def change(client, tid, actor, user_sub, action, reason="back from leave"):
    body = {} if reason is None else {"reason": reason}
    return client.post(f"/api/v1/identity/tenants/{tid}/members/{user_sub}/{action}", json=body, headers=as_user(actor))


def deactivated(client, tid, user_sub, role="sales"):
    add_member(client, tid, ALICE, user_sub, role)
    assert change(client, tid, ALICE, user_sub, "deactivate").status_code == 200


def reactivations(client, tid):
    events = client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(ALICE)).json()
    return [e for e in events if e["action"] == "member.reactivated"]


def test_reactivated_member_regains_access_with_same_role(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, tid, BOB, role="finance")
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).status_code == 404

    r = change(client, tid, ALICE, BOB, "reactivate")
    assert r.status_code == 200
    assert r.json() == {"user_sub": BOB, "role": "finance", "status": "active", "email": None, "display_name": None}
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).json()["role"] == "finance"


def test_reactivation_is_audited_with_reason(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, tid, BOB)
    change(client, tid, ALICE, BOB, "reactivate", reason="rehired")
    [event] = reactivations(client, tid)
    assert event["actor_sub"] == ALICE
    assert event["details"] == {"user_sub": BOB, "role": "sales", "reason": "rehired"}


@pytest.mark.parametrize("reason", [None, "", "x" * 501])
def test_reason_is_required_and_bounded(client, reason):
    tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, tid, BOB)
    assert change(client, tid, ALICE, BOB, "reactivate", reason=reason).status_code == 422
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).status_code == 404


def test_retry_and_already_active_member_are_no_ops(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "sales")
    assert change(client, tid, ALICE, BOB, "reactivate").json()["status"] == "active"
    assert reactivations(client, tid) == []

    change(client, tid, ALICE, BOB, "deactivate")
    first = change(client, tid, ALICE, BOB, "reactivate")
    second = change(client, tid, ALICE, BOB, "reactivate")
    assert first.json() == second.json()
    assert len(reactivations(client, tid)) == 1


def test_deactivate_then_reactivate_round_trip_keeps_one_membership(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, tid, BOB)
    change(client, tid, ALICE, BOB, "reactivate")
    members = client.get(f"/api/v1/identity/tenants/{tid}/members", headers=as_user(ALICE)).json()
    assert [(m["user_sub"], m["status"]) for m in members] == [(ALICE, "active"), (BOB, "active")]


def test_admin_can_reactivate_non_owner_but_not_owner(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    add_member(client, tid, ALICE, CAROL, "owner")
    change(client, tid, ALICE, CAROL, "deactivate")
    assert change(client, tid, BOB, CAROL, "reactivate").status_code == 404
    assert change(client, tid, ALICE, CAROL, "reactivate").status_code == 200

    change(client, tid, ALICE, CAROL, "deactivate")
    add_member(client, tid, ALICE, "user-dave", "viewer")
    change(client, tid, ALICE, "user-dave", "deactivate")
    assert change(client, tid, BOB, "user-dave", "reactivate").status_code == 200


@pytest.mark.parametrize("role", ["sales", "inventory", "finance", "viewer"])
def test_non_admin_roles_cannot_reactivate(client, role):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, role)
    deactivated(client, tid, CAROL)
    assert change(client, tid, BOB, CAROL, "reactivate").status_code == 404


def test_deactivated_member_cannot_reactivate_self(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, tid, BOB, role="admin")
    assert change(client, tid, BOB, BOB, "reactivate").status_code == 404


def test_other_tenant_looks_like_it_does_not_exist(client):
    alice_tid = make_tenant(client, ALICE, "Alice Co")
    deactivated(client, alice_tid, CAROL)
    make_tenant(client, BOB, "Bob Co")
    real = change(client, alice_tid, BOB, CAROL, "reactivate")
    fake = change(client, str(uuid.uuid4()), BOB, CAROL, "reactivate")
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()
    assert client.get(f"/api/v1/identity/tenants/{alice_tid}", headers=as_user(CAROL)).status_code == 404


def test_cannot_reactivate_a_member_of_another_tenant_through_own_tenant(client):
    alice_tid = make_tenant(client, ALICE, "Alice Co")
    bob_tid = make_tenant(client, BOB, "Bob Co")
    add_member(client, bob_tid, BOB, CAROL, "sales")
    change(client, bob_tid, BOB, CAROL, "deactivate")
    assert change(client, alice_tid, ALICE, CAROL, "reactivate").status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{bob_tid}", headers=as_user(CAROL)).status_code == 404


def test_requires_authentication(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    r = client.post(f"/api/v1/identity/tenants/{tid}/members/{BOB}/reactivate", json={"reason": "x"})
    assert r.status_code == 401
