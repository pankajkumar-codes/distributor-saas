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


def test_the_url_branch_passes_connect_timeout_and_the_iam_branch_does_not(monkeypatch):
    seen = []
    real = db.create_engine
    monkeypatch.setattr(db, "create_engine", lambda url, **kw: (seen.append((str(url), kw)), real(url, **kw))[1])
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://app_rw:x@localhost:5432/saas")
    db.engine.cache_clear()
    try:
        db.engine()
        monkeypatch.delenv("DATABASE_URL")
        monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "api")
        for name, value in {"DB_HOST": "db.internal", "DB_USER": "app_rw", "DB_NAME": "saas"}.items():
            monkeypatch.setenv(name, value)
        db.engine.cache_clear()
        db.engine()
    finally:
        db.engine.cache_clear()
    (_, url_kwargs), (_, iam_kwargs) = seen
    assert url_kwargs["connect_args"] == {"connect_timeout": 5}
    assert "connect_timeout" not in iam_kwargs["connect_args"]
