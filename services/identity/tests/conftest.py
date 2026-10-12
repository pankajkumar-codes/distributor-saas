import os

os.environ["PLATFORM_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from platform_common import db


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
