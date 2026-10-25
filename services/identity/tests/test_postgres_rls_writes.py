"""Row-level security on the write paths, as svc_identity, bypassing the API.

The API checks membership before every write; these tests ask whether the database
would still stop a write if an API check were forgotten or bypassed (defense in
depth, docs/SECURITY.md). xfail(strict=True) marks known gaps logged in the QA plan
(none open: migration 0004 closed QA-DEF-001, 002, 003, 005 and 006). When a migration closes one, its test starts passing and pytest fails until the
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


def test_admin_cannot_add_or_touch_owners_at_the_database(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin")])
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_sub(c, "erin")
            c.execute(
                text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, 'mallory', 'owner')"),
                {"i": uuid.uuid4(), "t": tid},
            )
    with pytest.raises(Exception, match="only an owner"):
        with svc.begin() as c:
            as_sub(c, "erin")
            c.execute(text("update identity.memberships set status = 'disabled' where user_sub = 'alice'"))
    with pytest.raises(Exception, match="only an owner"):
        with svc.begin() as c:
            as_sub(c, "erin")
            c.execute(text("update identity.memberships set role = 'owner' where user_sub = 'erin'"))
    assert ("alice", "owner", "active") in memberships(svc, tid)
    assert ("erin", "admin", "active") in memberships(svc, tid)


def test_admin_can_deactivate_a_non_owner_and_owner_can_deactivate_admin(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin"), ("sam", "sales")])
    with svc.begin() as c:
        as_sub(c, "erin")
        assert c.execute(text("update identity.memberships set status = 'disabled' where user_sub = 'sam'")).rowcount == 1
    with svc.begin() as c:
        as_sub(c, "alice")
        assert c.execute(text("update identity.memberships set status = 'disabled' where user_sub = 'erin'")).rowcount == 1
    assert {("sam", "sales", "disabled"), ("erin", "admin", "disabled")} <= memberships(svc, tid)


def test_non_admin_member_cannot_add_members_or_write_others_audit(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("sam", "sales")])
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_sub(c, "sam")
            c.execute(
                text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, 'x', 'viewer')"),
                {"i": uuid.uuid4(), "t": tid},
            )
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_sub(c, "sam")
            c.execute(
                text(
                    "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id) "
                    "values (:i, :t, 'alice', 'member.added', 'membership', 'x')"
                ),
                {"i": uuid.uuid4(), "t": tid},
            )


def test_first_owner_rule_only_covers_an_empty_tenant(pg_client):
    client, svc = pg_client
    with svc.begin() as c:
        as_sub(c, "zoe")
        tid = uuid.uuid4()
        c.execute(text("insert into identity.tenants (id, name) values (:t, 'Zoe Co')"), {"t": tid})
        # Not as someone else, not as a lesser role: only themselves as owner.
        for sub, role in (("other", "owner"), ("zoe", "admin")):
            c.execute(text("savepoint s"))
            with pytest.raises(Exception, match="row-level security"):
                c.execute(
                    text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, :u, :r)"),
                    {"i": uuid.uuid4(), "t": tid, "u": sub, "r": role},
                )
            c.execute(text("rollback to savepoint s"))
        c.execute(
            text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, 'zoe', 'owner')"),
            {"i": uuid.uuid4(), "t": tid},
        )


def test_viewer_cannot_rename_tenant_but_admin_can(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("vic", "viewer"), ("erin", "admin")])
    with svc.begin() as c:
        as_sub(c, "vic")
        assert c.execute(text("update identity.tenants set name = 'pwned' where id = :t"), {"t": tid}).rowcount == 0
    with svc.begin() as c:
        as_sub(c, "erin")
        assert c.execute(text("update identity.tenants set name = 'Alice Pvt Ltd' where id = :t"), {"t": tid}).rowcount == 1


def test_admin_can_lock_owner_rows_so_the_api_answers_403(pg_client):
    # The deactivate endpoint locks the target with SELECT ... FOR UPDATE; RLS must not hide it.
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin")])
    with svc.begin() as c:
        as_sub(c, "erin")
        rows = c.execute(
            text("select user_sub from identity.memberships where tenant_id = :t for update"), {"t": tid}
        ).scalars().all()
    assert sorted(rows) == ["alice", "erin"]


def test_membership_cannot_be_moved_to_another_user(pg_client):
    client, svc = pg_client
    setup_alice(client, [("sam", "sales")])
    with pytest.raises(Exception, match="cannot move"):
        with svc.begin() as c:
            as_sub(c, "alice")
            c.execute(text("update identity.memberships set user_sub = 'mallory' where user_sub = 'sam'"))


def _as_invitee(conn, sub, email):
    conn.execute(
        text("select set_config('app.user_sub', :s, true), set_config('app.user_email', :e, true)"),
        {"s": sub, "e": email},
    )


def _insert_member(conn, tid, sub, role):
    conn.execute(
        text("insert into identity.memberships (id, tenant_id, user_sub, role) values (:i, :t, :u, :r)"),
        {"i": uuid.uuid4(), "t": tid, "u": sub, "r": role},
    )


def test_invitee_can_insert_only_their_own_membership_with_the_invited_role(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    r = client.post(
        f"/identity/tenants/{tid}/invitations",
        json={"email": "ivy@example.com", "role": "sales"},
        headers={"x-debug-user": "alice"},
    )
    assert r.status_code == 201
    refused = [
        ("ivy", "ivy@example.com", "owner"),  # a role other than the invited one
        ("mallory", "mallory@example.com", "sales"),  # no invitation for this email
        ("mallory", "", "sales"),  # no verified email at all
    ]
    for sub, email, role in refused:
        with pytest.raises(Exception, match="row-level security"):
            with svc.begin() as c:
                _as_invitee(c, sub, email)
                _insert_member(c, tid, sub, role)
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            # The invitation's email does not let you add somebody else.
            _as_invitee(c, "ivy", "ivy@example.com")
            _insert_member(c, tid, "mallory", "sales")
    with svc.begin() as c:
        _as_invitee(c, "ivy", "ivy@example.com")
        _insert_member(c, tid, "ivy", "sales")
    assert ("ivy", "sales", "active") in memberships(svc, tid)


def test_revoked_or_expired_invitation_does_not_allow_a_membership_insert(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    ids = {}
    for email in ("rev@example.com", "old@example.com"):
        r = client.post(
            f"/identity/tenants/{tid}/invitations",
            json={"email": email, "role": "viewer"},
            headers={"x-debug-user": "alice"},
        )
        assert r.status_code == 201
        ids[email] = r.json()["id"]
    revoke = client.post(
        f"/identity/tenants/{tid}/invitations/{ids['rev@example.com']}/revoke", headers={"x-debug-user": "alice"}
    )
    assert revoke.status_code == 200
    with svc.begin() as c:
        as_sub(c, "alice")
        c.execute(
            text("update identity.invitations set expires_at = now() - interval '1 day' where email = 'old@example.com'")
        )
    for sub, email in (("rev", "rev@example.com"), ("old", "old@example.com")):
        with pytest.raises(Exception, match="row-level security"):
            with svc.begin() as c:
                _as_invitee(c, sub, email)
                _insert_member(c, tid, sub, "viewer")
