"""Password policy (LLD-1 L1-9, NIST SP 800-63B): 10 to 128 characters, no
character-class rules, and not one of the 10,000 most common passwords.

The list is SecLists' 10k-most-common.txt (MIT licence, Daniel Miessler), bundled as
identity/common_passwords.txt and compared case-insensitively. Cognito's pool policy
is set to the same minimum with no class rules, so the two never disagree.

The check runs before a code is looked at, so a weak password never spends a code
try (RM3-6). Fix texts are provisional product copy until the PO confirms them.
"""

from functools import cache
from pathlib import Path

from platform_common.errors import Invalid

MIN_LENGTH = 10
MAX_LENGTH = 128
_LIST = Path(__file__).resolve().parent.parent / "common_passwords.txt"


@cache
def _common() -> frozenset[str]:
    return frozenset(line.strip().lower() for line in _LIST.read_text(encoding="utf-8").splitlines() if line.strip())


def check_password(password: str) -> None:
    """Raise Invalid("password_weak") with a `fix` text, or return."""
    if len(password) < MIN_LENGTH:
        fix = f"Use at least {MIN_LENGTH} characters. A few unrelated words work well."
    elif len(password) > MAX_LENGTH:
        fix = f"Use at most {MAX_LENGTH} characters."
    elif password.lower() in _common():
        fix = "This password is too common. Choose one that is harder to guess."
    else:
        return
    raise Invalid("password_weak", "the password is too weak", field="password", fix=fix)
