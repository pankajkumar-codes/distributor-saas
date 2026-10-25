"""Build-readiness 2.5 (LLD-6 §10): replacing the T-013 guard with CREATE OR REPLACE
FUNCTION, as app_owner after the take-ownership file, keeps the trigger bound and
changes its behaviour, with no DROP. Also pins two Postgres facts the take-ownership
file and LLD-6 migration 2 depend on.

Needs a disposable PostgreSQL with trust auth: PG_DSN=postgresql://postgres@localhost:5432/postgres
"""

import os
import uuid

import psycopg
import pytest

DSN = os.environ.get("PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="PG_DSN not set")

GUARD_T013 = """
create function identity.guard_owner_rows() returns trigger
language plpgsql security definer set search_path = identity as $$
begin
    if old.role = 'owner' and new.status <> 'active' then
        raise exception 'the last owner cannot be deactivated' using errcode = 'insufficient_privilege';
    end if;
    return new;
end $$
"""

# LLD-6 §5.3: owners may be deactivated once the business is closed in the same transaction.
GUARD_CLOSURE = """
create or replace function identity.guard_owner_rows() returns trigger
language plpgsql security definer set search_path = identity as $$
begin
    if old.role = 'owner' and new.status <> 'active'
       and (select status from identity.businesses where id = old.business_id) <> 'closed' then
        raise exception 'the last owner cannot be deactivated' using errcode = 'insufficient_privilege';
    end if;
    return new;
end $$
"""


def _dsn(user: str, db: str) -> str:
    rest = DSN.split("://", 1)[1].split("@", 1)[1].rsplit("/", 1)[0]
    return f"postgresql://{user}@{rest}/{db}"


@pytest.fixture()
def db():
    """A database owned by an RDS-like master (CREATEROLE, not superuser) holding
    app_owner WITH INHERIT FALSE, SET TRUE (LLD-0 §4.1), and the T-013 guard
    created by master as the grandfathered file does."""
    tag = uuid.uuid4().hex[:8]
    name, master, owner = f"tr_{tag}", f"master_{tag}", f"app_owner_{tag}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"create role {master} login createrole createdb")
        admin.execute(f"create database {name} owner {master}")
    with psycopg.connect(_dsn(master, name), autocommit=True) as c:
        c.execute(f"create role {owner} nologin")
        c.execute(f"grant {owner} to {master} with inherit false, set true")
        c.execute("create schema identity")
        c.execute("create table identity.businesses (id int primary key, status text not null)")
        c.execute(
            "create table identity.memberships (id int primary key,"
            " business_id int references identity.businesses, role text, status text)"
        )
        c.execute(GUARD_T013)
        c.execute("revoke all on function identity.guard_owner_rows() from public")
        c.execute(
            "create trigger guard_owner_rows before update on identity.memberships"
            " for each row execute function identity.guard_owner_rows()"
        )
        c.execute("insert into identity.businesses values (1, 'active')")
        c.execute("insert into identity.memberships values (1, 1, 'owner', 'active')")
        yield c, owner
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f"drop database {name} with (force)")
        admin.execute(f"drop role {owner}")
        admin.execute(f"drop role {master}")


def _take_ownership(c, owner: str) -> None:
    # The new owner needs CREATE on the schema, and master loses USAGE once the
    # schema itself moves (INHERIT FALSE), so: grant, objects, schema last.
    c.execute(f"grant usage, create on schema identity to {owner}")
    c.execute(f"alter table identity.businesses owner to {owner}")
    c.execute(f"alter table identity.memberships owner to {owner}")
    c.execute(f"alter function identity.guard_owner_rows() owner to {owner}")
    c.execute(f"alter schema identity owner to {owner}")


def _fn(c):
    return c.execute(
        "select p.oid, t.tgfoid, p.prosecdef, p.proconfig, p.proacl::text from pg_proc p"
        " join pg_trigger t on t.tgfoid = p.oid where p.proname = 'guard_owner_rows'"
    ).fetchone()


def test_replace_as_app_owner_keeps_trigger_and_adds_closure_exception(db):
    c, owner = db
    _take_ownership(c, owner)
    oid_before = _fn(c)[0]

    c.execute(f"set role {owner}")
    c.execute(GUARD_CLOSURE)
    c.execute("reset role")

    oid, tgfoid, secdef, config, acl = _fn(c)
    assert (oid, tgfoid) == (oid_before, oid_before)  # same function, trigger untouched
    assert secdef and config == ["search_path=identity"]
    assert "=X/" not in acl.replace(f"{owner}=X/", "")  # still no PUBLIC execute

    c.execute(f"set role {owner}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("update identity.memberships set status = 'deactivated' where id = 1")
    with c.transaction():
        c.execute("update identity.businesses set status = 'closed' where id = 1")
        c.execute("update identity.memberships set status = 'deactivated' where id = 1")
    assert c.execute("select status from identity.memberships").fetchone() == ("deactivated",)


def test_replace_before_take_ownership_is_refused(db):
    # Migration 2 runs as app_owner, so it depends on the take-ownership file covering
    # the grandfathered guard function (LLD-0 §4.1).
    c, owner = db
    c.execute(f"grant usage, create on schema identity to {owner}")
    c.execute(f"set role {owner}")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="must be owner"):
        c.execute(GUARD_CLOSURE)


def test_take_ownership_needs_create_on_schema_first(db):
    c, owner = db
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="schema identity"):
        c.execute(f"alter table identity.memberships owner to {owner}")


def test_replace_without_security_definer_resets_it(db):
    # CREATE OR REPLACE resets attributes it doesn't restate, so migration 2 must
    # repeat SECURITY DEFINER and SET search_path.
    c, owner = db
    _take_ownership(c, owner)
    c.execute(f"set role {owner}")
    c.execute(
        "create or replace function identity.guard_owner_rows() returns trigger"
        " language plpgsql as $$ begin return new; end $$"
    )
    c.execute("reset role")
    _, _, secdef, config, _ = _fn(c)
    assert not secdef and config is None
