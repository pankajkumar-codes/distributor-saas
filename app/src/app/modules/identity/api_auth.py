"""/api/v1/auth/* (LLD-1 §5): public routes with no JWT authorizer.

Routes open their own short transactions (service/signup.py) instead of taking a
unit of work as a dependency, because rate.hit must commit before the first one opens.
Bodies are never logged. The refresh token goes only into an HttpOnly cookie scoped to
/api/v1/auth, and any route that sets or reads it first checks Origin (§5.6).
"""

import os
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from platform_common.auth import debug_env
from platform_common.authprovider import AuthProvider
from platform_common.errors import Deny, Invalid, deny_response, request_id
from platform_common.mailer import Mailer

from .providers import auth_provider, mailer
from .service import sessions, signup

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "__Secure-rt"
COOKIE_PATH = "/api/v1/auth"
COOKIE_MAX_AGE = 30 * 24 * 3600  # auth.session_max_days
_LOCAL_ORIGIN = "http://localhost:5173"


class EmailBody(BaseModel):
    email: str = Field(max_length=254)


class VerifyBody(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=16)
    password: str = Field(max_length=1024)  # the policy's own limit gives the friendly error


def _email(raw: str) -> str:
    """Shape only: a malformed address is 422 (that reveals nothing, §5.1)."""
    email = signup.normalise(raw)
    local, _, domain = email.partition("@")
    if not local or "." not in domain or " " in email or email.count("@") != 1:
        raise Invalid("email_invalid", "enter a valid email address", field="email")
    return email


def _client_ip(request: Request) -> str:
    # API Gateway's sourceIp, through Mangum. If CloudFront is ever put in front of
    # /api, this becomes CloudFront's address and every per-IP bucket is shared by
    # all users; read CloudFront-Viewer-Address then (infra review item).
    return request.client.host if request.client else "-"


def _check_origin(request: Request) -> None:
    origin = os.environ.get("APP_ORIGIN") or (_LOCAL_ORIGIN if debug_env() else None)
    if origin is None or request.headers.get("origin") != origin:
        raise Deny("session_invalid")


@router.post("/signup", status_code=202)
def signup_request(body: EmailBody, request: Request, mail: Annotated[Mailer, Depends(mailer)]):
    signup.request_code(_email(body.email), _client_ip(request), request_id(request), mail)
    return {"status": "code_sent"}


@router.post("/signup/verify")
def signup_verify(
    body: VerifyBody,
    request: Request,
    response: Response,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
):
    _check_origin(request)
    done = signup.verify(_email(body.email), body.code, body.password, _client_ip(request), request_id(request), idp)
    response.set_cookie(
        REFRESH_COOKIE,
        done.refresh_token,
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return {
        "access_token": done.access_token,
        "expires_in": done.expires_in,
        "user": {"id": str(done.user_id), "email": done.email},
    }


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


@router.post("/refresh")
def refresh(request: Request, idp: Annotated[AuthProvider, Depends(auth_provider)]):
    try:
        _check_origin(request)
        tokens = sessions.refresh(
            request.cookies.get(REFRESH_COOKIE),
            _client_ip(request),
            request_id(request),
            idp,
            background=request.headers.get("x-background") == "1",
        )
    except Deny as e:
        failed = deny_response(request, e)
        _clear_cookie(failed)
        return failed
    # The refresh token isn't rotated (L1-5), so the cookie is left as it is.
    return {"access_token": tokens.access_token, "expires_in": tokens.expires_in}


@router.post("/signout", status_code=204)
def signout(request: Request, idp: Annotated[AuthProvider, Depends(auth_provider)]):
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth.lower().startswith("bearer ") else None
    sessions.sign_out(bearer, request.cookies.get(REFRESH_COOKIE), request_id(request), idp)
    done = Response(status_code=204)
    _clear_cookie(done)
    return done
