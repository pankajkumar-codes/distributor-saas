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
from datetime import timedelta
from typing import NoReturn

from sqlalchemy import text

from platform_common import audit, rate
from platform_common.authprovider import AuthProvider, AuthRefused, AuthResult
from platform_common.errors import Deny
from platform_common.jwt_verify import TokenInvalid, verify_access_token
from platform_common.uow import Principal, unit_of_work

from ..interface import session_key_from_claims
from ..providers import token_issuer_and_client

log = logging.getLogger(__name__)

REFRESH_PER_IP_PER_HOUR = 600  # auth.refresh_per_ip_per_hour (provisional, L1-10)
HOUR = timedelta(hours=1)


def _claims(token: str, idp: AuthProvider, *, allow_expired: bool = False) -> dict:
    issuer, client_id = token_issuer_and_client()
    return verify_access_token(token, idp.jwks(), issuer=issuer, client_id=client_id, allow_expired=allow_expired)


def refresh(refresh_token: str | None, ip: str, request_id: str, idp: AuthProvider, *, background: bool) -> AuthResult:
    """§5.5. Raises Deny("session_invalid") or RateLimited."""
    rate.hit(rate.bucket("refresh:ip", ip), REFRESH_PER_IP_PER_HOUR, HOUR)
    if not refresh_token:
        raise Deny("session_invalid")
    try:
        tokens = idp.refresh(refresh_token)
        claims = _claims(tokens.access_token, idp)
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
    _revoke_at_provider(refresh_token, idp, request_id)
    raise Deny("session_invalid")


def _revoke_at_provider(refresh_token: str, idp: AuthProvider, request_id: str) -> None:
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
            claims = _claims(bearer, idp, allow_expired=True)
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
        _revoke_at_provider(refresh_token, idp, request_id)
