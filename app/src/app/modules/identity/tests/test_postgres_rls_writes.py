"""Row-level security on the write paths, as app_rw, bypassing the API (LLD-1 §3.4).

The API checks membership before every write; these tests ask whether the database
would still stop a write if an API check were forgotten or bypassed (defense in
depth, docs/SECURITY.md). Each one binds the business the way a request does
(app.tenant_id), so they show what the policies refuse *inside* a business: the
principal resolver decides who may bind one at all (S0a c2).

Skipped unless PG_ADMIN_URL is set (see conftest.py).
"""

import uuid

import pytest
from sqlalchemy import text

from .conftest import PG_ADMIN_URL, seed_member
from .test_postgres_rls import as_user

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


def setup_alice(client, extra=()):
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers={"x-debug-user": "alice"}).json()["id"]
    for sub, role in extra:
        seed_member(tid, sub, role)
    return tid


def memberships(svc, tid):
    with svc.begin() as c:
        as_user(c, "alice", tid)
        return {
            (u, r, s)
            for u, r, s in c.execute(
                text("select user_sub, role, status from identity.memberships where business_id = :t"), {"t": tid}
            )
        }


def _insert_member(conn, tid, sub, role):
    uid = conn.execute(text("select identity.dev_ensure_user(:s)"), {"s": sub}).scalar()
    conn.execute(
        text("insert into identity.memberships (id, business_id, user_id, user_sub, role) values (:i, :t, :u, :s, :r)"),
        {"i": uuid.uuid4(), "t": tid, "u": uid, "s": sub, "r": role},
    )


def test_app_cannot_delete_or_update_businesses(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    for sql in ("delete from identity.memberships", "delete from identity.businesses",
                "update identity.businesses set name = 'pwned'"):
        with pytest.raises(Exception, match="permission denied"):
            with svc.begin() as c:
                as_user(c, "alice", tid)
                c.execute(text(sql))


def test_app_cannot_update_audit(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            as_user(c, "alice", tid)
            c.execute(text("update identity.audit_events set action = 'x'"))


def test_non_manager_update_touches_nothing(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("dave", "billing")])
    for sub in ("dave", "bob"):  # a billing member, and an outsider who binds the business
        with svc.begin() as c:
            as_user(c, sub, tid)
            assert c.execute(text("update identity.memberships set role = 'ca'")).rowcount == 0
    assert ("dave", "billing", "active") in memberships(svc, tid)


def test_deactivated_member_cannot_promote_or_reenable_themselves(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("dave", "admin")])
    with svc.begin() as c:
        as_user(c, "alice", tid)
        c.execute(text("update identity.memberships set status = 'deactivated' where user_sub = 'dave'"))
    with svc.begin() as c:
        as_user(c, "dave", tid)
        n = c.execute(text("update identity.memberships set role = 'owner', status = 'active' where user_sub = 'dave'"))
        assert n.rowcount == 0
    assert ("dave", "admin", "deactivated") in memberships(svc, tid)


def test_outsider_cannot_insert_a_membership_or_audit_into_another_business(pg_client):
    client, svc = pg_client
    tid = setup_alice(client)
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "bob", tid)
            _insert_member(c, tid, "bob", "owner")
    # The legacy table takes no inserts at all since the LLD-2 copy (202610261510).
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            # Not bound to Alice's business: the audit row must be for the bound one.
            as_user(c, "bob")
            c.execute(
                text(
                    "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id) "
                    "values (:i, :t, 'bob', 'tenant.deleted', 'tenant', :e)"
                ),
                {"i": uuid.uuid4(), "t": tid, "e": tid},
            )


def test_audit_rows_are_written_as_the_caller(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("sam", "admin")])
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "sam", tid)
            c.execute(
                text(
                    "insert into platform.audit_log (id, business_id, user_id, action, target_kind, request_id)"
                    " values (:i, :t, identity.dev_ensure_user('alice'), 'member.invite', 'invitation', 'r')"
                ),
                {"i": uuid.uuid4(), "t": tid},
            )
    with pytest.raises(Exception, match="permission denied"):
        with svc.begin() as c:
            as_user(c, "sam", tid)
            c.execute(
                text(
                    "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id) "
                    "values (:i, :t, 'alice', 'member.added', 'membership', 'x')"
                ),
                {"i": uuid.uuid4(), "t": tid},
            )


