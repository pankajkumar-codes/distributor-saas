"""Needs a disposable PostgreSQL: PG_DSN=postgresql://postgres@localhost:5432/postgres"""

import os
import uuid
from pathlib import Path

import psycopg
import psycopg.conninfo
import psycopg.errors
import pytest

from migrator.handler import bootstrap, migrate

DSN = os.environ.get("PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PG_DSN not set")
SERVICES = Path(__file__).resolve().parents[2]


@pytest.fixture()
def conn(tmp_path):
    name = f"m_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create database {name}")
        admin.execute("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$")
    root = tmp_path / "migrations"
    for svc_dir in SERVICES.iterdir():
        if (svc_dir / "migrations").is_dir():
            (root / svc_dir.name).mkdir(parents=True)
            for f in (svc_dir / "migrations").glob("*.sql"):
                (root / svc_dir.name / f.name).write_text(f.read_text())
    with psycopg.connect(DSN.rsplit("/", 1)[0] + f"/{name}", autocommit=True) as c:
        yield c, root
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"drop database {name} with (force)")


def test_applies_once_and_is_safe_to_rerun(conn):
    c, root = conn
    first = migrate(c, root)
    assert "identity/0001_identity.sql" in first
    assert migrate(c, root) == []


def test_refuses_edited_migration(conn):
    c, root = conn
    migrate(c, root)
    f = root / "identity" / "0001_identity.sql"
    f.write_text(f.read_text() + "\n-- edited")
    with pytest.raises(RuntimeError, match="changed after it was applied"):
        migrate(c, root)


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


def test_bootstrap_refuses_and_names_a_role_that_gained_bypassrls(conn):
    c, root = conn
    migrate(c, root)
    c.execute("alter role app_rw bypassrls")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="role app_rw has superuser, bypassrls"):
            migrate(c, root)
    finally:
        c.execute("alter role app_rw nobypassrls")


def test_bootstrap_fixes_login_and_createrole_drift(conn):
    c, root = conn
    migrate(c, root)
    c.execute("alter role app_ro login createrole")
    migrate(c, root)
    assert c.execute("select rolcanlogin, rolcreaterole from pg_roles where rolname = 'app_ro'").fetchone() == (False, False)


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
