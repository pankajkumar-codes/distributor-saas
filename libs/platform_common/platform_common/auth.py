"""Who is calling.

In AWS, API Gateway has already verified the Cognito JWT and passes its claims in
the Lambda event. Locally and in tests only, a bearer token is verified here against
the keys set with `set_local_verifier` (FakeAuthProvider's JWKS), producing the same
claims the authorizer would (LLD-0 §3.11). The older X-Debug-User header (and
X-Debug-Email for a verified email) still stands in for a token there. All of this is
ignored in every other environment.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from fastapi import Request

from .errors import Deny

from .jwt_verify import TokenInvalid, verify_access_token

DEBUG_ENVS = {"local", "test"}


@dataclass(frozen=True)
class Caller:
    user_sub: str
    email: str | None = None
    # Only a verified email may be used to match invitations to the caller.
    email_verified: bool = False
    # All verified token claims, e.g. origin_jti (the session key, LLD-1 L1-6) and auth_time.
    claims: Mapping = field(default_factory=dict, compare=False)

    @property
    def verified_email(self) -> str | None:
        return self.email.strip().lower() if self.email and self.email_verified else None


def platform_env() -> str:
    return os.environ.get("PLATFORM_ENV", "local")


@dataclass(frozen=True)
class _LocalVerifier:
    jwks: Mapping
    issuer: str
    client_id: str


_local_verifier: _LocalVerifier | None = None


def set_local_verifier(jwks: Mapping | None, *, issuer: str = "", client_id: str = "") -> None:
    """Local and CI only: verify bearer tokens against these keys (None turns it off)."""
    global _local_verifier
    _local_verifier = None if jwks is None else _LocalVerifier(jwks, issuer, client_id)


def current_caller(request: Request) -> Caller:
    event = request.scope.get("aws.event") or {}
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    if claims.get("sub"):
        # API Gateway passes JWT claims as strings, so the flag arrives as "true".
        verified = str(claims.get("email_verified", "")).lower() == "true"
        return Caller(user_sub=claims["sub"], email=claims.get("email"), email_verified=verified, claims=claims)

    if platform_env() in DEBUG_ENVS:
        bearer = request.headers.get("authorization", "")
        if bearer.lower().startswith("bearer ") and _local_verifier is not None:
            v = _local_verifier
            try:
                claims = verify_access_token(bearer[7:].strip(), v.jwks, issuer=v.issuer, client_id=v.client_id)
            except TokenInvalid:
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required") from None
            return Caller(user_sub=claims["sub"], claims=claims)
        debug_user = request.headers.get("x-debug-user")
        if debug_user:
            debug_email = request.headers.get("x-debug-email")
            return Caller(user_sub=debug_user, email=debug_email, email_verified=bool(debug_email))

    # 401, so the web app knows to sign in; it says nothing about any business.
    raise Deny("session_invalid")
