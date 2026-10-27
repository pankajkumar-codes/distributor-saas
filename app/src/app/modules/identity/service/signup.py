"""Sign-up and its verify step (LLD-1 §5.1, §5.2).

Each step runs in its own short transaction, in this order, because the Lambda pool
has one connection and a counted try must survive a later failure:
  rate.hit (own tx) -> tx 1 check the code (committed whatever happens)
  -> Cognito create user + sign in -> tx 2 consume, create user, open session, audit.
A failure after tx 1 leaves the code claimed; the claim lapses after 60 s and the user
can retry while the code lasts.

Replies that say "uniform" are the same in every branch (AC-2): sign-up always
answers 202 and always computes one HMAC, and verify answers code_not_accepted for
a wrong, expired, voided, claimed or already-registered code alike.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

import jwt
from sqlalchemy import text

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider, AuthRefused
from platform_common.errors import AppError
from platform_common.ids import uuid7
from platform_common.mailer import Mailer, send_after_commit
from platform_common.uow import Principal, unit_of_work

from .. import codes
from ..interface import session_key_from_claims
from . import limits
from .passwords import check_password
from .sessions import open_session

HOUR = timedelta(hours=1)


class CodeNotAccepted(AppError):
    status = 400
    code = "code_not_accepted"

    def __init__(self):
        super().__init__(message="the code is wrong or has expired; ask for a new one")


@dataclass(frozen=True)
class CodeTerms:
    """What the screen tells the user about the code it just sent (the same for every email)."""

    ttl_minutes: int
    max_tries: int


@dataclass(frozen=True)
class SignedUp:
    user_id: uuid.UUID
    email: str
    access_token: str
    refresh_token: str
    expires_in: int


def normalise(email: str) -> str:
    return email.strip().lower()


def _public(request_id: str) -> Principal:
    return Principal(user_sub=None, request_id=request_id)


def request_code(email: str, ip: str, request_id: str, mail: Mailer, today: date) -> CodeTerms:
    """§5.1. Mails a code to a new email, or a sign-in hint to a registered one."""
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
    # The same in both branches, so the reply doesn't tell a registered email from a new one.
    terms = CodeTerms(lim["auth.code_ttl_minutes"], lim["auth.code_max_tries"])
    code = codes.new_code()
    digest = codes.code_hmac("signup", email, code)
    with unit_of_work(_public(request_id)) as uow:
        if uow.tx.execute(text("select identity.auth_user_by_email(:e)"), {"e": email}).scalar() is not None:
            # The same advisory lock auth_issue_code takes, so both branches do
            # comparable work (Staff 2, #33).
            uow.tx.execute(text("select pg_advisory_xact_lock(hashtextextended('signup:' || :e, 0))"), {"e": email})
            send_after_commit(uow, mail, "already_registered", email, {})
            return terms
        uow.tx.execute(
            text("select identity.auth_issue_code(:i, 'signup', :e, :h, :t, :m)"),
            {
                "i": uuid7(),
                "e": email,
                "h": digest,
                "t": timedelta(minutes=terms.ttl_minutes),
                "m": terms.max_tries,
            },
        )
        send_after_commit(uow, mail, "signup_code", email, {"code": code})
    return terms


def verify(email: str, code: str, password: str, ip: str, request_id: str, idp: AuthProvider, today: date) -> SignedUp:
    """§5.2. Raises Invalid("password_weak"), RateLimited or CodeNotAccepted."""
    email = normalise(email)
    check_password(password)  # before the code, so a weak password spends no try (RM3-6)
    lim = limits.read(("auth.code_checks_per_ip_per_hour", "auth.session_max_days"), today, request_id)
    rate.hit(rate.bucket("code_check:ip", ip), lim["auth.code_checks_per_ip_per_hour"], HOUR)
    digest = codes.code_hmac("signup", email, code)
    with unit_of_work(_public(request_id)) as uow:  # tx 1: committed whatever the answer
        code_id = uow.tx.execute(
            text("select identity.auth_check_code('signup', :e, :h)"), {"e": email, "h": digest}
        ).scalar()
    if code_id is None:
        raise CodeNotAccepted()

    try:
        sub = idp.create_user(email, password)
    except AuthRefused as e:
        if e.code != "user_exists":
            raise
        # An earlier verify created the Cognito user and then failed before tx 2
        # (HLD §6.1). Only reachable with a valid claimed code, which proves the caller
        # holds the inbox. An invitee whose Cognito user an invitation pre-created
        # (invites.CognitoSender) and who signs up instead of accepting comes here too,
        # by design: the code proves the same thing.
        sub = idp.get_sub(email)
        idp.set_password(sub, password)
    tokens = idp.initiate_auth(email, password)  # a new user has no TOTP yet
    # Straight from the provider over our own server call, so the claims are trusted.
    claims = jwt.decode(tokens.access_token, options={"verify_signature": False})
    key = session_key_from_claims(claims)  # the same key the resolver will look up (L1-6)
    if key is None or not isinstance(claims.get("auth_time"), (int, float)):
        raise RuntimeError("the provider's access token names no session key or auth_time")

    user_id = uuid7()
    with unit_of_work(_public(request_id)) as uow:  # tx 2
        if not uow.tx.execute(text("select identity.auth_consume_code(:c)"), {"c": code_id}).scalar():
            raise CodeNotAccepted()
        uow.tx.execute(text("select identity.auth_create_user(:i, :s, :e)"), {"i": user_id, "s": sub, "e": email})
        uow.become_user(user_id, sub)
        open_session(uow, user_id, key, claims["auth_time"], lim["auth.session_max_days"])
        audit.record(uow, "auth.signup", "user", user_id, user_level=True)
    return SignedUp(user_id, email, tokens.access_token, tokens.refresh_token, tokens.expires_in)
