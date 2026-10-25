"""Units of work and business_uow on PostgreSQL with row-level security (LLD-0 §3.1, AC-7).

Carries over #9's bind_tenant tests. Runs the identity migrations on a throwaway
database and connects as svc_commerce, which has no grants on identity tables and sees
a demo table only through RLS. The resolver below stands in for identity's: it asks
`identity.caller_role()`, which answers only for the user in `app.user_sub`.

Skipped unless PG_ADMIN_URL points at a disposable server, e.g.
PG_ADMIN_URL=postgresql+psycopg://postgres@localhost:5432/postgres
"""

import logging
import os
import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import InternalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from platform_common import uow as uow_mod
from platform_common.errors import Deny, install_error_handlers
from platform_common.uow import BusinessUoW, MeUoW, Principal, UnitOfWork, business_uow, unit_of_work

ADMIN_URL = os.environ.get("PG_ADMIN_URL")
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="PG_ADMIN_URL not set")

REPO = Path(__file__).resolve().parents[3]
IDENTITY_MIGRATIONS = sorted((REPO / "app" / "src" / "app" / "modules" / "identity" / "migrations").glob("*.sql"))

# A stand-in for a module table protected the way ADR 0001 prescribes.
DEMO_TABLE = """
do $$ begin if not exists (select from pg_roles where rolname = 'app_ro') then create role app_ro nologin; end if; end $$;
create schema demo;
grant usage on schema demo to svc_commerce;
create table demo.notes (tenant_id uuid not null, body text not null);
grant select, insert on demo.notes to svc_commerce;
alter table demo.notes enable row level security;
create policy tenant_rows on demo.notes to svc_commerce, app_ro
    using (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.is_member(tenant_id))
    with check (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
           and identity.is_member(tenant_id));
grant app_ro to svc_commerce;
grant usage on schema demo to app_ro;
grant select on demo.notes to app_ro;
grant usage on schema identity to app_ro;
grant execute on function identity.is_member(uuid) to app_ro;
-- Fails only at commit, to prove the commit happens before the response is sent.
create table demo.once (k int, constraint once_k unique (k) deferrable initially deferred);
grant insert on demo.once to svc_commerce;
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
        raw.execute(DEMO_TABLE)
        raw.execute("alter role svc_commerce password 'test-only'")
    svc = create_engine(url.set(username="svc_commerce", password="test-only", database=dbname), pool_size=1)
    yield owner, svc
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def _member(owner, tenant_id, user, role, status="active"):
    with owner.connect() as c:
        c.execute(text("insert into identity.tenants (id, name) values (:t, 'T') on conflict do nothing"), {"t": tenant_id})
        c.execute(
            text("insert into identity.memberships (id, tenant_id, user_sub, role, status) values (:i, :t, :u, :r, :s)"),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user, "r": role, "s": status},
        )


def resolver(tx, caller, business_id, request_id):
    if business_id is None:
        return Principal(user_sub=caller.user_sub, request_id=request_id)
    role = tx.scalar(text("select identity.caller_role(:t)"), {"t": business_id})
    if role is None:
        raise Deny("not_member")
    return Principal(user_sub=caller.user_sub, request_id=request_id, business_id=business_id, role=role)


@pytest.fixture()
def t(pg, monkeypatch):
    owner, svc = pg
    monkeypatch.setenv("PLATFORM_ENV", "test")
    uow_mod.set_session_factory(sessionmaker(bind=svc, expire_on_commit=False))
    uow_mod.set_principal_resolver(resolver)
    a, b = uuid.uuid4(), uuid.uuid4()
    names = {n: f"{n}_{uuid.uuid4().hex[:6]}" for n in ("alice", "bob", "carol", "vic")}
    _member(owner, a, names["alice"], "owner")
    _member(owner, b, names["bob"], "owner")
    _member(owner, a, names["carol"], "owner", status="disabled")
    _member(owner, a, names["vic"], "viewer")  # not an owner: refused by owner_only
    yield {"a": a, "b": b, **names, "owner": owner}
    uow_mod.set_session_factory(None)
    uow_mod.set_principal_resolver(None)


def owner_only(uow: UnitOfWork = Depends(business_uow, scope="function")) -> None:
    # Stands in for permissions.require, which moves onto the 4-role matrix next.
    if uow.principal.role != "owner":
        raise Deny("role_denied")


def _app(calls=None):
    app = FastAPI()
    install_error_handlers(app)
    calls = calls if calls is not None else []

    @app.get("/b/{business_id}/notes", dependencies=[Depends(owner_only)])
    def notes(uow: BusinessUoW):
        calls.append(id(uow))
        settings = uow.tx.execute(
            text("select current_setting('app.tenant_id'), current_setting('app.role'), current_setting('app.user_sub')")
        ).one()
        return {"count": uow.tx.scalar(text("select count(*) from demo.notes")), "settings": list(settings)}

    @app.post("/b/{business_id}/notes", dependencies=[Depends(owner_only)])
    def add(business_id: str, body: str, uow: BusinessUoW, fail: bool = False):
        calls.append(id(uow))
        uow.tx.execute(text("insert into demo.notes (tenant_id, body) values (:t, :b)"), {"t": business_id, "b": body})
        uow.after_commit(lambda: calls.append("after_commit"))
        if fail:
            raise Deny("not_found")
        return {"ok": True}

    @app.post("/b/{business_id}/fails-at-commit", dependencies=[Depends(owner_only)])
    def fails_at_commit(uow: BusinessUoW):
        uow.tx.execute(text("insert into demo.once values (1), (1)"))
        return {"ok": True}

    @app.post("/b/{business_id}/nested", dependencies=[Depends(owner_only)])
    def nested(business_id: str, uow: BusinessUoW):
        uow.tx.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'outer')"), {"t": business_id})
        with unit_of_work(uow.principal):
            pass
        return {"ok": True}

    @app.post("/b/{business_id}/nested-async", dependencies=[Depends(owner_only)])
    async def nested_async(business_id: str, uow: BusinessUoW):
        uow.tx.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'outer')"), {"t": business_id})
        with unit_of_work(uow.principal):
            pass
        return {"ok": True}

    @app.get("/me")
    def me(uow: MeUoW):
        return {"tenant": uow.tx.scalar(text("select current_setting('app.tenant_id')"))}

    return TestClient(app, raise_server_exceptions=False)


def _count(owner, tenant_id):
    with owner.connect() as c:
        return c.scalar(text("select count(*) from demo.notes where tenant_id = :t"), {"t": tenant_id})


def test_member_gets_role_and_context(t):
    r = _app().get(f"/b/{t['a']}/notes", headers={"x-debug-user": t["alice"]})
    assert r.status_code == 200
    assert r.json()["settings"] == [str(t["a"]), "owner", t["alice"]]


@pytest.mark.parametrize(
    "case, reason",
    [
        ("other_business", "not_member"),
        ("unknown_business", "not_member"),
        ("malformed", "not_found"),
        ("disabled_member", "not_member"),
        ("not_an_owner", "role_denied"),
    ],
)
def test_every_refusal_is_the_same_404(t, case, reason, caplog):
    caplog.set_level(logging.INFO, "platform_common.errors")
    business, user = {
        "other_business": (t["b"], t["alice"]),
        "unknown_business": (uuid.uuid4(), t["alice"]),
        "malformed": ("not-a-uuid", t["alice"]),
        "disabled_member": (t["a"], t["carol"]),
        "not_an_owner": (t["a"], t["vic"]),
    }[case]
    r = _app().get(f"/b/{business}/notes", headers={"x-debug-user": user})
    assert (r.status_code, r.json()) == (404, {"error": {"code": "not_found", "message": "not found"}})
    assert [rec.reason for rec in caplog.records if getattr(rec, "event", None) == "deny"] == [reason]


def test_no_caller_is_401(t):
    assert _app().get(f"/b/{t['a']}/notes").status_code == 401


def test_commits_before_the_response_and_once_per_request(t, monkeypatch):
    calls, opened = [], []
    real = uow_mod.unit_of_work

    def counting(*args, **kwargs):
        opened.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(uow_mod, "unit_of_work", counting)
    client = _app(calls)
    r = client.post(f"/b/{t['a']}/notes", params={"body": "n1"}, headers={"x-debug-user": t["alice"]})
    assert r.status_code == 200
    assert _count(t["owner"], t["a"]) == 1
    assert calls[-1] == "after_commit"
    # owner_only and the endpoint share one unit of work: one transaction per request.
    assert len(opened) == 1


def test_a_failed_commit_is_a_500_not_a_success(t):
    r = _app().post(f"/b/{t['a']}/fails-at-commit", headers={"x-debug-user": t["alice"]})
    assert r.status_code == 500


def test_error_rolls_back_and_skips_after_commit(t):
    calls = []
    r = _app(calls).post(
        f"/b/{t['a']}/notes", params={"body": "n2", "fail": True}, headers={"x-debug-user": t["alice"]}
    )
    assert r.status_code == 404
    assert _count(t["owner"], t["a"]) == 0
    assert "after_commit" not in calls


def test_rls_refuses_a_write_to_another_business(t):
    r = _app().post(f"/b/{t['b']}/notes", params={"body": "x"}, headers={"x-debug-user": t["alice"]})
    assert r.status_code == 404
    assert _count(t["owner"], t["b"]) == 0


def test_settings_are_transaction_local(t, pg):
    _, svc = pg
    _app().get(f"/b/{t['a']}/notes", headers={"x-debug-user": t["alice"]})
    # pool_size=1: this is the connection the request just used.
    with svc.connect() as c:
        assert c.scalar(text("select current_setting('app.tenant_id', true)")) in ("", None)
        assert c.scalar(text("select count(*) from demo.notes")) == 0


def test_me_uow_has_no_business(t):
    r = _app().get("/me", headers={"x-debug-user": t["alice"]})
    assert r.json() == {"tenant": ""}


def test_nested_unit_of_work_raises(t):
    p = Principal(user_sub=t["alice"], request_id="r")
    with unit_of_work(p), pytest.raises(RuntimeError, match="already open"):
        with unit_of_work(p):
            pass
    with unit_of_work(p):  # and the flag is cleared again
        pass


@pytest.mark.parametrize("route", ["nested", "nested-async"])
def test_a_route_cannot_open_a_second_unit_of_work(t, route, caplog):
    # In AWS (pool_size=1) a second transaction would wait for the connection and then fail;
    # locally it would commit on its own. The guard must refuse it inside the route.
    caplog.set_level(logging.ERROR, "platform_common.errors")
    r = _app().post(f"/b/{t['a']}/{route}", headers={"x-debug-user": t["alice"]})
    assert r.status_code == 500
    assert "already open" in str(caplog.records[-1].exc_info[1])
    assert _count(t["owner"], t["a"]) == 0


def test_read_only_unit_of_work_uses_app_ro_and_refuses_writes(t):
    p = Principal(user_sub=t["alice"], request_id="r", business_id=t["a"], role="owner")
    with unit_of_work(p, read_only=True) as uow:
        assert uow.tx.scalar(text("select current_user")) == "app_ro"
        assert uow.tx.scalar(text("select count(*) from demo.notes")) == 0
    with pytest.raises((InternalError, ProgrammingError), match="read-only|permission denied"):
        with unit_of_work(p, read_only=True) as uow:
            uow.tx.execute(text("insert into demo.notes (tenant_id, body) values (:t, 'x')"), {"t": t["a"]})


def test_resolver_answering_for_another_business_is_a_500(t):
    uow_mod.set_principal_resolver(
        lambda tx, caller, bid, rid: Principal(user_sub=caller.user_sub, request_id=rid, business_id=t["b"], role="owner")
    )
    assert _app().get(f"/b/{t['a']}/notes", headers={"x-debug-user": t["alice"]}).status_code == 500


def test_support_principal_is_refused_until_grants_exist(t, caplog):
    caplog.set_level(logging.INFO, "platform_common.errors")
    uow_mod.set_principal_resolver(
        lambda tx, caller, bid, rid: Principal(
            user_sub=caller.user_sub, request_id=rid, business_id=bid, role=None, support_grant_id=uuid.uuid4()
        )
    )
    assert _app().get(f"/b/{t['a']}/notes", headers={"x-debug-user": t["alice"]}).status_code == 404
    assert [r.reason for r in caplog.records if getattr(r, "event", None) == "deny"] == ["support_no_grant"]


def test_no_resolver_is_a_500(t):
    uow_mod.set_principal_resolver(None)
    assert _app().get(f"/b/{t['a']}/notes", headers={"x-debug-user": t["alice"]}).status_code == 500
