"""One-time email codes for sign-up and password reset (LLD-1 L1-4, §5).

A code is 6 digits from `secrets.randbelow`, zero-padded. Only its HMAC-SHA256 is
stored; the key is per environment (Secrets Manager `auth/code-hmac` in AWS, S0b) and
separate from the rate-counter key, so a leaked backup can't be reversed by trying
all 10^6 codes. The HMAC also binds the purpose and the normalised email, so a sign-up
code can't be replayed as a reset code or for another address.

The compare happens inside identity.auth_check_code, on the locked row. Callers
compute exactly one HMAC per request whatever the branch, so a uniform reply takes
the same work in every case (LLD-1 §5).
"""

import hashlib
import hmac
import secrets

from platform_common.auth import debug_env
from platform_common.secrets import secret

PURPOSES = frozenset({"signup", "reset"})
CODE_DIGITS = 6
_DEV_KEY = b"local-only-code-key"


def _key() -> bytes:
    key = secret("CODE_HMAC_KEY")  # Parameter Store in AWS (D-040)
    if key:
        return key.encode()
    if debug_env():  # never on Lambda, even if PLATFORM_ENV wrongly says local or test
        return _DEV_KEY
    raise RuntimeError("CODE_HMAC_KEY is not set")


def new_code() -> str:
    return f"{secrets.randbelow(10**CODE_DIGITS):0{CODE_DIGITS}d}"


def code_hmac(purpose: str, email: str, code: str) -> bytes:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown code purpose {purpose!r}")
    message = "\x00".join((purpose, email.strip().lower(), code.strip()))
    return hmac.new(_key(), message.encode(), hashlib.sha256).digest()

