"""Needs a disposable PostgreSQL: PG_DSN=postgresql://postgres@localhost:5432/postgres"""

import os
import uuid
from pathlib import Path

import psycopg
import psycopg.conninfo
import psycopg.errors
import pytest

from migrator.handler import bootstrap, migrate, ordered
from migrator.local import collect

DSN = os.environ.get("PG_DSN")
needs_pg = pytest.mark.skipif(not DSN, reason="PG_DSN not set")


@pytest.fixture()
def conn(tmp_path):
    name = f"m_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create database {name}")
        admin.execute("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$")
    root = tmp_path / "migrations"
    collect(root)
    with psycopg.connect(DSN.rsplit("/", 1)[0] + f"/{name}", autocommit=True) as c:
        yield c, root
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"drop database {name} with (force)")


@needs_pg
def test_applies_once_and_is_safe_to_rerun(conn):
    c, root = conn
    first = migrate(c, root)
    assert "identity/0001_identity.sql" in first
    assert migrate(c, root) == []


@needs_pg
def test_applies_platform_common_migrations_as_module_platform(conn):
    c, root = conn
    applied = migrate(c, root)
    assert "platform/202610251600_platform_idempotency.sql" in applied
    forced = c.execute(
        "select relrowsecurity and relforcerowsecurity from pg_class where oid = 'platform.idempotency_keys'::regclass"
    ).fetchone()
    assert forced == (True,)


@needs_pg
def test_refuses_edited_migration(conn):
    c, root = conn
    migrate(c, root)
    f = root / "identity" / "0001_identity.sql"
    f.write_text(f.read_text() + "\n-- edited")
    with pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate(c, root)


def _tree(tmp_path: Path, files: dict[str, list[str]]) -> Path:
    for module, names in files.items():
        (tmp_path / module).mkdir()
        for n in names:
            (tmp_path / module / n).write_text("select 1;")
    return tmp_path


def test_grandfathered_files_first_then_timestamps_across_modules(tmp_path):
    root = _tree(tmp_path, {
        "identity": ["0001_a.sql", "0002_b.sql", "202611010900_c.sql"],
        "imports": ["0001_x.sql"],
        "platform": ["202611010900_p.sql", "202610300000_q.sql"],
    })
    got = [f"{m}/{p.name}" for m, p in ordered(root)]
    assert got == [
        "identity/0001_a.sql", "identity/0002_b.sql", "imports/0001_x.sql",
        "platform/202610300000_q.sql", "platform/202611010900_p.sql", "identity/202611010900_c.sql",
    ]


@pytest.mark.parametrize("files", [{"identity": ["3_bad.sql"]}, {"nosuchmodule": ["0001_a.sql"]}])
def test_refuses_bad_names_and_unknown_modules(tmp_path, files):
    with pytest.raises(RuntimeError):
        ordered(_tree(tmp_path, files))


DESIGN_ROLES = {
    "app_owner": False,
    "app_rw": True,
    "app_ro": False,
    "app_retention": True,
    "retention_owner": False,
    "platform_ops": False,
    "identity_auth": False,
    "share_ops": False,
}


@needs_pg
def test_bootstrap_creates_the_design_roles_without_rls_bypass(conn):
    c, root = conn
    migrate(c, root)
    rows = {
        r[0]: r[1:]
        for r in c.execute(
            "select rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication "
            "from pg_roles where rolname = any(%s)",
            (list(DESIGN_ROLES),),
        )
    }
    assert set(rows) == set(DESIGN_ROLES)
    for name, login in DESIGN_ROLES.items():
        assert rows[name] == (login, False, False, False, False, False), name


@needs_pg
def test_bootstrap_memberships(conn):
    c, root = conn
    migrate(c, root)

    def member(role, of):
        return c.execute(
            "select m.set_option, m.inherit_option from pg_auth_members m "
            "join pg_roles r on r.oid = m.roleid join pg_roles g on g.oid = m.member "
            "where r.rolname = %s and g.rolname = %s and not m.admin_option",
            (of, role),
        ).fetchone()

    # The migrator can SET ROLE app_owner but doesn't inherit its rights.
    assert member(c.execute("select current_user").fetchone()[0], "app_owner") == (True, False)
    assert member("app_rw", "app_ro") == (True, False)
    # Bridge to the legacy identity roles, which the ledger files create (L0-5).
    assert member("app_rw", "svc_identity") == (True, True)
    assert member("app_rw", "tenant_auth") == (True, True)
    assert c.execute("select has_database_privilege('app_owner', current_database(), 'CREATE')").fetchone()[0]


@needs_pg
def test_bootstrap_refuses_and_names_a_role_that_gained_bypassrls(conn):
    c, root = conn
    migrate(c, root)
    c.execute("alter role app_rw bypassrls")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="role app_rw has superuser, bypassrls"):
            migrate(c, root)
    finally:
        c.execute("alter role app_rw nobypassrls")


