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
from datetime import UTC, datetime, timedelta

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
from .passwords import check_password

# Provisional limits (LLD-1 L1-10, §12); they move to refdata rows when refdata lands.
CODE_TTL = timedelta(minutes=10)  # auth.code_ttl_minutes
CODE_MAX_TRIES = 5  # auth.code_max_tries
CODE_REQUESTS_PER_EMAIL_PER_HOUR = 5
CODE_REQUESTS_PER_IP_PER_HOUR = 20
CODE_CHECKS_PER_IP_PER_HOUR = 50
SESSION_MAX_DAYS = 30  # auth.session_max_days (BRD)
HOUR = timedelta(hours=1)


class CodeNotAccepted(AppError):
    status = 400
    code = "code_not_accepted"

    def __init__(self):
        super().__init__(message="the code is wrong or has expired; ask for a new one")


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


def request_code(email: str, ip: str, request_id: str, mail: Mailer) -> None:
    """§5.1. Mails a code to a new email, or a sign-in hint to a registered one."""
    email = normalise(email)
    rate.hit(rate.bucket("code_request:email", email), CODE_REQUESTS_PER_EMAIL_PER_HOUR, HOUR)
    rate.hit(rate.bucket("code_request:ip", ip), CODE_REQUESTS_PER_IP_PER_HOUR, HOUR)
    code = codes.new_code()
    digest = codes.code_hmac("signup", email, code)
    with unit_of_work(_public(request_id)) as uow:
        if uow.tx.execute(text("select identity.auth_user_by_email(:e)"), {"e": email}).scalar() is not None:
            send_after_commit(uow, mail, "already_registered", email, {})
            return
        uow.tx.execute(
            text("select identity.auth_issue_code(:i, 'signup', :e, :h, :t, :m)"),
            {"i": uuid7(), "e": email, "h": digest, "t": CODE_TTL, "m": CODE_MAX_TRIES},
        )
        send_after_commit(uow, mail, "signup_code", email, {"code": code})


def verify(email: str, code: str, password: str, ip: str, request_id: str, idp: AuthProvider) -> SignedUp:
    """§5.2. Raises Invalid("password_weak"), RateLimited or CodeNotAccepted."""
    email = normalise(email)
    check_password(password)  # before the code, so a weak password spends no try (RM3-6)
    rate.hit(rate.bucket("code_check:ip", ip), CODE_CHECKS_PER_IP_PER_HOUR, HOUR)
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
        # (HLD §6.1). Only reachable with a valid claimed code.
        sub = idp.get_sub(email)
        idp.set_password(sub, password)
    tokens = idp.initiate_auth(email, password)  # a new user has no TOTP yet
    # Straight from the provider over our own server call, so the claims are trusted.
    claims = jwt.decode(tokens.access_token, options={"verify_signature": False})
    key = session_key_from_claims(claims)  # the same key the resolver will look up (L1-6)
    if key is None:
        raise RuntimeError("the provider's access token names no session key")

    user_id = uuid7()
    with unit_of_work(_public(request_id)) as uow:  # tx 2
        if not uow.tx.execute(text("select identity.auth_consume_code(:c)"), {"c": code_id}).scalar():
            raise CodeNotAccepted()
        uow.tx.execute(text("select identity.auth_create_user(:i, :s, :e)"), {"i": user_id, "s": sub, "e": email})
        uow.become_user(user_id, sub)
        uow.tx.execute(
            text("select identity.auth_open_session(:i, :u, :kind, :k, :t, :d)"),
            {
                "i": uuid7(),
                "u": user_id,
                "kind": key[0],
                "k": key[1],
                "t": datetime.fromtimestamp(claims["auth_time"], UTC),
                "d": SESSION_MAX_DAYS,
            },
        )
        audit.record(uow, "auth.signup", "user", user_id, user_level=True)
    return SignedUp(user_id, email, tokens.access_token, tokens.refresh_token, tokens.expires_in)
