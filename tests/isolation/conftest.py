"""Database-level isolation checks that need the real migrations on PostgreSQL.

Skipped unless PG_DSN points at a PostgreSQL superuser connection, for example
postgresql://postgres@localhost:5432/postgres. Each run creates a fresh database,
applies every migration with the local migrator, and drops the database afterwards.
Roles are cluster-wide, so the role checks see every role on the server.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

PG_DSN = os.environ.get("PG_DSN")
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def migrated_db():
    if not PG_DSN:
        pytest.skip("PG_DSN not set; database isolation checks need PostgreSQL")
    import psycopg
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    sys.path.insert(0, str(REPO / "services" / "migrator"))
    from migrator import local

    name = f"iso_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(PG_DSN, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    params = conninfo_to_dict(PG_DSN)
    params["dbname"] = name
    dsn = make_conninfo(**params)
    try:
        local.main(dsn)
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield conn
    finally:
        with psycopg.connect(PG_DSN, autocommit=True) as admin:
            admin.execute(f'drop database if exists "{name}" with (force)')
