"""uuid7 and rate bucket keys; no database."""

import time
import uuid

import pytest

from platform_common import rate
from platform_common.ids import uuid7


def test_uuid7_is_version_7_rfc_variant_and_time_ordered():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7 and first.variant == uuid.RFC_4122
    assert first < second
    assert abs((first.int >> 80) - time.time_ns() // 1_000_000) < 5_000


def test_bucket_normalises_and_hides_the_value(monkeypatch):
    monkeypatch.setenv("PLATFORM_ENV", "test")
    monkeypatch.delenv("RATE_HMAC_KEY", raising=False)
    key = rate.bucket("code_request:email", " Asha@Example.com ")
    assert key == rate.bucket("code_request:email", "asha@example.com")
    assert key.startswith("code_request:email:") and "asha" not in key
    monkeypatch.setenv("RATE_HMAC_KEY", "another key")
    assert rate.bucket("code_request:email", "asha@example.com") != key


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_bucket_needs_a_real_key_outside_local_and_test(monkeypatch, env):
    monkeypatch.setenv("PLATFORM_ENV", env)
    monkeypatch.delenv("RATE_HMAC_KEY", raising=False)
    with pytest.raises(RuntimeError):
        rate.bucket("x", "y")


@pytest.mark.parametrize("env", [None, "local", "test"])
def test_bucket_never_uses_the_dev_key_on_lambda(monkeypatch, env):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "saas-staging-api")
    monkeypatch.delenv("RATE_HMAC_KEY", raising=False)
    if env is None:
        monkeypatch.delenv("PLATFORM_ENV", raising=False)
    else:
        monkeypatch.setenv("PLATFORM_ENV", env)
    with pytest.raises(RuntimeError):
        rate.bucket("x", "y")


def test_bucket_needs_a_real_key_when_platform_env_is_unset(monkeypatch):
    monkeypatch.delenv("PLATFORM_ENV", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.delenv("RATE_HMAC_KEY", raising=False)
    with pytest.raises(RuntimeError, match="RATE_HMAC_KEY"):
        rate.bucket("x", "y")
