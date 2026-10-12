"""Needs a disposable PostgreSQL: PG_DSN=postgresql://postgres@localhost:5432/postgres"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest

from migrator.handler import migrate

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
