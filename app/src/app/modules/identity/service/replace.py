"""One active session per user: the answer to "One session is already active. Sign out there and continue here?".

A sign-in that finds a live session opens nothing (service/signin.py) and hands back the provider's tokens, which no
route accepts because they have no session row. The browser then asks the person and calls one of these with that
access token as the Bearer:

  replace  yes: end the live sessions ('replaced') and open this one, in one transaction under a lock on the user, so
           two sign-ins at once are decided one at a time. The sign-in must be recent (auth.session_confirm_minutes);
           a retry of the same confirmation answers the same way.
  cancel   no: the new sign-in does not complete. The provider's refresh token is revoked, nothing else changes, and
           the person's other session keeps running.

Both are public routes (no authorizer) that verify the token themselves, as sign-out does.
"""

import logging
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider
from platform_common.clock import Clock
from platform_common.errors import Deny
from platform_common.ids import uuid7
from platform_common.jwt_verify import TokenInvalid
from platform_common.uow import Principal, unit_of_work
from datetime import UTC, datetime

from ..interface import list_my_businesses, session_key_from_claims
from . import limits
from .sessions import open_session, revoke_at_provider, verified_claims
from dataclasses import dataclass
import uuid

from ..interface import MembershipCard

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class Replaced:
    user_id: uuid.UUID
    email: str
    access_token: str  # the same token, now backed by a session row
    expires_in: int
    memberships: list[MembershipCard]
    is_support: bool


def replace(bearer: str | None, ip: str, request_id: str, idp: AuthProvider, clock: Clock) -> Replaced:
    """Raises Deny("session_invalid") for a missing, bad, expired or stale token, and RateLimited."""
    lim = limits.read(("auth.signin_per_ip_per_hour", "auth.session_max_days", "auth.session_confirm_minutes"), clock.today(), request_id
    )
    rate.hit(rate.bucket("signin:ip", ip), lim["auth.signin_per_ip_per_hour"], HOUR)
    if not bearer:
        raise Deny("session_invalid")
    try:
        claims = verified_claims(bearer, idp)
    except TokenInvalid:
        raise Deny("session_invalid") from None
    key, sub, auth_time = session_key_from_claims(claims), claims.get("sub"), claims.get("auth_time")
    if key is None or not sub or not isinstance(auth_time, (int, float)):
        raise Deny("session_invalid")
    now = clock.now().timestamp()
    if now - auth_time > lim["auth.session_confirm_minutes"] * 60:
        raise Deny("session_invalid")  # an old sign-in can't be confirmed later
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        user = uow.tx.execute(text("select user_id, email from identity.auth_user_by_sub(:s)"), {"s": sub}).first()
        if user is None:
            raise Deny("session_invalid")
        uow.become_user(user.user_id, sub)
        done = uow.tx.execute(
            text("select user_id, revoked, opened from identity.auth_replace_session(:i, :s, :kind, :k, :t, :d)"),
            {
                "i": uuid7(),
                "s": sub,
                "kind": key[0],
                "k": key[1],
                "t": datetime.fromtimestamp(auth_time, UTC),
                "d": lim["auth.session_max_days"],
            },
        ).first()
        if done is None:
            raise Deny("session_invalid")
        is_support = bool(
            uow.tx.execute(text("select is_support from identity.users where id = :me"), {"me": user.user_id}).scalar()
        )
        if done.opened:
            audit.record(uow, "auth.session_replaced", "user", user.user_id, data={"sessions": done.revoked}, user_level=True)
        uow.become_read_only()
        memberships = list_my_businesses(uow.tx, user.user_id)
    # The cookie's refresh token stays: it belongs to this same sign-in.
    exp = claims.get("exp")
    left = max(int(exp - now), 0) if isinstance(exp, (int, float)) else 0
    return Replaced(user.user_id, user.email, bearer, left, memberships, is_support)


def cancel(bearer: str | None, refresh_token: str | None, request_id: str, idp: AuthProvider, clock: Clock) -> None:
    """Never raises for a missing or bad token (as sign-out): the sign-in just doesn't complete.

    The declined sign-in is written as a session row that is already ended, so the same token can't be used
    for replace afterwards (the row for its key exists and is revoked)."""
    if bearer:
        try:
            claims = verified_claims(bearer, idp, allow_expired=True)
        except TokenInvalid:
            claims = {}
        key, sub, auth_time = session_key_from_claims(claims), claims.get("sub"), claims.get("auth_time")
        if key is not None and sub and isinstance(auth_time, (int, float)):
            lim = limits.read(("auth.session_max_days",), clock.today(), request_id)
            with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
                user = uow.tx.execute(text("select user_id from identity.auth_user_by_sub(:s)"), {"s": sub}).first()
                if user is not None:
                    uow.become_user(user.user_id, sub)
                    try:
                        with uow.tx.begin_nested():  # a row for this key already exists: leave it alone
                            sid = open_session(uow, user.user_id, key, int(auth_time), lim["auth.session_max_days"])
                    except IntegrityError:
                        sid = None
                    if sid is not None:
                        uow.tx.execute(
                            text("select 1 from identity.auth_end_session(:kind, :value, :sub, 'signout')"),
                            {"kind": key[0], "value": key[1], "sub": sub},
                        ).first()
                        audit.record(uow, "auth.signin_declined", "session", sid, user_level=True)
    if refresh_token:
        revoke_at_provider(refresh_token, idp, request_id)
