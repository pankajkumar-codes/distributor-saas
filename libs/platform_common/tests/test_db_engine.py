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
