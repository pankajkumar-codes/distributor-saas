"""retention.purge_operational() on the real migrations (LLD-0 AC-5, AC-15; LLD-6 §6.4).

Rows are planted as the bootstrap superuser across two businesses, the function is
called as app_retention exactly as the retention Lambda calls it, and every test rolls
back. The privilege test lists everything retention_owner (the function's definer) can
do to any table, so a later grant on the audit log or a financial, stock or GST table
fails here until someone decides it on purpose.
"""

import uuid

import psycopg
import pytest

# Everything retention_owner may do to a table. Nothing else: not the audit log, not any
# financial, stock or GST table (D-041).
ALLOWED = {
    "identity.invitations": {"SELECT", "DELETE"},
    "identity.pending_signups": {"SELECT", "DELETE"},
    "identity.sessions": {"SELECT", "DELETE"},
    "identity.verification_codes": {"SELECT", "DELETE"},
    "platform.idempotency_keys": {"SELECT", "DELETE"},
    "platform.jobs": {"SELECT", "DELETE"},
    "platform.outbox": {"SELECT", "DELETE"},
    "platform.rate_counters": {"SELECT", "DELETE"},
    "platform.retention_runs": {"INSERT"},
    "refdata.values": {"SELECT"},
}
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
TABLES_SQL = """
    select c.oid, n.nspname || '.' || c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
    where c.relkind in ('r', 'p', 'v', 'm') and n.nspname not in ('pg_catalog', 'information_schema')
      and n.nspname not like 'pg\\_%%'
"""


def _privileges(conn, role):
    held = {}
    for oid, name in conn.execute(TABLES_SQL).fetchall():
        got = {
            p
            for p in PRIVILEGES
            if conn.execute("select has_table_privilege(%s, %s, %s)", (role, oid, p)).fetchone()[0]
        }
        for p in ("SELECT", "INSERT", "UPDATE"):  # a column grant without the table-level one
            if (
                p not in got
                and conn.execute(
                    "select bool_or(has_column_privilege(%s, attrelid, attnum, %s)) from pg_attribute"
                    " where attrelid = %s and attnum > 0 and not attisdropped",
                    (role, p, oid),
                ).fetchone()[0]
            ):
                got.add(f"COLUMN {p}")
        if got:
            held[name] = got
    return held


def test_definer_reaches_only_operational_tables(migrated_db):
    assert _privileges(migrated_db, "retention_owner") == ALLOWED


def test_audit_and_business_tables_are_out_of_reach(migrated_db):
    held = _privileges(migrated_db, "retention_owner")
    for name in held:
        assert "audit" not in name, name
        assert name.split(".")[0] in ("platform", "identity", "refdata"), name


@pytest.mark.parametrize("role, login", [("retention_owner", False), ("app_retention", True)])
def test_role_attributes(migrated_db, role, login):
    row = migrated_db.execute(
        "select rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, rolcanlogin"
        " from pg_roles where rolname = %s",
        (role,),
    ).fetchone()
    assert row == (False, False, False, False, False, login), role


def test_login_role_only_executes(migrated_db):
    assert _privileges(migrated_db, "app_retention") == {}
    fns = migrated_db.execute(
        "select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
        " where n.nspname = 'retention'"
    ).fetchall()
    assert [f for (f,) in fns] == ["retention.purge_operational(boolean,integer)"]
    for role, can in (("app_retention", True), ("app_rw", False), ("app_ro", False)):
        assert (
            migrated_db.execute(
                "select has_function_privilege(%s, 'retention.purge_operational(boolean,integer)', 'EXECUTE')", (role,)
            ).fetchone()[0]
            is can
        ), role


@pytest.fixture()
def tx(migrated_db):
    with migrated_db.transaction():
        yield migrated_db
        raise psycopg.Rollback()


def _enable(c):
    c.execute("update refdata.values set value = 'true' where key = 'retention.purge_operational.enabled'")


def _run(c, dry_run=False, max_rows=5000):
    c.execute("set local role app_retention")
    out = c.execute("select retention.purge_operational(%s, %s)", (dry_run, max_rows)).fetchone()[0]
    c.execute("reset role")
    return out


