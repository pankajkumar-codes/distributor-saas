"""Who is calling.

In AWS, API Gateway has already verified the Cognito JWT and passes its claims in
the Lambda event. Locally and in tests only, an X-Debug-User header stands in for a
token. That header is ignored in every other environment.
"""

import os
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

DEBUG_ENVS = {"local", "test"}


@dataclass(frozen=True)
class Principal:
    user_sub: str
    email: str | None = None


def platform_env() -> str:
    return os.environ.get("PLATFORM_ENV", "local")


def current_principal(request: Request) -> Principal:
    event = request.scope.get("aws.event") or {}
    claims = (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )
    if claims.get("sub"):
        return Principal(user_sub=claims["sub"], email=claims.get("email"))

    if platform_env() in DEBUG_ENVS:
        debug_user = request.headers.get("x-debug-user")
        if debug_user:
            return Principal(user_sub=debug_user)

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required")
