"""Fixtures for catalog's PostgreSQL tests (the business module's pattern).

The database is built by migrator.local, exactly as `make run-api` builds it, once per
session as a template; each test gets a fresh copy, connected as app_rw so row-level
security applies. Callers are named by X-Debug-User (identity.dev_ensure_session).
"""

import os

os.environ.setdefault("PLATFORM_ENV", "test")

import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

PG_ADMIN_URL = os.environ.get("PG_ADMIN_URL")
MIGRATOR = Path(__file__).resolve().parents[6] / "migrator"


@pytest.fixture(scope="session")
def template_db():
    name = f"tpl_{uuid.uuid4().hex[:10]}"
    url = make_url(PG_ADMIN_URL)
    server = create_engine(url, isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        c.execute(text(f"create database {name}"))
    dsn = url.set(drivername="postgresql", database=name).render_as_string(hide_password=False)
    subprocess.run([sys.executable, "-m", "migrator.local", dsn], cwd=MIGRATOR, check=True, capture_output=True)
    yield name
    with server.connect() as c:
        c.execute(text(f"drop database {name} with (force)"))
    server.dispose()


@pytest.fixture()
def pg(template_db):
    """(client, app_rw engine, owner engine). The owner is a superuser, for seeding and checks."""
    from fastapi.testclient import TestClient

    from app import api as app_api
    from platform_common import uow as uow_mod

    name = f"t_{uuid.uuid4().hex[:10]}"
    url = make_url(PG_ADMIN_URL)
    server = create_engine(url, isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        c.execute(text(f"create database {name} template {template_db}"))
    app_rw = create_engine(url.set(username="app_rw", password="local-only", database=name))
    owner = create_engine(url.set(database=name), isolation_level="AUTOCOMMIT")
    uow_mod.set_session_factory(sessionmaker(bind=app_rw, expire_on_commit=False))
    yield SimpleNamespace(client=TestClient(app_api.app, raise_server_exceptions=False), app_rw=app_rw, owner=owner)
    app_api.app.dependency_overrides.clear()
    uow_mod.set_session_factory(None)
    app_rw.dispose()
    owner.dispose()
    with server.connect() as c:
        c.execute(text(f"drop database {name} with (force)"))
    server.dispose()


def as_user(sub: str) -> dict:
    return {"x-debug-user": sub}


def scalar(engine, sql: str, **params):
    with engine.connect() as c:
        return c.execute(text(sql), params).scalar()


def user_id(engine, sub: str) -> uuid.UUID:
    return scalar(engine, "select id from identity.users where cognito_sub = :s", s=sub)


def ctx(c, user, tenant=None, grant=None, role=None):
    """Bind app.* the way a unit of work does, inside an open transaction `c`."""
    if role:
        c.execute(text(f"set local role {role}"))
    c.execute(
        text("select set_config('app.user_id', :u, true), set_config('app.tenant_id', :t, true),"
             " set_config('app.support_grant_id', :g, true)"),
        {"u": str(user), "t": str(tenant or ""), "g": str(grant or "")},
    )


def new_business(pg, sub: str = "alice") -> uuid.UUID:
    """A business created through POST /b, owned by `sub`."""
    body = {
        "registration": {"kind": "gstin", "gstin": "19AAPFU0939F1ZS"},
        "legal_name": "Test Traders LLP",
        "trade_name": "Test Traders",
        "address": {"line1": "1 Test Road", "city": "Kolkata", "pin": "700016", "state_code": "19"},
        "turnover_band": "up_to_threshold",
        "einvoice_history": "no",
    }
    r = pg.client.post("/api/v1/b", json=body, headers={**as_user(sub), "Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 201, r.text
    return uuid.UUID(r.json()["business_id"])


def seed_member(pg, business_id, sub: str, role: str) -> uuid.UUID:
    """A membership written as the database owner, past RLS: test setup only."""
    with pg.owner.connect() as c:
        uid = c.execute(text("select identity.dev_ensure_user(:s)"), {"s": sub}).scalar()
        c.execute(
            text("insert into identity.memberships (id, business_id, user_id, user_sub, role, status)"
                 " values (:i, :b, :u, :s, :r, 'active')"),
            {"i": uuid.uuid4(), "b": business_id, "u": uid, "s": sub, "r": role},
        )
    return uid