def _plant(c):
    """For each of two businesses: one row per table that may go and one that must stay."""
    ids = {}
    for b in ("b1", "b2"):
        u, biz = uuid.uuid4(), uuid.uuid4()
        c.execute(
            "insert into identity.users (id, cognito_sub, email) values (%s, %s, %s)",
            (u, f"sub-{u}", f"{u}@example.test"),
        )
        c.execute("insert into identity.businesses (id, name, created_by) values (%s, %s, %s)", (biz, b, u))
        ids[b] = (u, biz)
        old, new = "now() - interval '15 days'", "now() - interval '1 day'"
        for tag, at, status in (
            ("go", old, "done"),
            ("go", old, "failed"),
            ("stay", new, "done"),
            ("stay", old, "running"),
        ):
            c.execute(
                f"insert into platform.jobs (id, business_id, type, status, natural_key, updated_at) values (%s, %s, 'x', %s, %s, {at})",
                (uuid.uuid4(), biz, status, f"{tag}-{uuid.uuid4()}"),
            )
        for tag, sent in (("go", old), ("stay", new), ("stay", "null")):
            c.execute(
                f"insert into platform.outbox (id, business_id, type, payload, created_at, sent_at)"
                f" values (%s, %s, %s, '{{}}', now() - interval '20 days', {sent})",
                (uuid.uuid4(), biz, tag),
            )
        c.execute(
            "insert into platform.idempotency_keys (scope, key, request_hash, created_at) values"
            " (%s, 'go', repeat('a', 64), now() - interval '25 hours'), (%s, 'stay', repeat('a', 64), now() - interval '23 hours')",
            (biz, biz),
        )
        sessions = (
            ("go-revoked", "now() - interval '31 days'", "now() + interval '9 days'"),
            ("go-expired", "null", "now() - interval '31 days'"),
            ("stay-live", "null", "now() + interval '1 day'"),  # created long ago, still live
            ("stay-recent", "now() - interval '29 days'", "now() + interval '1 day'"),
        )
        for key, revoked, expires in sessions:
            c.execute(
                f"insert into identity.sessions (id, user_id, key_kind, key_value, auth_time, created_at, absolute_expires_at, revoked_at)"
                f" values (%s, %s, 'sid', %s, now() - interval '60 days', now() - interval '60 days', {expires}, {revoked})",
                (uuid.uuid4(), u, f"{key}-{u}"),
            )
        codes = (
            ("go-used", "now() + interval '1 day'", "now() - interval '25 hours'"),
            ("go-expired", "now() - interval '25 hours'", "null"),
            ("stay-live", "now() + interval '10 minutes'", "null"),  # created long ago, still usable
            ("stay-recent", "now() - interval '1 hour'", "null"),
        )
        for email, expires, consumed in codes:
            c.execute(
                f"insert into identity.verification_codes (id, purpose, email, code_hmac, max_tries, expires_at, consumed_at, created_at)"
                f" values (%s, 'signup', %s, '\\x00', 5, {expires}, {consumed}, now() - interval '3 days')",
                (uuid.uuid4(), f"{email}-{b}@example.test"),
            )
        c.execute(
            "insert into identity.pending_signups (email, created_at, last_code_at) values"
            " (%s, now() - interval '3 days', now() - interval '25 hours'), (%s, now() - interval '3 days', now() - interval '1 hour')",
            (f"go-{b}@example.test", f"stay-{b}@example.test"),
        )
        # Old enough to go by its own dates, but its sign-up code is still usable.
        c.execute(
            "insert into identity.pending_signups (email, created_at, last_code_at)"
            " values (%s, now() - interval '3 days', now() - interval '3 days')",
            (f"stay-live-{b}@example.test",),
        )
        invites = (
            ("go-accepted", "accepted", "now() - interval '31 days'", "null", "now() + interval '1 day'"),
            ("go-cancelled", "cancelled", "null", "now() - interval '31 days'", "now() + interval '1 day'"),
            ("go-lapsed", "pending", "null", "null", "now() - interval '31 days'"),
            ("stay-pending", "pending", "null", "null", "now() + interval '1 day'"),
            ("stay-recent", "accepted", "now() - interval '29 days'", "null", "now() - interval '40 days'"),
        )
        # Planted in their end state directly; the guards' own paths are identity's tests.
        c.execute("set local session_replication_role = replica")
        for email, status, accepted, cancelled, expires in invites:
            c.execute(
                f"insert into identity.invitations (id, business_id, email, role, status, created_at, expires_at, token_hash,"
                f" invited_by_user, accepted_at, cancelled_at) values (%s, %s, %s, 'admin', %s, now() - interval '60 days',"
                f" {expires}, %s, %s, {accepted}, {cancelled})",
                (uuid.uuid4(), biz, f"{email}-{b}@example.test", status, uuid.uuid4().hex * 2, u),
            )
        c.execute("set local session_replication_role = origin")
    return ids


