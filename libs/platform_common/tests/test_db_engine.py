"""Without DATABASE_URL, the engine signs IAM tokens, and only on Lambda (D-040)."""

import sys
import types

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


def test_only_postgresql_urls_get_the_dead_connection_guards():
    """A pooled connection that went dead silently (a sleeping laptop, a paused Docker network) must fail within seconds
    and be replaced, not hang a request until the operating system gives up."""
    opts = db.engine_options("postgresql+psycopg://app_rw@localhost/saas")
    assert opts["connect_args"]["connect_timeout"] == 5
    assert opts["connect_args"]["tcp_user_timeout"] == 5000 and opts["connect_args"]["keepalives"] == 1
    assert opts["pool_pre_ping"] is True and opts["pool_recycle"] == 300
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
    # boto3 is not installed in this package's own CI job: a stand-in is enough, nothing is signed or sent.
    fake_boto3 = types.SimpleNamespace(client=lambda *_a, **_k: types.SimpleNamespace(generate_db_auth_token=lambda *a: "t"))
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
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
    assert url_kwargs["connect_args"]["connect_timeout"] == 5 and url_kwargs["connect_args"]["tcp_user_timeout"] == 5000
    assert "connect_timeout" not in iam_kwargs["connect_args"] and "tcp_user_timeout" not in iam_kwargs["connect_args"]
    assert iam_kwargs["pool_size"] == 1 and iam_kwargs["pool_pre_ping"] is True  # the Lambda engine is left as it was
