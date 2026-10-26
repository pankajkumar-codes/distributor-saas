"""Refresh and sign-out (LLD-1 §5.5, §5.7).

Refresh is cookie-only: the provider swaps the refresh token for a new access token,
we verify that token, read its session key (L1-6) and check the session row through
identity.auth_resolve with no business: not revoked, active in the last 24 h, before
its 30-day absolute expiry. Background polls (X-Background: 1, L1-8) don't move the
idle clock. Any failure is Deny("session_invalid"), and the route clears the cookie.

Sign-out never reveals anything: it revokes the session the bearer token names, even
an expired token's, and always ends in 204. The provider's refresh token is revoked
after commit.
"""

import logging
from datetime import timedelta

from sqlalchemy import text

from platform_common import rate
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
    except (AuthRefused, TokenInvalid):
        raise Deny("session_invalid") from None
    key = session_key_from_claims(claims)
    if key is None:
        raise Deny("session_invalid")
    with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
        row = uow.tx.execute(
            text("select deny from identity.auth_resolve(:kind, :value, :sub, null, :touch)"),
            {"kind": key[0], "value": key[1], "sub": claims["sub"], "touch": not background},
        ).first()
    if row is None or row.deny is not None:
        raise Deny("session_invalid")
    return tokens


def sign_out(bearer: str | None, refresh_token: str | None, request_id: str, idp: AuthProvider) -> None:
    """§5.7. Never raises for a missing or bad token."""
    key, sub = None, None
    if bearer:
        try:
            claims = _claims(bearer, idp, allow_expired=True)
            key, sub = session_key_from_claims(claims), claims["sub"]
        except TokenInvalid:
            pass
    if key is not None:
        with unit_of_work(Principal(user_sub=None, request_id=request_id)) as uow:
            uow.tx.execute(
                text("select identity.auth_revoke_session(:kind, :value, :sub, 'signout')"),
                {"kind": key[0], "value": key[1], "sub": sub},
            )
    if refresh_token:
        try:
            idp.revoke_refresh(refresh_token)
        except Exception:  # the session row is already revoked; the reply stays 204
            log.exception("revoke_refresh failed", extra={"request_id": request_id})
