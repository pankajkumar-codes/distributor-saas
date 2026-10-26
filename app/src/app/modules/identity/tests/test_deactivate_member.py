"""T-003 / backlog E0-2: deactivate a member."""

import uuid

import pytest

from .conftest import as_user
from .test_tenant_isolation import ALICE, BOB, CAROL, make_tenant


def add_member(client, tid, actor, user_sub, role):
    r = client.post(
        f"/api/v1/identity/tenants/{tid}/members", json={"user_sub": user_sub, "role": role}, headers=as_user(actor)
    )
    assert r.status_code == 201, r.text


def deactivate(client, tid, actor, user_sub, reason="left the company"):
    body = {} if reason is None else {"reason": reason}
    return client.post(f"/api/v1/identity/tenants/{tid}/members/{user_sub}/deactivate", json=body, headers=as_user(actor))


def audit_events(client, tid, action="member.deactivated"):
    events = client.get(f"/api/v1/identity/tenants/{tid}/audit", headers=as_user(ALICE)).json()
    return [e for e in events if e["action"] == action]


def test_owner_deactivates_member_who_then_loses_access(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).status_code == 200

    r = deactivate(client, tid, ALICE, BOB)
    assert r.status_code == 200
    assert r.json() == {"user_sub": BOB, "role": "billing", "status": "deactivated", "email": None, "display_name": None}
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).status_code == 404


def test_deactivation_is_audited_with_who_whom_and_why(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    deactivate(client, tid, ALICE, BOB, reason="contract ended")
    [event] = audit_events(client, tid)
    assert event["actor_sub"] == ALICE
    assert event["entity_type"] == "membership"
    assert event["details"] == {"user_sub": BOB, "role": "billing", "reason": "contract ended"}


@pytest.mark.parametrize("reason", [None, "", "x" * 501])
def test_reason_is_required_and_bounded(client, reason):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    assert deactivate(client, tid, ALICE, BOB, reason=reason).status_code == 422
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(BOB)).status_code == 200


def test_retry_returns_same_result_without_a_second_audit_event(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "billing")
    first = deactivate(client, tid, ALICE, BOB)
    second = deactivate(client, tid, ALICE, BOB)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(audit_events(client, tid)) == 1


def test_last_active_owner_cannot_be_deactivated(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    r = deactivate(client, tid, ALICE, ALICE)
    assert r.status_code == 409
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(ALICE)).status_code == 200
    assert audit_events(client, tid) == []


def test_owner_can_be_deactivated_while_another_owner_remains(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "owner")
    assert deactivate(client, tid, BOB, ALICE).status_code == 200
    # Bob is now the only active owner.
    assert deactivate(client, tid, BOB, BOB).status_code == 409


def test_owner_may_deactivate_self_when_not_last(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "owner")
    assert deactivate(client, tid, ALICE, ALICE).status_code == 200
    assert client.get("/api/v1/identity/tenants", headers=as_user(ALICE)).json() == []


def test_admin_can_deactivate_non_owners_but_not_owners(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    add_member(client, tid, ALICE, CAROL, "ca")
    assert deactivate(client, tid, BOB, CAROL).status_code == 200
    assert deactivate(client, tid, BOB, ALICE).status_code == 404


@pytest.mark.parametrize("role", ["billing", "ca"])
def test_non_admin_roles_cannot_deactivate(client, role):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, role)
    add_member(client, tid, ALICE, CAROL, "ca")
    assert deactivate(client, tid, BOB, CAROL).status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{tid}", headers=as_user(CAROL)).status_code == 200


def test_deactivated_admin_can_no_longer_deactivate_others(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, tid, ALICE, BOB, "admin")
    add_member(client, tid, ALICE, CAROL, "billing")
    deactivate(client, tid, ALICE, BOB)
    assert deactivate(client, tid, BOB, CAROL).status_code == 404


def test_unknown_member_is_404(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    assert deactivate(client, tid, ALICE, "nobody").status_code == 404


def test_other_tenant_looks_like_it_does_not_exist(client):
    alice_tid = make_tenant(client, ALICE, "Alice Co")
    add_member(client, alice_tid, ALICE, CAROL, "billing")
    make_tenant(client, BOB, "Bob Co")
    real = deactivate(client, alice_tid, BOB, CAROL)
    fake = deactivate(client, str(uuid.uuid4()), BOB, CAROL)
    assert real.status_code == fake.status_code == 404
    assert real.json() == fake.json()
    assert client.get(f"/api/v1/identity/tenants/{alice_tid}", headers=as_user(CAROL)).status_code == 200


def test_cannot_deactivate_a_member_of_another_tenant_through_own_tenant(client):
    alice_tid = make_tenant(client, ALICE, "Alice Co")
    bob_tid = make_tenant(client, BOB, "Bob Co")
    add_member(client, bob_tid, BOB, CAROL, "billing")
    assert deactivate(client, alice_tid, ALICE, CAROL).status_code == 404
    assert client.get(f"/api/v1/identity/tenants/{bob_tid}", headers=as_user(CAROL)).status_code == 200


def test_requires_authentication(client):
    tid = make_tenant(client, ALICE, "Alice Co")
    r = client.post(f"/api/v1/identity/tenants/{tid}/members/{ALICE}/deactivate", json={"reason": "x"})
    assert r.status_code == 401