@needs_pg
def test_bootstrap_fixes_login_and_createrole_drift(conn):
    c, root = conn
    migrate(c, root)
    c.execute("alter role app_ro login createrole")
    migrate(c, root)
    assert c.execute("select rolcanlogin, rolcreaterole from pg_roles where rolname = 'app_ro'").fetchone() == (False, False)


@needs_pg
def test_bootstrap_runs_as_a_non_superuser_createrole_master(tmp_path):
    # On RDS the master is rds_superuser, not a superuser (build-readiness 2.1 stand-in).
    db, master = f"m_{uuid.uuid4().hex[:10]}", f"master_{uuid.uuid4().hex[:6]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create role {master} login createrole createdb")
        admin.execute(f"create database {db} owner {master}")
        # Roles are cluster-wide, so other tests may already have created them as the
        # superuser. On RDS the master creates them and so administers them; mirror that.
        # RDS's master (rds_superuser) can grant rds_iam; give the stand-in the same.
        admin.execute("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$")
        admin.execute(f"grant rds_iam to {master} with admin true, inherit false, set false")
        for role in [*DESIGN_ROLES, "svc_identity", "tenant_auth"]:
            if admin.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone():
                admin.execute(f"grant {role} to {master} with admin true, inherit false, set false")
    try:
        params = psycopg.conninfo.conninfo_to_dict(DSN) | {"dbname": db, "user": master}
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params), autocommit=True) as c:
            bootstrap(c)
            bootstrap(c)  # idempotent, including for roles this master didn't create
            assert c.execute(
                "select m.set_option, m.inherit_option from pg_auth_members m join pg_roles r on r.oid = m.roleid "
                "join pg_roles g on g.oid = m.member where r.rolname = 'app_owner' and g.rolname = %s "
                "and not m.admin_option",
                (master,),
            ).fetchone() == (True, False)
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f"drop database {db} with (force)")
            admin.execute(f"drop owned by {master}")
            admin.execute(f"drop role {master}")


def test_support_grant_active_sorts_after_the_identity_reshape(tmp_path):
    # `language sql` checks its body at creation, so it must follow identity.support_grants
    # (build-readiness 2.4); a same-minute tie would put platform first.
    root = tmp_path / "migrations"
    collect(root)
    names = [f"{m}/{f.name}" for m, f in ordered(root)]
    grant_create = names.index("identity/202610251659_identity_auth_schema_create.sql")
    reshape = names.index("identity/202610251700_identity_r1_reshape.sql")
    support = names.index("identity/202610261000_identity_support_and_resolve.sql")
    assert grant_create < reshape < support
    assert all(not n.startswith("platform/2026102610") for n in names[reshape:support])


@needs_pg
def test_every_migration_runs_as_a_non_superuser_createrole_master(tmp_path):
    # The reshape hands functions to identity_auth, which only a superuser may do without
    # CREATE on the schema; RDS's master isn't one. Runs the whole ledger as such a master.
    db, master = f"m_{uuid.uuid4().hex[:10]}", f"master_{uuid.uuid4().hex[:6]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create role {master} login createrole createdb")
        admin.execute(f"create database {db} owner {master}")
        admin.execute("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$")
        admin.execute(f"grant rds_iam to {master} with admin true, inherit false, set false")
        for role in [*DESIGN_ROLES, "svc_identity", "tenant_auth"]:
            if admin.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone():
                admin.execute(f"grant {role} to {master} with admin true, inherit false, set false")
    root = tmp_path / "migrations"
    collect(root)
    try:
        params = psycopg.conninfo.conninfo_to_dict(DSN) | {"dbname": db, "user": master}
        with psycopg.connect(psycopg.conninfo.make_conninfo(**params), autocommit=True) as c:
            assert "identity/202610261000_identity_support_and_resolve.sql" in migrate(c, root)
            assert migrate(c, root) == []
            owners = dict(
                c.execute(
                    "select p.proname, r.rolname from pg_proc p join pg_roles r on r.oid = p.proowner"
                    " where p.proname in ('support_grant_active', 'auth_resolve', 'caller_has_role')"
                ).fetchall()
            )
            assert set(owners.values()) == {"identity_auth"}
            # The CREATE lent for the hand-over is taken back on both schemas.
            assert c.execute(
                "select has_schema_privilege('identity_auth', 'identity', 'create'),"
                " has_schema_privilege('identity_auth', 'platform', 'create')"
            ).fetchone() == (False, False)
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f"drop database {db} with (force)")
            admin.execute(f"drop owned by {master}")
            admin.execute(f"drop role {master}")


def test_the_handler_refuses_to_run_off_lambda(monkeypatch):
    """Locally and in CI the master comes from PG_ADMIN_URL; the handler never reaches for
    the shell's AWS credentials (D-040)."""
    from migrator import handler as handler_module

    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("DB_MASTER_PASSWORD_PARAM", "/distsaas-staging/db/master-password")
    with pytest.raises(RuntimeError, match="Lambda only"):
        handler_module.handler({}, None)
