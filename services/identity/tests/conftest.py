import os

os.environ["PLATFORM_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from platform_common import db

PG_ADMIN_URL = os.environ.get("PG_ADMIN_URL")
MIGRATIONS = sorted((Path(__file__).parent.parent / "migrations").glob("*.sql"))


@pytest.fixture()
def client(monkeypatch):
    from sqlalchemy import create_engine

    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.engine.cache_clear()
    monkeypatch.setattr(db, "engine", lambda: eng)

    from app import main
    from app.models import Base

    monkeypatch.setattr(main, "engine", lambda: eng)
    main._factory.cache_clear()
    Base.metadata.create_all(eng.execution_options(schema_translate_map={"identity": None}))
    yield TestClient(main.app)
    main._factory.cache_clear()


def as_user(sub: str) -> dict:
    return {"x-debug-user": sub}


@pytest.fixture()
def pg_client(monkeypatch):
    """The identity API on a fresh PostgreSQL database with the real migrations,
    connected as svc_identity so row-level security applies."""
    from sqlalchemy import create_engine, make_url, text

    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    admin_url = make_url(PG_ADMIN_URL)
    owner = create_engine(admin_url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        for m in MIGRATIONS:
            c.exec_driver_sql(m.read_text())
        c.execute(text("alter role svc_identity password 'test-only'"))
    svc = create_engine(admin_url.set(username="svc_identity", password="test-only", database=dbname))

    from fastapi.testclient import TestClient

    from app import main

    monkeypatch.setattr(main, "engine", lambda: svc)
    monkeypatch.setattr("platform_common.db.engine", lambda: svc)
    main._factory.cache_clear()
    yield TestClient(main.app), svc
    main._factory.cache_clear()
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))
