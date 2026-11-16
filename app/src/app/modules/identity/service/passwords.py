"""Password policy (Pankaj, 16 Nov 2026; supersedes the "no character-class rules" of LLD-1 L1-9).

The rules are refdata `auth.password_*`: a length range, which of upper case, lower case, digit and special
character are needed, and the fixed set of special characters. The common-passwords list stays (SecLists'
10k-most-common.txt, MIT licence, Daniel Miessler; the notice is in identity/common_passwords.LICENSE, bundled as
identity/common_passwords.txt and compared case-insensitively). A leading or trailing space is refused rather than
stripped: Cognito refuses such passwords, and stripping would change what the user types at sign-in. Spaces inside
a password are fine and are not special characters. The app is stricter than Cognito's pool policy, so Cognito never
refuses a password the app accepted.

The check runs before a code is sent (sign-up request) or looked at (verify, reset), so a weak password never
spends a code or a code try (RM3-6). An error lists every unmet rule, not just the first. Fix texts are provisional
product copy until the PO confirms them.
"""

import time
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

from platform_common.errors import Invalid
from platform_common.uow import Principal, unit_of_work

from app.modules.refdata import value_on

_LIST = Path(__file__).resolve().parent.parent / "common_passwords.txt"
_KEYS = {
    "min_length": "auth.password_min_length",
    "max_length": "auth.password_max_length",
    "upper": "auth.password_require_upper",
    "lower": "auth.password_require_lower",
    "digit": "auth.password_require_digit",
    "special": "auth.password_require_special",
    "specials": "auth.password_specials",
}


POLICY_CACHE_SECONDS = 60
_cached: tuple[float, date, "Policy"] | None = None


@dataclass(frozen=True)
class Policy:
    min_length: int
    max_length: int
    upper: bool
    lower: bool
    digit: bool
    special: bool
    specials: str

    def rules(self) -> list[tuple[str, str]]:
        """(id, what the person is asked to do), in the order the screen lists them."""
        out = [("length", f"At least {self.min_length} characters")]
        if self.upper:
            out.append(("upper", "An uppercase letter (A to Z)"))
        if self.lower:
            out.append(("lower", "A lowercase letter (a to z)"))
        if self.digit:
            out.append(("digit", "A digit (0 to 9)"))
        if self.special:
            out.append(("special", f"A special character: {self.specials}"))
        return out


def read_policy(today: date, request_id: str) -> Policy:
    """The rules in force on `today`. Raises RefdataMissing (a 500, never a guess)."""
    with unit_of_work(Principal(user_sub=None, request_id=request_id), read_only=True) as uow:
        values = {name: value_on(uow.tx, key, today) for name, key in _KEYS.items()}
    return Policy(
        min_length=int(values["min_length"]), max_length=int(values["max_length"]), upper=bool(values["upper"]),
        lower=bool(values["lower"]), digit=bool(values["digit"]), special=bool(values["special"]),
        specials=str(values["specials"]),
    )


def cached_policy(today: date, request_id: str) -> Policy:
    """`read_policy` for the public GET, kept for POLICY_CACHE_SECONDS per process so an unauthenticated caller
    cannot turn it into a database read per request. A change in refdata shows within that time."""
    global _cached
    now = time.monotonic()
    if _cached is not None and _cached[1] == today and now - _cached[0] < POLICY_CACHE_SECONDS:
        return _cached[2]
    policy = read_policy(today, request_id)
    _cached = (now, today, policy)
    return policy


def clear_policy_cache() -> None:
    global _cached
    _cached = None


class PasswordWeak(Invalid):
    """422 password_weak. `unmet` is the ids of the rules the password breaks, for the screen to tick off."""

    def __init__(self, unmet: list[str], fix: str):
        super().__init__("password_weak", "the password is too weak", field="password", fix=fix)
        self.unmet = unmet

    def body(self) -> dict:
        body = super().body()
        body["error"]["unmet"] = self.unmet
        return body


@cache
def _common() -> frozenset[str]:
    return frozenset(line.strip().lower() for line in _LIST.read_text(encoding="utf-8").splitlines() if line.strip())


def check_password(password: str, policy: Policy, *, field: str = "password") -> None:
    """Raise PasswordWeak naming every unmet rule, or return."""
    unmet: list[str] = []
    wording: list[str] = []
    labels = dict(policy.rules())
    if len(password) < policy.min_length:
        unmet.append("length")
        wording.append(labels["length"].lower())
    for rule, found in (
        ("upper", any(c.isascii() and c.isupper() for c in password)),
        ("lower", any(c.isascii() and c.islower() for c in password)),
        ("digit", any(c.isascii() and c.isdigit() for c in password)),
        ("special", any(c in policy.specials for c in password)),
    ):
        if rule in labels and not found:
            unmet.append(rule)
            wording.append(labels[rule][0].lower() + labels[rule][1:])
    extra: list[str] = []
    if len(password) > policy.max_length:
        unmet.append("too_long")
        extra.append(f"Use at most {policy.max_length} characters.")
    if password != password.strip():
        unmet.append("edge_space")
        extra.append("Remove the spaces at the start or end. Spaces in the middle are fine.")
    if not unmet and password.lower() in _common():
        unmet.append("common")
        extra.append("This password is too common. Choose one that is harder to guess.")
    if not unmet:
        return
    fix = " ".join([("Your password needs: " + "; ".join(wording) + ".") if wording else "", *extra]).strip()
    error = PasswordWeak(unmet, fix)
    error.field = field
    raise error
