"""T-001: the shared tenant-authorization dependency, as a non-identity service sees it.

Runs the identity migrations on a throwaway database and connects as svc_commerce,
which has no grants on identity tables. Skipped unless PG_ADMIN_URL points at a
disposable server, e.g. PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import os
import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from platform_common.auth import Principal
from platform_common.tenancy import TenantContext, bind_tenant, tenant_dependency

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")

REPO = Path(__file__).resolve().parents[3]
IDENTITY_MIGRATIONS = sorted((REPO / "app" / "src" / "app" / "modules" / "identity" / "migrations").glob("*.sql"))

# A stand-in for a service table protected the way ADR 0001 prescribes.
SERVICE_TABLE = """
create schema demo;
grant usage on schema demo to svc_commerce;
create table demo.notes (tenant_id uuid not null, body text not null);
grant select, insert on demo.notes to svc_commerce;
alter table demo.notes enable row level security;
create policy tenant_rows on demo.notes to svc_commerce
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.is_member(tenant_id))
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.is_member(tenant_id));
"""


@pytest.fixture(scope="module")
def pg():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    url = make_url(ADMIN_URL)
    owner = create_engine(url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        raw = c.connection.driver_connection
        for m in IDENTITY_MIGRATIONS:
            raw.execute(m.read_text())
        raw.execute(SERVICE_TABLE)
        raw.execute("alter role svc_commerce password 'test-only'")
    svc = create_engine(url.set(username="svc_commerce", password="test-only", database=dbname))
    yield owner, svc
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def _member(owner, tenant_id, user, role="sales", status="active"):
    with owner.connect() as c:
        c.execute(text("insert into identity.tenants (id, name) values (:t, 'T') on conflict do nothing"), {"t": tenant_id})
        c.execute(
            text("insert into identity.memberships (id, tenant_id, user_sub, role, status) values (:i, :t, :u, :r, :s)"),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user, "r": role, "s": status},
        )


@pytest.fixture()
def tenants(pg):
    owner, svc = pg
    a, b = uuid.uuid4(), uuid.uuid4()
    alice, bob, carol = (f"{n}_{uuid.uuid4().hex[:6]}" for n in ("alice", "bob", "carol"))
    _member(owner, a, alice, "owner")
    _member(owner, b, bob, "viewer")
    _member(owner, a, carol, "finance", status="disabled")
    return sessionmaker(bind=svc), {"a": a, "b": b, "alice": alice, "bob": bob, "carol": carol}


def _status_of(fn):
    try:
        fn()
    except HTTPException as exc:
        return exc.status_code
    return 200


def test_member_gets_their_role(tenants):
    factory, t = tenants
    with factory() as s:
        ctx = bind_tenant(s, str(t["a"]), Principal(t["alice"]))
    assert ctx == TenantContext(tenant_id=t["a"], user_sub=t["alice"], role="owner")


@pytest.mark.parametrize("case", ["other_tenant", "unknown_tenant", "malformed", "disabled_member"])
def test_everything_else_is_the_same_404(tenants, case):
    factory, t = tenants
    raw, user = {
        "other_tenant": (str(t["b"]), t["alice"]),
        "unknown_tenant": (str(uuid.uuid4()), t["alice"]),
        "malformed": ("not-a-uuid", t["alice"]),
        "disabled_member": (str(t["a"]), t["carol"]),
    }[case]
    with factory() as s:
        assert _status_of(lambda: bind_tenant(s, raw, Principal(user))) == 404


def test_service_cannot_read_identity_tables(tenants):
    factory, _ = tenants
    with factory() as s, pytest.raises(ProgrammingError, match="permission denied"):
        s.execute(text("select * from identity.memberships")).all()


def test_rls_context_survives_commit(tenants):
    factory, t = tenants
    with factory() as s:
        bind_tenant(s, str(t["a"]), Principal(t["alice"]))
        s.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'a1')"), {"t": t["a"]})
        s.commit()
        # A new transaction starts here; without re-binding RLS would hide everything.
        assert s.scalar(text("select count(*) from demo.notes")) == 1
        with pytest.raises(ProgrammingError, match="row-level security"):
            s.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'x')"), {"t": t["b"]})
    with factory() as s:
        bind_tenant(s, str(t["b"]), Principal(t["bob"]))
        assert s.scalar(text("select count(*) from demo.notes")) == 0


def test_unbound_session_sees_nothing(tenants):
    factory, t = tenants
    with factory() as s:
        bind_tenant(s, str(t["a"]), Principal(t["alice"]))
        s.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'a2')"), {"t": t["a"]})
        s.commit()
    with factory() as s:
        assert s.scalar(text("select count(*) from demo.notes")) == 0


def test_session_cannot_be_rebound_to_another_tenant(tenants):
    factory, t = tenants
    with factory() as s:
        bind_tenant(s, str(t["a"]), Principal(t["alice"]))
        with pytest.raises(RuntimeError):
            bind_tenant(s, str(t["b"]), Principal(t["alice"]))


def test_fastapi_dependency(tenants, monkeypatch):
    factory, t = tenants
    monkeypatch.setenv("PLATFORM_ENV", "test")

    def db_session():
        with factory() as s:
            yield s

    tenant = tenant_dependency(db_session)
    app = FastAPI()

    @app.get("/demo/tenants/{tenant_id}/notes")
    def notes(ctx: TenantContext = Depends(tenant), s: Session = Depends(db_session)):
        return {"role": ctx.role, "count": s.scalar(text("select count(*) from demo.notes"))}

    client = TestClient(app)
    path = f"/demo/tenants/{t['a']}/notes"
    r = client.get(path, headers={"x-debug-user": t["alice"]})
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert client.get(path, headers={"x-debug-user": t["bob"]}).status_code == 404
    assert client.get(path).status_code == 401
