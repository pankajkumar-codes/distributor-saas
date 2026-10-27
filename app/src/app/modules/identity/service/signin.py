"""Sign-in and its TOTP step (LLD-1 §5.3, §5.4).

  rate.hit (own tx) -> provider sign-in (password, or the TOTP answer)
  -> one tx: find the user, open the session, audit auth.signin, list memberships.

Every refusal before the provider says yes is the uniform signin_not_accepted, so the
reply never tells a wrong password from an unknown email. The TOTP challenge is the
provider's opaque session string (L1-7): it goes back to the browser, is never stored
and never logged.

The TOTP step's email goes to the provider with the challenge (Cognito's USERNAME),
which refuses a challenge that isn't that user's, so rotating the email can't dodge
the per-email limit. The step also counts against the per-IP sign-in limit, and on
success the token's user must still own that email.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import NoReturn

from sqlalchemy import text

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider, AuthRefused, AuthResult
from platform_common.errors import AppError
from platform_common.jwt_verify import TokenInvalid
from platform_common.uow import Principal, unit_of_work

from ..interface import MembershipCard, list_my_businesses, session_key_from_claims
from .sessions import open_session, revoke_at_provider, verified_claims

# Provisional limits (LLD-1 L1-10, §12); they move to refdata rows with the PO's numbers.
SIGNIN_PER_EMAIL = 10  # auth.signin_per_email_per_15min
SIGNIN_PER_IP = 100  # auth.signin_per_ip_per_hour
TOTP_PER_EMAIL = 5  # auth.totp_tries_per_email_per_15min
QUARTER_HOUR = timedelta(minutes=15)
HOUR = timedelta(hours=1)


class SigninNotAccepted(AppError):
    status = 401
    code = "signin_not_accepted"

    def __init__(self):
        super().__init__(message="the email or password is wrong")


class SigninExpired(AppError):
    status = 401
    code = "signin_expired"

    def __init__(self):
        super().__init__(message="the sign-in took too long; start again")


class TotpNotAccepted(AppError):
    status = 401
    code = "totp_not_accepted"

    def __init__(self, challenge: str):
        super().__init__(message="the code is wrong; try the current one")
        self.challenge = challenge  # the provider may hand out a new one per try

    def body(self) -> dict:
        return {**super().body(), "challenge": self.challenge}


@dataclass(frozen=True)
class TotpStep:
    challenge: str


@dataclass(frozen=True)
class SignedIn:
    user_id: uuid.UUID
    email: str
    access_token: str
    refresh_token: str
    expires_in: int
    memberships: list[MembershipCard]


def sign_in(email: str, password: str, ip: str, request_id: str, idp: AuthProvider) -> SignedIn | TotpStep:
    """§5.3. Raises SigninNotAccepted or RateLimited."""
    rate.hit(rate.bucket("signin:email", email), SIGNIN_PER_EMAIL, QUARTER_HOUR)
    rate.hit(rate.bucket("signin:ip", ip), SIGNIN_PER_IP, HOUR)
    try:
        tokens = idp.initiate_auth(email, password)
    except AuthRefused:
        raise SigninNotAccepted() from None
    if tokens.needs_totp:
        return TotpStep(tokens.challenge)
    return _finish(email, tokens, request_id, idp, totp=False)


def sign_in_totp(email: str, challenge: str, code: str, ip: str, request_id: str, idp: AuthProvider) -> SignedIn:
    """§5.4. Raises TotpNotAccepted, SigninExpired, SigninNotAccepted or RateLimited."""
    rate.hit(rate.bucket("totp:email", email), TOTP_PER_EMAIL, QUARTER_HOUR)
    rate.hit(rate.bucket("signin:ip", ip), SIGNIN_PER_IP, HOUR)
    try:
        tokens = idp.respond_totp(email, challenge, code)
    except AuthRefused as e:
        if e.code == "totp_not_accepted":
            raise TotpNotAccepted(e.challenge or challenge) from None
        raise SigninExpired() from None
    return _finish(email, tokens, request_id, idp, totp=True)


def _finish(email: str, tokens: AuthResult, request_id: str, idp: AuthProvider, *, totp: bool) -> SignedIn:
    try:
        claims = verified_claims(tokens.access_token, idp)
    except TokenInvalid:
        _refuse(tokens, idp, request_id)
    key, sub, auth_time = session_key_from_claims(claims), claims.get("sub"), claims.get("auth_time")
    if key is None or not sub or not isinstance(auth_time, (int, float)):
        _refuse(tokens, idp, request_id)
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        user = uow.tx.execute(text("select user_id, email from identity.auth_user_by_sub(:s)"), {"s": sub}).first()
        if user is not None and user.email == email:
            uow.become_user(user.user_id, sub)
            session_id = open_session(uow, user.user_id, key, auth_time)
            audit.record(uow, "auth.signin", "session", session_id, data={"totp": totp}, user_level=True)
            uow.become_read_only()  # list_my_businesses reads through app_ro policies
            memberships = list_my_businesses(uow.tx, user.user_id)
    if user is None or user.email != email:
        # A provider user with no users row (a half-finished sign-up), or a TOTP answer
        # sent under someone else's email: nothing was written, and the provider's
        # tokens are dropped.
        _refuse(tokens, idp, request_id)
    return SignedIn(user.user_id, email, tokens.access_token, tokens.refresh_token, tokens.expires_in, memberships)


def _refuse(tokens: AuthResult, idp: AuthProvider, request_id: str) -> NoReturn:
    if tokens.refresh_token:
        revoke_at_provider(tokens.refresh_token, idp, request_id)
    raise SigninNotAccepted()
