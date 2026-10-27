"""S0a (c3) on PostgreSQL: platform.v_audit_log (LLD-0 §3.6), which reads only
platform.audit_log since the LLD-2 copy (202610261510; the copy itself is tested in
test_postgres_audit_copy.py), and the support exclusion on identity's tenant policies
(LLD-0 §4.2).

Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .conftest import PG_ADMIN_URL
from .test_postgres_support_and_resolve import as_ctx, business, grant, member, seed, user

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")
ALICE = {"x-debug-user": "alice"}
VIEW = "select action, target_kind, target_id, reason, data, request_id, user_id from platform.v_audit_log"


def user_id(sub):
    return seed("select id from identity.users where cognito_sub = :s", s=sub).scalar()


def test_the_view_reads_platform_rows_only(pg_client):
    client, svc = pg_client
    tid = client.post("/api/v1/identity/tenants", json={"name": "Alice Co"}, headers=ALICE).json()["id"]
    alice = user_id("alice")
    seed(
        "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id)"
        " values (:i, :b, 'alice', 'tenant.created', 'tenant', :e)",
        i=uuid.uuid4(), b=tid, e=str(tid),
    )
    with svc.begin() as c:
        as_ctx(c, alice, tenant=tid)
        c.execute(
            text(
                "insert into platform.audit_log (id, business_id, user_id, action, target_kind, target_id, request_id)"
                " values (:i, :b, :u, 'business.create', 'business', :b, 'r1')"
            ),
            {"i": uuid.uuid4(), "b": tid, "u": alice},
        )
        c.execute(
            text(
                "insert into platform.audit_log (id, user_id, action, target_kind, request_id)"
                " values (:i, :u, 'auth.signin', 'user', 'r2')"
            ),
            {"i": uuid.uuid4(), "u": alice},
        )
    with svc.begin() as c:
        as_ctx(c, alice, tenant=tid)
        rows = c.execute(text("select action, request_id from platform.v_audit_log")).all()
        # The route's own business.create, the two rows above, and no legacy row.
        assert sorted(a for a, _ in rows) == ["auth.signin", "business.create", "business.create"]
        assert {"r1", "r2"} <= {r for _, r in rows} and "legacy-copy" not in {r for _, r in rows}
    with svc.begin() as c:
        as_ctx(c, user_id("alice"))  # no business: only the user's own user-level row
        assert c.execute(text("select action from platform.v_audit_log")).scalars().all() == ["auth.signin"]


def test_a_support_grant_id_turns_every_identity_tenant_policy_off(pg_client):
    _, svc = pg_client
    asha, adi, sam = user("asha"), user("adi"), user("sam", support=True)
    a = business(asha)
    member(a, adi, "admin")
    seed(
        "insert into identity.support_grants (id, business_id, granted_by, expires_at) values (:g, :b, :u, now() + interval '1 day')",
        g=uuid.uuid4(), b=a, u=asha,
    )
    seed(
        "insert into identity.invitations (id, business_id, email, role, token_hash, invited_by_user, expires_at)"
        " values (:i, :b, 'p@example.com', 'ca', repeat('a', 64), :u, now() + interval '7 days')",
        i=uuid.uuid4(), b=a, u=asha,
    )
    seed(
        "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id)"
        " values (:i, :b, 'asha', 'tenant.created', 'tenant', :b)",
        i=uuid.uuid4(), b=a,
    )
    tables = ("businesses", "memberships", "support_grants", "invitations", "audit_events")

    def counts(c, names=tables):
        return {t: c.execute(text(f"select count(*) from identity.{t}")).scalar() for t in names}

    with svc.begin() as c:
        as_ctx(c, asha, tenant=a)
        assert counts(c) == {
            "businesses": 1, "memberships": 2, "support_grants": 1, "invitations": 1, "audit_events": 1
        }
    # The owner's own request, but carrying a support grant id that isn't active: no
    # tenant policy matches. Only m_self, which is keyed on the user, still shows her row.
    with svc.begin() as c:
        as_ctx(c, asha, tenant=a, grant_id=uuid.uuid4())
        assert counts(c) == {
            "businesses": 0, "memberships": 1, "support_grants": 0, "invitations": 0, "audit_events": 0
        }
        c.execute(text("set local role app_ro"))  # app_ro has no grant on invitations
        assert counts(c, ("businesses", "memberships", "support_grants", "audit_events")) == {
            "businesses": 0, "memberships": 1, "support_grants": 0, "audit_events": 0
        }
    writes = [
        "insert into identity.memberships (id, business_id, user_id, role, status)"
        " values (gen_random_uuid(), :b, :u, 'ca', 'active')",
        "insert into identity.support_grants (id, business_id, granted_by, expires_at)"
        " values (gen_random_uuid(), :b, :u, now() + interval '1 day')",
        "insert into identity.invitations (id, business_id, email, role, token_hash, invited_by_user, expires_at)"
        " values (gen_random_uuid(), :b, 'q@example.com', 'ca', repeat('b', 64), :u, now() + interval '7 days')",
    ]
    # identity.audit_events takes no inserts from anyone since the LLD-2 copy.
    with pytest.raises(DBAPIError, match="permission denied"):
        with svc.begin() as c:
            as_ctx(c, asha, tenant=a)
            c.execute(
                text(
                    "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id)"
                    " values (gen_random_uuid(), :b, 'asha', 'x', 'x', 'x')"
                ),
                {"b": a},
            )
    for sql in writes:
        with pytest.raises(DBAPIError, match="row-level security"):
            with svc.begin() as c:
                as_ctx(c, asha, tenant=a, grant_id=uuid.uuid4())
                c.execute(text("select set_config('app.user_sub', 'asha', true)"))
                c.execute(text(sql), {"b": a, "u": sam})
    fresh = uuid.uuid4()
    with pytest.raises(DBAPIError, match="row-level security"):
        with svc.begin() as c:
            as_ctx(c, asha, tenant=fresh, grant_id=uuid.uuid4())
            c.execute(text("insert into identity.businesses (id, created_by) values (:b, :u)"), {"b": fresh, "u": asha})
    with svc.begin() as c:
        as_ctx(c, asha, tenant=a, grant_id=uuid.uuid4())
        # No WHERE, so only the update policy's USING decides which rows match.
        assert c.execute(text("update identity.invitations set expires_at = now() + interval '1 day'")).rowcount == 0
    with svc.begin() as c:
        as_ctx(c, adi, tenant=a, grant_id=uuid.uuid4())
        assert c.execute(text("update identity.memberships set role = 'ca'")).rowcount == 0
    # A support user under a live grant still reads the business through support_read.
    gid = grant(a, asha)
    with svc.begin() as c:
        as_ctx(c, sam, tenant=a, grant_id=gid)
        assert counts(c) == {
            "businesses": 1, "memberships": 2, "support_grants": 0, "invitations": 0, "audit_events": 0
        }