REMAINING = {
    "platform.jobs": "natural_key like 'stay-%%'",
    "platform.outbox": "type = 'stay'",
    "platform.idempotency_keys": "key = 'stay'",
    "identity.sessions": "key_value like 'stay-%%'",
    "identity.verification_codes": "email like 'stay-%%'",
    "identity.pending_signups": "email like 'stay-%%'",
    "identity.invitations": "email like 'stay-%%'",
}
EXPECTED_GONE = {
    "jobs": 4,
    "outbox": 2,
    "idempotency_keys": 2,
    "sessions": 4,
    "verification_codes": 4,
    "pending_signups": 2,
    "invitations": 6,
}


def _counts(c):
    return {
        t: (
            c.execute(f"select count(*) from {t} where {cond}").fetchone()[0],
            c.execute(f"select count(*) from {t} where not ({cond})").fetchone()[0],
        )
        for t, cond in REMAINING.items()
    }


def test_disabled_rule_deletes_nothing(tx):
    _plant(tx)
    before = _counts(tx)
    assert _run(tx) == {"rule": "purge_operational", "skipped": "disabled"}
    assert _counts(tx) == before
    assert tx.execute("select count(*) from platform.retention_runs").fetchone()[0] == 0


def test_deletes_only_expired_rows_of_both_businesses(tx):
    _plant(tx)
    _enable(tx)
    out = _run(tx)
    assert out["counts"] == {**EXPECTED_GONE, "rate_counters": None}  # no refdata row: kept
    assert out["more"] is False
    for table, (stay, gone) in _counts(tx).items():
        assert gone == 0, table
        assert stay > 0, table
    run = tx.execute("select rule, dry_run, counts from platform.retention_runs").fetchall()
    assert run == [("purge_operational", False, out["counts"])]
    assert tx.execute("select current_setting('retention.active', true)").fetchone()[0] == "off"
    live = tx.execute(
        "select count(*) from identity.pending_signups where email like 'stay-live-%%'"
        " union all select count(*) from identity.sessions where key_value like 'stay-live-%%'"
        " union all select count(*) from identity.verification_codes where email like 'stay-live-%%'"
        " union all select count(*) from identity.invitations where email like 'stay-pending-%%'"
    ).fetchall()
    assert live == [(2,), (2,), (2,), (2,)]  # still usable, so kept in both businesses


def test_dry_run_counts_without_deleting(tx):
    _plant(tx)
    before = _counts(tx)
    out = _run(tx, dry_run=True)  # allowed while disabled, so ops can check before switching on
    assert out["counts"] == {**EXPECTED_GONE, "rate_counters": None}
    assert _counts(tx) == before
    assert tx.execute("select dry_run from platform.retention_runs").fetchall() == [(True,)]


def test_limit_reports_more_and_the_next_call_continues(tx):
    _plant(tx)
    _enable(tx)
    first = _run(tx, max_rows=1)
    assert first["more"] is True
    assert all(n in (None, 1) for n in first["counts"].values())
    while _run(tx, max_rows=1)["more"]:
        pass
    assert all(gone == 0 for _, gone in _counts(tx).values())


def test_owner_sees_nothing_without_the_flag(tx):
    _plant(tx)
    tx.execute("set local role retention_owner")
    try:
        for table in REMAINING:
            assert tx.execute(f"select count(*) from {table}").fetchone()[0] == 0, table
    finally:
        tx.execute("reset role")
