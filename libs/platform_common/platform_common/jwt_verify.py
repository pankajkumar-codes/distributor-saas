"""Verifying access tokens ourselves (LLD-1 §7.3).

API Gateway verifies tokens on authorized routes. The API verifies them itself on
/auth/refresh, /auth/signout and the sign-in replies, and the local/CI middleware uses
this for every request so tests see what the authorizer would pass on.
"""

from collections.abc import Mapping

import jwt


class TokenInvalid(Exception):
    pass


def verify_access_token(
    token: str,
    jwks: Mapping,
    *,
    issuer: str,
    client_id: str,
    allow_expired: bool = False,
) -> dict:
    """Return the claims of a valid access token, or raise TokenInvalid.

    Checks the signature against `jwks` (RS256 only), the issuer, `token_use` and
    `client_id` (Cognito access tokens carry no `aud`). `allow_expired` skips only
    the expiry check, for sign-out after a long idle; the caller then checks the
    session's absolute expiry.
    """
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.PyJWTError as e:
        raise TokenInvalid("malformed") from e
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key is None:
        raise TokenInvalid("unknown_kid")
    try:
        claims = jwt.decode(
            token,
            jwt.PyJWK(dict(key)).key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False, "verify_exp": not allow_expired, "require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise TokenInvalid(type(e).__name__) from e
    if claims.get("token_use") != "access" or claims.get("client_id") != client_id:
        raise TokenInvalid("wrong_token")
    return claims
