"""Who is calling.

In AWS, API Gateway has already verified the Cognito JWT and passes its claims in
the Lambda event. Locally and in tests only, an X-Debug-User header stands in for a
token (and X-Debug-Email for a verified email). Both headers are ignored in every
other environment.
"""

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

DEBUG_ENVS = {"local", "test"}


@dataclass(frozen=True)
class Caller:
    user_sub: str
    email: str | None = None
    # Only a verified email may be used to match invitations to the caller.
    email_verified: bool = False

    @property
    def verified_email(self) -> str | None:
        return self.email.strip().lower() if self.email and self.email_verified else None


def platform_env() -> str:
    return os.environ.get("PLATFORM_ENV", "local")


def current_caller(request: Request) -> Caller:
    event = request.scope.get("aws.event") or {}
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    if claims.get("sub"):
        # API Gateway passes JWT claims as strings, so the flag arrives as "true".
        verified = str(claims.get("email_verified", "")).lower() == "true"
        return Caller(user_sub=claims["sub"], email=claims.get("email"), email_verified=verified)

    if platform_env() in DEBUG_ENVS:
        debug_user = request.headers.get("x-debug-user")
        if debug_user:
            debug_email = request.headers.get("x-debug-email")
            return Caller(user_sub=debug_user, email=debug_email, email_verified=bool(debug_email))

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
