"""One-time email codes for sign-up and password reset (LLD-1 L1-4, §5).

A code is 6 digits from `secrets.randbelow`, zero-padded. Only its HMAC-SHA256 is
stored; the key is per environment (Secrets Manager `auth/code-hmac` in AWS, S0b) and
separate from the rate-counter key, so a leaked backup can't be reversed by trying
all 10^6 codes. The HMAC also binds the purpose and the normalised email, so a sign-up
code can't be replayed as a reset code or for another address.

`matches` always computes one HMAC and one constant-time compare, against a dummy
when there is no stored row, so every branch of a uniform reply takes the same work.
"""

import hashlib
import hmac
import os
import secrets

from platform_common.auth import DEBUG_ENVS, platform_env

PURPOSES = frozenset({"signup", "reset"})
CODE_DIGITS = 6
_DEV_KEY = b"local-only-code-key"
_DUMMY = b"\x00" * 32


def _key() -> bytes:
    key = os.environ.get("CODE_HMAC_KEY")
    if key:
        return key.encode()
    if platform_env() in DEBUG_ENVS:
        return _DEV_KEY
    raise RuntimeError("CODE_HMAC_KEY is not set")


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def code_hmac(purpose: str, email: str, code: str) -> bytes:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown code purpose {purpose!r}")
    message = "\x00".join((purpose, email.strip().lower(), code.strip()))
    return hmac.new(_key(), message.encode(), hashlib.sha256).digest()


def matches(stored: bytes | None, purpose: str, email: str, code: str) -> bool:
    """True only when `stored` is the HMAC of this code; same work when `stored` is None."""
    candidate = code_hmac(purpose, email, code)
    ok = hmac.compare_digest(candidate, stored if stored is not None else _DUMMY)
    return ok and stored is not None
