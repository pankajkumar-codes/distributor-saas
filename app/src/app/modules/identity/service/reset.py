"""Password reset (LLD-1 §5.8).

The same shape as sign-up (service/signup.py): rate.hit, then short transactions.
  request: rate.hit (the per-email bucket is shared with sign-up) -> one tx: a code
           for a registered email, nothing for an unknown one; the reply is the same.
  verify:  policy check -> rate.hit -> tx 1 check the code (committed whatever happens)
           -> provider set_password -> tx 2 consume, revoke every session, audit
           -> after commit: provider global sign-out, mail password_changed.
The user then signs in, so a TOTP challenge still applies.
"""

from datetime import date, timedelta

from sqlalchemy import text

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider
from platform_common.ids import uuid7
from platform_common.mailer import Mailer, send_after_commit
from platform_common.uow import Principal, unit_of_work

from .. import codes
from . import limits
from .passwords import check_password
from .signup import HOUR, CodeNotAccepted, CodeTerms, normalise


def _public(request_id: str) -> Principal:
    return Principal(user_sub=None, request_id=request_id)


def request_reset(email: str, ip: str, request_id: str, mail: Mailer, today: date) -> CodeTerms:
    """§5.8. Mails a reset code to a registered email; an unknown one gets nothing."""
    email = normalise(email)
    lim = limits.read(
        (
            "auth.code_requests_per_email_per_hour",
            "auth.code_requests_per_ip_per_hour",
            "auth.code_ttl_minutes",
            "auth.code_max_tries",
        ),
        today,
        request_id,
    )
    rate.hit(rate.bucket("code_request:email", email), lim["auth.code_requests_per_email_per_hour"], HOUR)
    rate.hit(rate.bucket("code_request:ip", ip), lim["auth.code_requests_per_ip_per_hour"], HOUR)
    terms = CodeTerms(lim["auth.code_ttl_minutes"], lim["auth.code_max_tries"])
    code = codes.new_code()
    digest = codes.code_hmac("reset", email, code)
    with unit_of_work(_public(request_id)) as uow:
        if uow.tx.execute(text("select identity.auth_user_by_email(:e)"), {"e": email}).scalar() is None:
            # The lock auth_issue_code takes, so both branches do comparable work.
            uow.tx.execute(text("select pg_advisory_xact_lock(hashtextextended('reset:' || :e, 0))"), {"e": email})
            return terms
        uow.tx.execute(
            text("select identity.auth_issue_code(:i, 'reset', :e, :h, :t, :m)"),
            {"i": uuid7(), "e": email, "h": digest, "t": timedelta(minutes=terms.ttl_minutes), "m": terms.max_tries},
        )
        send_after_commit(uow, mail, "reset_code", email, {"code": code})
    return terms


def verify_reset(
    email: str, code: str, new_password: str, ip: str, request_id: str, idp: AuthProvider, mail: Mailer, today: date
) -> None:
    """§5.8. Raises Invalid("password_weak"), RateLimited or CodeNotAccepted."""
    email = normalise(email)
    check_password(new_password)  # before the code, so a weak password spends no try
    per_ip = limits.read(("auth.code_checks_per_ip_per_hour",), today, request_id)["auth.code_checks_per_ip_per_hour"]
    rate.hit(rate.bucket("code_check:ip", ip), per_ip, HOUR)
    digest = codes.code_hmac("reset", email, code)
    with unit_of_work(_public(request_id)) as uow:  # tx 1: committed whatever the answer
        code_id = uow.tx.execute(
            text("select identity.auth_check_code('reset', :e, :h)"), {"e": email, "h": digest}
        ).scalar()
    if code_id is None:  # wrong, expired, voided, claimed, or no account for this email
        raise CodeNotAccepted()

    sub = idp.get_sub(email)
    if sub is None:  # a users row with no provider user: nothing to set a password on
        raise CodeNotAccepted()
    idp.set_password(sub, new_password)

    with unit_of_work(_public(request_id)) as uow:  # tx 2
        if not uow.tx.execute(text("select identity.auth_consume_code(:c)"), {"c": code_id}).scalar():
            raise CodeNotAccepted()
        user = uow.tx.execute(
            text("select user_id, revoked from identity.auth_revoke_user_sessions(:s, 'password_reset')"), {"s": sub}
        ).first()
        if user is None:
            raise CodeNotAccepted()
        uow.become_user(user.user_id, sub)
        audit.record(uow, "auth.password_reset", "user", user.user_id, user_level=True)
        uow.after_commit(lambda: idp.global_sign_out(sub))  # a failure is logged; the rows are revoked
        send_after_commit(uow, mail, "password_changed", email, {})
