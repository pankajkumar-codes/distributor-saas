"""TOTP recovery by support (LLD-2 §6.3, L2-6, TD-4a; AC2-11).

A user who lost their authenticator contacts support. Support starts a recovery for the
account's email; we mail a code to that address only; the user reads it to support;
support enters it, and the account's TOTP is removed. The code never reaches support
except from the user, so a phone call alone can't take an account over.

Neither route can take me_uow as a dependency, because rate.hit must commit before the
first unit of work opens (as in service/account.py):
  start:   tx A resolve the caller, who must be support with TOTP on (else 404)
           -> rate.hit per support user and per email -> tx B: a code only for a
           non-support account with TOTP on, mail totp_recovery_code after commit.
           The reply is the same whatever the email.
  confirm: tx A as start -> rate.hit per IP -> tx 1 check the code (committed whatever
           the answer: 5 tries, 10 minutes, claim) and its account (not support, not
           the caller, and the provider's sub for the email is that account's)
           -> provider removes the account's
           TOTP -> tx 2 identity.auth_totp_recovery_complete: consume the code, clear
           totp_enabled_at, revoke every session ('support'), audit row
           auth.totp_removed_by_support -> after commit: provider global sign-out, mail
           totp_off_by_support.
If the provider call fails, the code stays claimed and unconsumed; after the 60-second
claim support may enter it again. If tx 2 fails after the provider succeeded, the same
retry works: removing TOTP at the provider twice is harmless (S1-c4c2 to confirm for
Cognito), and the function finishes even when the flag is already clear.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import text

from platform_common import rate
from platform_common.auth import Caller
from platform_common.authprovider import AuthProvider, AuthRefused
from platform_common.errors import Deny, RateLimited
from platform_common.ids import uuid7
from platform_common.mailer import Mailer, send_after_commit
from platform_common.uow import Principal, unit_of_work

from .. import codes
from ..interface import resolve_principal
from . import limits
from .signup import HOUR, CodeNotAccepted, CodeTerms, normalise

DAY = timedelta(days=1)


def _support_caller(caller: Caller, request_id: str) -> Principal:
    """The signed-in caller if they are support with TOTP on. Anyone else gets 404: the
    routes don't exist for them (LLD-2 §6.3)."""
    with unit_of_work(Principal(user_sub=caller.user_sub, request_id=request_id)) as uow:
        me = resolve_principal(uow.tx, caller, None, request_id)
        uow.become_user(me.user_id, me.user_sub)
        ok = uow.tx.execute(
            text("select is_support and totp_enabled_at is not null from identity.users where id = :me"),
            {"me": me.user_id},
        ).scalar()
    if not ok:
        raise Deny("not_found")
    return me


def start(caller: Caller, email: str, request_id: str, mail: Mailer, today: date) -> CodeTerms:
    """Step 1. Raises Deny (404) for a non-support caller, or RateLimited."""
    me = _support_caller(caller, request_id)
    email = normalise(email)
    lim = limits.read(
        (
            "support.totp_recovery_per_support_user_per_hour",
            "support.totp_recovery_per_email_per_day",
            "auth.code_ttl_minutes",
            "auth.code_max_tries",
        ),
        today,
        request_id,
    )
    rate.hit(
        rate.bucket("totp_recovery:support", str(me.user_id)),
        lim["support.totp_recovery_per_support_user_per_hour"],
        HOUR,
    )
    rate.hit(rate.bucket("totp_recovery:email", email), lim["support.totp_recovery_per_email_per_day"], DAY)
    terms = CodeTerms(lim["auth.code_ttl_minutes"], lim["auth.code_max_tries"])
    code = codes.new_code()
    digest = codes.code_hmac("totp_recovery", email, code)  # one HMAC whichever branch
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        uow.become_user(me.user_id, me.user_sub)
        issued = uow.tx.execute(
            text("select identity.auth_issue_totp_recovery_code(:i, :e, :h, :t, :m)"),
            {"i": uuid7(), "e": email, "h": digest, "t": timedelta(minutes=terms.ttl_minutes), "m": terms.max_tries},
        ).scalar()
        if issued:
            send_after_commit(uow, mail, "totp_recovery_code", email, {"code": code})
    return terms


def confirm(
    caller: Caller, email: str, code: str, ip: str, request_id: str, idp: AuthProvider, mail: Mailer, today: date
) -> uuid.UUID:
    """Step 3. Returns the account's user ID. Raises Deny (404), RateLimited or
    CodeNotAccepted."""
    me = _support_caller(caller, request_id)
    email = normalise(email)
    per_ip = limits.read(("auth.code_checks_per_ip_per_hour",), today, request_id)["auth.code_checks_per_ip_per_hour"]
    rate.hit(rate.bucket("code_check:ip", ip), per_ip, HOUR)
    digest = codes.code_hmac("totp_recovery", email, code)
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:  # tx 1: committed whatever the answer
        uow.become_user(me.user_id, me.user_sub)
        code_id = uow.tx.execute(
            text("select identity.auth_check_code('totp_recovery', :e, :h)"), {"e": email, "h": digest}
        ).scalar()
        # Who the code is for, checked before the provider is touched: not support, not
        # the caller (tx 2 checks again, as the last guard).
        target = (
            None
            if code_id is None
            else uow.tx.execute(text("select identity.auth_totp_recovery_target(:c)"), {"c": code_id}).scalar()
        )
    if target is None:  # wrong, expired, voided, claimed, no account, or one support can't touch
        raise CodeNotAccepted()

    try:
        sub = idp.get_sub(email)
        if sub is None or sub != target:  # the provider's user isn't the account the code was sent for
            raise CodeNotAccepted()
        idp.remove_totp(sub)
    except AuthRefused as e:  # the code stays claimed, so support may enter it again after 60 s
        if e.code == "rate_limited":
            raise RateLimited(retry_after=60) from None
        raise RuntimeError(f"support_totp: unexpected provider refusal {e.code}") from None  # a 500, never a guess

    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:  # tx 2
        uow.become_user(me.user_id, me.user_sub)
        account = uow.tx.execute(
            text("select user_id, email from identity.auth_totp_recovery_complete(:c, :s, :a)"),
            {"c": code_id, "s": sub, "a": uuid7()},
        ).first()
        if account is None:  # the account changed since the code was sent (or is support)
            raise CodeNotAccepted()
        uow.after_commit(lambda: idp.global_sign_out(sub))  # a failure is logged; the rows are revoked
        send_after_commit(uow, mail, "totp_off_by_support", account.email, {})
    return account.user_id