def test_admin_cannot_add_or_touch_owners_at_the_database(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin")])
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "erin", tid)
            _insert_member(c, tid, "mallory", "owner")
    with pytest.raises(Exception, match="only an owner"):
        with svc.begin() as c:
            as_user(c, "erin", tid)
            c.execute(text("update identity.memberships set status = 'deactivated' where user_sub = 'alice'"))
    with pytest.raises(Exception, match="only an owner"):
        with svc.begin() as c:
            as_user(c, "erin", tid)
            c.execute(text("update identity.memberships set role = 'owner' where user_sub = 'erin'"))
    assert ("alice", "owner", "active") in memberships(svc, tid)
    assert ("erin", "admin", "active") in memberships(svc, tid)


def test_admin_can_deactivate_a_non_owner_and_owner_can_deactivate_admin(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin"), ("sam", "billing")])
    with svc.begin() as c:
        as_user(c, "erin", tid)
        n = c.execute(text("update identity.memberships set status = 'deactivated' where user_sub = 'sam'"))
        assert n.rowcount == 1
    with svc.begin() as c:
        as_user(c, "alice", tid)
        n = c.execute(text("update identity.memberships set status = 'deactivated' where user_sub = 'erin'"))
        assert n.rowcount == 1
    assert {("sam", "billing", "deactivated"), ("erin", "admin", "deactivated")} <= memberships(svc, tid)


def test_non_admin_member_cannot_add_members(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("sam", "billing")])
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "sam", tid)
            _insert_member(c, tid, "x", "ca")


def test_first_owner_rule_only_covers_the_creator_of_an_empty_business(pg_client):
    client, svc = pg_client
    tid = uuid.uuid4()
    with svc.begin() as c:
        as_user(c, "zoe", tid)
        # A business can only be created by the bound caller, for the bound id.
        c.execute(text("savepoint s"))
        with pytest.raises(Exception, match="row-level security"):
            c.execute(
                text("insert into identity.businesses (id, name, created_by) values (:t, 'X', identity.dev_ensure_user('bob'))"),
                {"t": tid},
            )
        c.execute(text("rollback to savepoint s"))
        c.execute(
            text("insert into identity.businesses (id, name, created_by) values (:t, 'Zoe Co', current_setting('app.user_id')::uuid)"),
            {"t": tid},
        )
        # Not someone else, not a lesser role: only themselves, as owner.
        for sub, role in (("other", "owner"), ("zoe", "admin")):
            c.execute(text("savepoint s"))
            with pytest.raises(Exception, match="row-level security"):
                _insert_member(c, tid, sub, role)
            c.execute(text("rollback to savepoint s"))
        _insert_member(c, tid, "zoe", "owner")
    with svc.begin() as c:
        # The rule is spent once the business has a member.
        as_user(c, "zoe", tid)
        c.execute(text("update identity.memberships set status = 'deactivated'"))
    with pytest.raises(Exception, match="row-level security"):
        with svc.begin() as c:
            as_user(c, "zoe2", tid)
            _insert_member(c, tid, "zoe2", "owner")


def test_admin_can_lock_owner_rows_so_the_api_answers_404(pg_client):
    # The deactivate endpoint locks the target with SELECT ... FOR UPDATE; RLS must not hide it.
    client, svc = pg_client
    tid = setup_alice(client, [("erin", "admin")])
    with svc.begin() as c:
        as_user(c, "erin", tid)
        rows = c.execute(
            text("select user_sub from identity.memberships where business_id = :t for update"), {"t": tid}
        ).scalars().all()
    assert sorted(rows) == ["alice", "erin"]


def test_membership_cannot_be_moved_to_another_user(pg_client):
    client, svc = pg_client
    tid = setup_alice(client, [("sam", "billing")])
    with pytest.raises(Exception, match="cannot move"):
        with svc.begin() as c:
            as_user(c, "alice", tid)
            c.execute(
                text("update identity.memberships set user_id = identity.dev_ensure_user('mallory') where user_sub = 'sam'")
            )
