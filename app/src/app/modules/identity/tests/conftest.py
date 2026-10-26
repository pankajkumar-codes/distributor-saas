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
# The current pg_client database as its owner (a superuser, so RLS doesn't apply), for seeding.
PG_OWNER = {}
REPO = Path(__file__).resolve().parents[6]


def _migration_order(module_and_file):
    # migrator.handler.ordered's rule: NNNN_ files first, then by timestamp, then module.
    module, f = module_and_file
    rank = 0 if module == "platform" else 1
    return (1, f.name[:12], rank, f.name) if f.name[:12].isdigit() else (0, "", rank, f.name)


MIGRATIONS = [
    f
    for _, f in sorted(
        [("identity", f) for f in (Path(__file__).parent.parent / "migrations").glob("*.sql")]
        + [("platform", f) for f in (REPO / "libs" / "platform_common" / "migrations").glob("*.sql")],
        key=_migration_order,
    )
]
BOOTSTRAP = REPO / "migrator" / "migrator" / "bootstrap.sql"
LOCAL_ONLY = REPO / "migrator" / "local_only.sql"


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

    from app import api as app_api
    from app.modules.identity import api as main
    from app.modules.identity.models import Base

    monkeypatch.setattr(main, "engine", lambda: eng)
    main._factory.cache_clear()
    Base.metadata.create_all(eng.execution_options(schema_translate_map={"identity": None}))
    yield TestClient(app_api.app)
    main._factory.cache_clear()


def as_user(sub: str) -> dict:
    return {"x-debug-user": sub}


@pytest.fixture()
def pg_client(monkeypatch):
    """The identity API on a fresh PostgreSQL database with the real migrations, set up
    the way migrator.local does it, connected as app_rw so row-level security applies."""
    from sqlalchemy import create_engine, make_url, text

    dbname = f"t_{uuid.uuid4().hex[:10]}"
    admin = create_engine(PG_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f"create database {dbname}"))
        c.execute(text("do $$ begin if not exists (select from pg_roles where rolname='rds_iam') then create role rds_iam; end if; end $$"))
    admin_url = make_url(PG_ADMIN_URL)
    owner = create_engine(admin_url.set(database=dbname), isolation_level="AUTOCOMMIT")
    with owner.connect() as c:
        raw = c.connection.driver_connection  # psycopg, without placeholder parsing (bootstrap has %rowtype)
        for sql in [BOOTSTRAP, *MIGRATIONS, BOOTSTRAP, LOCAL_ONLY]:
            raw.execute(sql.read_text())
        c.execute(text("alter role app_rw password 'test-only'"))
    PG_OWNER["engine"] = owner
    svc = create_engine(admin_url.set(username="app_rw", password="test-only", database=dbname))

    from fastapi.testclient import TestClient

    from app import api as app_api
    from app.modules.identity import api as main

    monkeypatch.setattr(main, "engine", lambda: svc)
    monkeypatch.setattr("platform_common.db.engine", lambda: svc)
    main._factory.cache_clear()
    yield TestClient(app_api.app), svc
    main._factory.cache_clear()
    svc.dispose()
    owner.dispose()
    with admin.connect() as c:
        c.execute(text(f"drop database {dbname} with (force)"))
