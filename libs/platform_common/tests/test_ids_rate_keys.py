"""uuid7 and rate bucket keys; no database."""

import time
import uuid

import pytest

from platform_common import rate
from platform_common.ids import uuid7


@pytest.fixture(autouse=True)
def _fresh_uuid7_state():
    """The tests below move a fake clock; none may leave `ids._last` in the future for the next test."""
    from platform_common import ids

    ids._last = (0, 0)
    yield
    ids._last = (0, 0)


def test_uuid7_is_version_7_rfc_variant_and_time_ordered():
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7 and first.variant == uuid.RFC_4122
    assert first < second
    assert abs((first.int >> 80) - time.time_ns() // 1_000_000) < 5_000


def test_uuid7_is_strictly_increasing_inside_one_millisecond(monkeypatch):
    from platform_common import ids

    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_800_000_000_000_000_000)  # the clock does not move at all
    same_ms = [uuid7() for _ in range(5000)]
    assert same_ms == sorted(same_ms) and len(set(same_ms)) == 5000
    assert all(u.version == 7 and u.variant == uuid.RFC_4122 for u in same_ms)
    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_700_000_000_000_000_000)  # the clock steps back
    assert uuid7() > same_ms[-1]


def test_uuid7_is_unique_across_threads_and_increasing_within_each():
    from concurrent.futures import ThreadPoolExecutor

    def mint(_):
        return [uuid7() for _ in range(2000)]

    with ThreadPoolExecutor(4) as ex:
        runs = list(ex.map(mint, range(4)))
    assert all(r == sorted(r) for r in runs)  # each thread sees its own ids rise
    assert len({u for r in runs for u in r}) == 8000  # and no two threads got the same id


def test_uuid7_rolls_into_the_next_millisecond_when_the_random_part_is_used_up(monkeypatch):
    from platform_common import ids

    monkeypatch.setattr(ids.time, "time_ns", lambda: 1_800_000_000_000_000_000)
    ms = 1_800_000_000_000
    monkeypatch.setattr(ids, "_last", (ms, (1 << ids._RANDOM_BITS) - 1))
    nxt = uuid7()
    assert nxt.int >> 80 == ms + 1 and nxt.version == 7


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
