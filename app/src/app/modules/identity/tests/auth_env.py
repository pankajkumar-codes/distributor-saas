"""A fresh database built by migrator.local, with the auth routes on the fake provider
and FakeMailer, for the sign-up and session route tests (nothing real is sent)."""

import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from app.modules.identity import providers
from platform_common import uow as uow_mod
from platform_common.fake_auth import FakeAuthProvider
from platform_common.mailer import FakeMailer

from .conftest import PG_ADMIN_URL

MIGRATOR = Path(__file__).resolve().parents[6] / "migrator"
ORIGIN = {"origin": "http://localhost:5173"}
EMAIL = "asha@example.com"
PASSWORD = "correct horse battery"


@contextmanager
def auth_env():
    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin_url = make_url(PG_ADMIN_URL)
    server = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with server.connect() as c:
        c.execute(text(f"create database {dbname}"))
    dsn = admin_url.set(drivername="postgresql", database=dbname).render_as_string(hide_password=False)
    subprocess.run([sys.executable, "-m", "migrator.local", dsn], cwd=MIGRATOR, check=True, capture_output=True)
    app_rw = create_engine(admin_url.set(username="app_rw", password="local-only", database=dbname))
    admin = create_engine(admin_url.set(database=dbname))
    uow_mod.set_session_factory(sessionmaker(bind=app_rw, expire_on_commit=False))

    from app import api as app_api

    idp, mail = FakeAuthProvider(), FakeMailer()
    app_api.app.dependency_overrides[providers.auth_provider] = lambda: idp
    app_api.app.dependency_overrides[providers.mailer] = lambda: mail
    client = TestClient(app_api.app, raise_server_exceptions=False)
    yield client, idp, mail, admin
    app_api.app.dependency_overrides.clear()
    uow_mod.set_session_factory(None)
    app_rw.dispose()
    admin.dispose()
    with server.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))


def one(admin, sql, **params):
    with admin.connect() as c:
        return c.execute(text(sql), params).scalar()


def sign_up(client, mail, email=EMAIL):
    r = client.post("/api/v1/auth/signup", json={"email": email})
    assert (r.status_code, r.json()) == (202, {"status": "code_sent"})
    return last(mail)


def last(mail):
    template, to, params = mail.sent[-1]
    return SimpleNamespace(template=template, to=to, params=params)


def verify(client, code, password=PASSWORD, email=EMAIL, headers=ORIGIN):
    return client.post(
        "/api/v1/auth/signup/verify", json={"email": email, "code": code, "password": password}, headers=headers
    )
