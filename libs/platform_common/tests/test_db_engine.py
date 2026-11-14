"""Without DATABASE_URL, the engine signs IAM tokens, and only on Lambda (D-040)."""

import pytest

from platform_common import db


def test_iam_login_is_refused_off_lambda(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    for name, value in {"DB_HOST": "db.internal", "DB_USER": "app_rw", "DB_NAME": "saas"}.items():
        monkeypatch.setenv(name, value)
    db.engine.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="Lambda only"):
            db.engine()
    finally:
        db.engine.cache_clear()


def test_only_postgresql_urls_get_a_connect_timeout():
    assert db.engine_options("postgresql+psycopg://app_rw@localhost/saas") == {"connect_args": {"connect_timeout": 5}}
    assert db.engine_options("sqlite+pysqlite:///:memory:") == {}


def test_the_engine_builds_for_sqlite_with_no_connect_arg(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    db.engine.cache_clear()
    try:
        with db.engine().connect():
            pass
    finally:
        db.engine.cache_clear()
