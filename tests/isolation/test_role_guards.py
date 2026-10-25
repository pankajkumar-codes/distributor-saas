"""Role guards (build-readiness 2.6; LLD-0 AC-6, §4.1, §11; LLD-1 §3.4; LLD-4 §14).

Row-level security is the tenant boundary, and a role that is a superuser, has
BYPASSRLS, or can become one of those walks straight past it. These tests check the
role attributes PostgreSQL actually holds after every migration has run, not what the
SQL meant to do.

migrator/bootstrap.sql creates every role listed here (build-readiness 2.8). A role
added to ROLES before the bootstrap creates it goes into NOT_YET_CREATED: its checks
are strict xfails, so the PR that creates it must take its name out again.
"""

import pytest

# Every role the approved design names that serves requests or owns
# SECURITY DEFINER functions, with whether it may log in.
ROLES = {
    "app_rw": True,  # API and worker Lambdas (LLD-0 §4.1)
    "app_ro": False,  # SET LOCAL ROLE only (LLD-0 §4.1)
    "app_retention": True,  # daily retention job (LLD-0 §4.1)
    "retention_owner": False,  # owns retention.* functions (LLD-0 §4.1, RM4-1)
    "platform_ops": False,  # owns sweep_outbox, mark_outbox_sent, claim_job (RM4-2)
    "identity_auth": False,  # owns identity.auth_* functions (LLD-1 L1-3, §3.4)
    "share_ops": False,  # owns sales.open_share (LLD-4 L4-7, §14)
}
NOT_YET_CREATED: set[str] = set()

# Attributes that bypass RLS or lead to a role that does. LLD-0 AC-6 names rolsuper
# and rolbypassrls; QA adds rolcreaterole (can grant itself other roles) and
# rolreplication (can stream every row out through replication).
ELEVATED = ("rolsuper", "rolbypassrls", "rolcreaterole", "rolreplication")

# Built-in roles that read or write around RLS, or reach the server's files.
DANGEROUS_BUILTINS = (
    "pg_read_all_data",
    "pg_write_all_data",
    "pg_read_server_files",
    "pg_write_server_files",
    "pg_execute_server_program",
)


def _param(role):
    marks = []
    if role in NOT_YET_CREATED:
        marks.append(pytest.mark.xfail(reason="created by migrator/bootstrap.sql in S0a (build-readiness 2.8)"))
    return pytest.param(role, marks=marks, id=role)


ROLE_PARAMS = [_param(r) for r in ROLES]


def _attrs(conn, role):
    row = conn.execute(
        "select rolsuper, rolbypassrls, rolcreaterole, rolreplication, rolcanlogin from pg_roles where rolname = %s",
        (role,),
    ).fetchone()
    assert row is not None, f"role {role} does not exist"
    return dict(zip((*ELEVATED, "rolcanlogin"), row))


@pytest.mark.parametrize("role", ROLE_PARAMS)
def test_role_has_no_rls_bypass(migrated_db, role):
    attrs = _attrs(migrated_db, role)
    granted = [a for a in ELEVATED if attrs[a]]
    assert not granted, f"{role} has {', '.join(granted)}"


@pytest.mark.parametrize("role", [_param(r) for r, login in ROLES.items() if not login])
def test_owner_roles_cannot_log_in(migrated_db, role):
    assert _attrs(migrated_db, role)["rolcanlogin"] is False, f"{role} can log in; the design says NOLOGIN"


@pytest.mark.parametrize("role", ROLE_PARAMS)
def test_role_cannot_reach_a_privileged_role(migrated_db, role):
    """Membership is checked transitively, because SET ROLE works along any chain.
    Reaching app_owner counts too: the owner can ALTER TABLE ... NO FORCE."""
    _attrs(migrated_db, role)
    reached = migrated_db.execute(
        """
        with recursive up(oid) as (
            select oid from pg_roles where rolname = %(role)s
            union
            select m.roleid from pg_auth_members m join up on m.member = up.oid
        )
        select r.rolname from up join pg_roles r on r.oid = up.oid
        where r.rolname <> %(role)s
          and (r.rolsuper or r.rolbypassrls or r.rolname = 'app_owner' or r.rolname = any(%(builtins)s))
        order by 1
        """,
        {"role": role, "builtins": list(DANGEROUS_BUILTINS)},
    ).fetchall()
    assert not reached, f"{role} can reach {', '.join(n for (n,) in reached)}"


def test_only_the_bootstrap_superuser_has_elevated_attributes(migrated_db):
    """Covers every role on the server today, including the svc_* logins and
    tenant_auth, so a migration that grants BYPASSRLS to anything fails here."""
    rows = migrated_db.execute(
        """
        select rolname, rolsuper, rolbypassrls, rolcreaterole, rolreplication from pg_roles
        where rolname <> current_user and rolname not like 'pg\\_%%'
          and (rolsuper or rolbypassrls or rolcreaterole or rolreplication)
        order by 1
        """
    ).fetchall()
    assert not rows, "roles with elevated attributes: " + ", ".join(
        f"{name} ({', '.join(a for a, on in zip(ELEVATED, flags) if on)})" for name, *flags in rows
    )


def test_login_roles_own_nothing(migrated_db):
    """An owner is exempt from RLS unless the table is FORCEd, and can turn FORCE off.
    So no role that logs in, other than the migrating superuser, may own a schema,
    table, view, sequence or function."""
    rows = migrated_db.execute(
        """
        with logins as (
            select oid, rolname from pg_roles where rolcanlogin and rolname <> current_user
        )
        select l.rolname, 'schema', n.nspname from pg_namespace n join logins l on l.oid = n.nspowner
        union all
        select l.rolname, 'relation', c.relnamespace::regnamespace || '.' || c.relname
        from pg_class c join logins l on l.oid = c.relowner
        union all
        select l.rolname, 'function', p.oid::regprocedure::text
        from pg_proc p join logins l on l.oid = p.proowner
        order by 1, 2, 3
        """
    ).fetchall()
    assert not rows, "login roles own objects: " + ", ".join(f"{r} owns {k} {o}" for r, k, o in rows)
