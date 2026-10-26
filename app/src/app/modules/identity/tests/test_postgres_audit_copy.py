"""The legacy audit copy (202610261510, LLD-1 §3.6) on PostgreSQL: the ledger up to the
file before it, legacy rows written the way the stock routes wrote them, then the copy,
twice. Skipped unless PG_ADMIN_URL points at a disposable server.
"""

import uuid

import pytest
from sqlalchemy import create_engine, make_url, text

from .conftest import BOOTSTRAP, MIGRATIONS, PG_ADMIN_URL

pytestmark = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")

COPY = next(f for f in MIGRATIONS if f.name.endswith("_identity_audit_copy.sql"))


@pytest.fixture()
def before_copy():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    owner = create_engine(make_url(PG_ADMIN_URL).set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        raw = c.connection.driver_connection
        for sql in [BOOTSTRAP, *MIGRATIONS[: MIGRATIONS.index(COPY)], BOOTSTRAP]:
            raw.execute(sql.read_text())
    yield owner
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def run(owner, sql, **params):
    with owner.begin() as c:
        result = c.execute(text(sql), params)
        return result.all() if result.returns_rows else []


def apply_copy(owner):
    with owner.connect() as c:
        c.connection.driver_connection.execute(COPY.read_text())


def test_legacy_rows_copy_once_with_the_mapping(before_copy):
    owner = before_copy
    alice, biz, member_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    run(owner, "insert into identity.users (id, cognito_sub, email) values (:u, 'alice', 'alice@example.com')", u=alice)
    run(owner, "insert into identity.businesses (id, name, created_by) values (:b, 'A', :u)", b=biz, u=alice)
    legacy = [
        ("tenant.created", "alice", "tenant", str(biz), "{}"),
        ("member.added", "alice", "membership", str(member_id), '{"role": "ca", "user_sub": "bob"}'),
        ("member.deactivated", "gone-sub", "membership", "not-a-uuid", '{"role": "ca", "reason": " left "}'),
        ("invitation.created", "alice", "invitation", str(uuid.uuid4()), '["odd"]'),
    ]
    ids = []
    for action, actor, kind, entity, details in legacy:
        ids.append(uuid.uuid4())
        run(
            owner,
            "insert into identity.audit_events (id, tenant_id, actor_sub, action, entity_type, entity_id, details)"
            " values (:i, :b, :a, :act, :k, :e, cast(:d as json))",
            i=ids[-1], b=biz, a=actor, act=action, k=kind, e=entity, d=details,
        )

    apply_copy(owner)
    apply_copy(owner)  # a re-run copies nothing twice

    rows = {
        r.action: r
        for r in run(
            owner,
            "select id, business_id, user_id, action, target_kind, target_id, reason, data, request_id"
            " from platform.audit_log",
        )
    }
    assert len(rows) == 4 and {r.id for r in rows.values()} == set(ids)
    created = rows["tenant.created"]
    assert (created.business_id, created.user_id, created.target_id) == (biz, alice, biz)
    assert created.data == {"legacy_dropped_keys": 0} and created.request_id == "legacy-copy"
    added = rows["member.added"]
    assert added.data == {"role": "ca", "legacy_dropped_keys": 1} and added.target_id == member_id
    gone = rows["member.deactivated"]
    # An unmatched sub keeps actor_sub; a non-uuid entity id moves into data; reason moves out.
    assert gone.user_id is None and gone.target_id is None and gone.reason == "left"
    assert gone.data == {"role": "ca", "legacy_dropped_keys": 0, "actor_sub": "gone-sub", "entity_id": "not-a-uuid"}
    # Details that aren't a JSON object keep nothing (Staff 2's jsonb_typeof guard).
    assert rows["invitation.created"].data == {"legacy_dropped_keys": 1}

    # The view now reads platform.audit_log only, and the legacy table takes no inserts.
    assert run(owner, "select count(*) from platform.v_audit_log")[0][0] == 4
    assert run(owner, "select pg_get_viewdef('platform.v_audit_log')")[0][0].count("audit_events") == 0
    assert not run(owner, "select has_table_privilege('app_rw', 'identity.audit_events', 'insert')")[0][0]
    check = run(owner, "select with_check from pg_policies where policyname = 'ae_insert'")[0][0]
    assert check == "false"
    # FORCE is back on every table the copy touched.
    forced = run(
        owner,
        "select relname, relforcerowsecurity from pg_class"
        " where oid in ('platform.audit_log'::regclass, 'identity.audit_events'::regclass, 'identity.users'::regclass)",
    )
    assert all(f for _, f in forced)
