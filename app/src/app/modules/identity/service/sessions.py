"""Refresh and sign-out (LLD-1 §5.5, §5.7).

Refresh is cookie-only: the provider swaps the refresh token for a new access token,
we verify that token, read its session key (L1-6) and check the session row through
identity.auth_resolve with no business: not revoked, active in the last 24 h, before
its 30-day absolute expiry. Background polls (X-Background: 1, L1-8) don't move the
idle clock. Any failure is Deny("session_invalid"), and the route clears the cookie.

When the session check refuses a token the provider accepted, the provider's refresh
token is revoked too (best effort), so it can't be replayed against the provider.

Sign-out never reveals anything: it revokes the session the bearer token names, even
an expired token's, writes auth.signout in the same transaction, and always ends in
204. The provider's refresh token is revoked after commit.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import NoReturn

from sqlalchemy import text

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider, AuthRefused, AuthResult
from platform_common.errors import Deny
from platform_common.ids import uuid7
from platform_common.jwt_verify import TokenInvalid, verify_access_token
from platform_common.uow import Principal, unit_of_work

from ..interface import session_key_from_claims
from ..providers import token_issuer_and_client
from . import limits

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)


def open_session(uow, user_id: uuid.UUID, key: tuple[str, str], auth_time: int, max_days: int) -> uuid.UUID:
    """§5.6: the session row for a new sign-up or sign-in, keyed as the resolver looks it up."""
    session_id = uuid7()
    uow.tx.execute(
        text("select identity.auth_open_session(:i, :u, :kind, :k, :t, :d)"),
        {
            "i": session_id,
            "u": user_id,
            "kind": key[0],
            "k": key[1],
            "t": datetime.fromtimestamp(auth_time, UTC),
            "d": max_days,
        },
    )
    return session_id


def verified_claims(token: str, idp: AuthProvider, *, allow_expired: bool = False) -> dict:
    issuer, client_id = token_issuer_and_client()
    return verify_access_token(token, idp.jwks(), issuer=issuer, client_id=client_id, allow_expired=allow_expired)


def refresh(
    refresh_token: str | None, ip: str, request_id: str, idp: AuthProvider, today: date, *, background: bool
) -> AuthResult:
    """§5.5. Raises Deny("session_invalid") or RateLimited."""
    per_ip = limits.read(("auth.refresh_per_ip_per_hour",), today, request_id)["auth.refresh_per_ip_per_hour"]
    rate.hit(rate.bucket("refresh:ip", ip), per_ip, HOUR)
    if not refresh_token:
        raise Deny("session_invalid")
    try:
        tokens = idp.refresh(refresh_token)
        claims = verified_claims(tokens.access_token, idp)
    except AuthRefused:
        raise Deny("session_invalid") from None
    except TokenInvalid:
        _refuse(refresh_token, idp, request_id)
    key, sub = session_key_from_claims(claims), claims.get("sub")
    if key is None or not sub:
        _refuse(refresh_token, idp, request_id)
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        row = uow.tx.execute(
            text("select deny from identity.auth_resolve(:kind, :value, :sub, null, :touch)"),
            {"kind": key[0], "value": key[1], "sub": sub, "touch": not background},
        ).first()
    if row is None or row.deny is not None:
        _refuse(refresh_token, idp, request_id)
    return tokens


def _refuse(refresh_token: str, idp: AuthProvider, request_id: str) -> NoReturn:
    """The provider accepted a refresh token our session check refuses: revoke it there."""
    revoke_at_provider(refresh_token, idp, request_id)
    raise Deny("session_invalid")


def revoke_at_provider(refresh_token: str, idp: AuthProvider, request_id: str) -> None:
    try:
        idp.revoke_refresh(refresh_token)
    except Exception:  # best effort: the session row already decides, and the reply doesn't change
        log.exception("revoke_refresh failed", extra={"request_id": request_id})


def sign_out(bearer: str | None, refresh_token: str | None, request_id: str, idp: AuthProvider) -> None:
    """§5.7. Never raises for a missing or bad token.

    §5.7 sends the cookie and the Authorization header. With the cookie alone the
    session row isn't known, so only the provider's refresh token is revoked and the
    row ends at its 24 h idle limit.
    """
    key, sub = None, None
    if bearer:
        try:
            claims = verified_claims(bearer, idp, allow_expired=True)
            key, sub = session_key_from_claims(claims), claims.get("sub")
        except TokenInvalid:
            pass
    if key is not None and sub:
        with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
            ended = uow.tx.execute(
                text("select session_id, user_id from identity.auth_end_session(:kind, :value, :sub, 'signout')"),
                {"kind": key[0], "value": key[1], "sub": sub},
            ).first()
            if ended is not None:
                uow.become_user(ended.user_id, sub)
                audit.record(uow, "auth.signout", "session", ended.session_id, user_level=True)
    if refresh_token:
        revoke_at_provider(refresh_token, idp, request_id)


def revoke_all(uow, idp: AuthProvider) -> int:
    """§5.7 sign out everywhere, on the caller's me_uow: every live session row of the
    user, audit auth.signout_all, and the provider's global sign-out after commit.
    Returns how many rows were revoked (this request's own session included)."""
    sub = uow.principal.user_sub
    done = uow.tx.execute(
        text("select user_id, revoked from identity.auth_revoke_user_sessions(:s, 'signout_all')"), {"s": sub}
    ).one()
    audit.record(uow, "auth.signout_all", "user", done.user_id, data={"sessions": done.revoked}, user_level=True)
    uow.after_commit(lambda: idp.global_sign_out(sub))  # a failure is logged; the rows are revoked
    return done.revoked
