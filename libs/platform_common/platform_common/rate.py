"""Rate counters (LLD-0 §3.9).

`hit` counts one try in its own short transaction and commits it before the request's
unit of work opens, so a counted try survives the request rolling back (RM3-5: wrong
code tries count even when the request fails). It must be called while no unit of work
is open: the Lambda pool has one connection, so a second transaction would wait for it.

Windows are fixed (aligned to the epoch). Bucket keys are HMACs of the normalised value
with a key that is not in the database, so `platform.rate_counters` holds no email or IP.
Limits come from refdata, not code; callers pass them in.
"""

import hashlib
import hmac
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from .auth import debug_env
from .secrets import secret
from .clock import Clock
from .errors import RateLimited

_DEV_KEY = b"local-only-rate-key"
_HIT = text(
    "insert into platform.rate_counters (bucket, window_start, count) values (:b, :w, 1)"
    " on conflict (bucket, window_start) do update set count = platform.rate_counters.count + 1"
    " returning count"
)


def _key() -> bytes:
    key = secret("RATE_HMAC_KEY")  # Parameter Store in AWS (D-040)
    if key:
        return key.encode()
    if debug_env():  # never on Lambda, even if PLATFORM_ENV wrongly says local or test
        return _DEV_KEY
    raise RuntimeError("RATE_HMAC_KEY is not set")


def bucket(kind: str, value: str) -> str:
    """E.g. bucket("code_request:email", " Asha@Example.com") -> "code_request:email:<hmac>"."""
    digest = hmac.new(_key(), value.strip().lower().encode(), hashlib.sha256).hexdigest()
    return f"{kind}:{digest}"


def hit(bucket_key: str, limit: int, window: timedelta, *, clock: Clock | None = None, factory=None) -> None:
    """Count one try; raise RateLimited (429 with Retry-After) once `limit` is passed."""
    from . import uow as _uow

    if _uow.is_open():
        raise RuntimeError("rate.hit must run before the unit of work opens")
    now = (clock or Clock()).now()
    seconds = int(window.total_seconds())
    start = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, UTC)
    with (factory or _uow.session_factory())() as s, s.begin():
        count = s.execute(_HIT, {"b": bucket_key, "w": start}).scalar_one()
    if count > limit:
        raise RateLimited(retry_after=max(1, math.ceil((start + window - now).total_seconds())))
