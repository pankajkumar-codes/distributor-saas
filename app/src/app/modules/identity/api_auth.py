"""/api/v1/auth/* (LLD-1 §5): public routes with no JWT authorizer.

Routes open their own short transactions (service/signup.py) instead of taking a
unit of work as a dependency, because rate.hit must commit before the first one opens.
Bodies are never logged. The refresh token goes only into an HttpOnly cookie scoped to
/api/v1/auth, and any route that sets or reads it first checks Origin (§5.6).
"""

import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from platform_common.auth import debug_env
from platform_common.authprovider import AuthProvider
from platform_common.clock import Clock, get_clock
from platform_common.errors import Deny, Invalid, deny_response, request_id
from platform_common.mailer import Mailer

from .providers import auth_provider, mailer
from .service import reset, sessions, signin, signup

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "__Secure-rt"
COOKIE_PATH = "/api/v1/auth"
COOKIE_MAX_AGE = 30 * 24 * 3600  # matches auth.session_max_days (30, BRD); the row ends the session itself
_LOCAL_ORIGIN = "http://localhost:5173"


class EmailBody(BaseModel):
    email: str = Field(max_length=254)


class VerifyBody(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=16)
    password: str = Field(max_length=1024)  # the policy's own limit gives the friendly error


class SigninBody(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=1024)


class TotpBody(BaseModel):
    email: str = Field(max_length=254)
    challenge: str = Field(max_length=4096)
    code: str = Field(max_length=16)


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


class CodeSent(BaseModel):
    status: Literal["code_sent"] = "code_sent"
    code_ttl_minutes: int  # auth.code_ttl_minutes, for the screen's copy
    code_max_tries: int  # auth.code_max_tries


class ResetVerifyBody(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=16)
    new_password: str = Field(max_length=1024)


class PasswordSetOut(BaseModel):
    status: Literal["password_set"] = "password_set"


class UserOut(BaseModel):
    id: str
    email: str


class SignedUpOut(BaseModel):
    access_token: str
    expires_in: int
    user: UserOut


class MembershipOut(BaseModel):
    business_id: str
    display_name: str
    gstin: str | None
    role: str


class SignedInOut(SignedUpOut):
    memberships: list[MembershipOut]


class TotpStepOut(BaseModel):
    step: Literal["totp"] = "totp"
    challenge: str  # the provider's opaque session string (L1-7); send it back with the code


class AccessTokenOut(BaseModel):
    access_token: str
    expires_in: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None
    fix: str | None = None


class ErrorOut(BaseModel):
    error: ErrorDetail
    challenge: str | None = None  # only on totp_not_accepted: the challenge to retry with


# Set here rather than taken from http.HTTPStatus, whose 422 phrase differs between
# Python 3.12 and 3.13, so openapi.json comes out the same on both.
_ERROR_DESCRIPTIONS = {400: "Bad Request", 401: "Unauthorized", 422: "Unprocessable Content", 429: "Too Many Requests"}


def _errors(*statuses: int) -> dict:
    return {status: {"model": ErrorOut, "description": _ERROR_DESCRIPTIONS[status]} for status in statuses}


@router.post("/signup", status_code=202, response_model=CodeSent, responses=_errors(422, 429))
def signup_request(
    body: EmailBody,
    request: Request,
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    terms = signup.request_code(_email(body.email), _client_ip(request), request_id(request), mail, clock.today())
    return CodeSent(code_ttl_minutes=terms.ttl_minutes, code_max_tries=terms.max_tries)


@router.post("/signup/verify", response_model=SignedUpOut, responses=_errors(400, 401, 422, 429))
def signup_verify(
    body: VerifyBody,
    request: Request,
    response: Response,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    _check_origin(request)
    done = signup.verify(
        _email(body.email), body.code, body.password, _client_ip(request), request_id(request), idp, clock.today()
    )
    _set_cookie(response, done.refresh_token)
    return {
        "access_token": done.access_token,
        "expires_in": done.expires_in,
        "user": {"id": str(done.user_id), "email": done.email},
    }


@router.post("/reset", status_code=202, response_model=CodeSent, responses=_errors(422, 429))
def reset_request(
    body: EmailBody,
    request: Request,
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    """§5.8: the same reply whether or not the email has an account."""
    terms = reset.request_reset(_email(body.email), _client_ip(request), request_id(request), mail, clock.today())
    return CodeSent(code_ttl_minutes=terms.ttl_minutes, code_max_tries=terms.max_tries)


@router.post("/reset/verify", response_model=PasswordSetOut, responses=_errors(400, 422, 429))
def reset_verify(
    body: ResetVerifyBody,
    request: Request,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    """§5.8. Sets no cookie: every session ends, and the user signs in again."""
    reset.verify_reset(
        _email(body.email),
        body.code,
        body.new_password,
        _client_ip(request),
        request_id(request),
        idp,
        mail,
        clock.today(),
    )
    return PasswordSetOut()


@router.post("/signin", response_model=SignedInOut | TotpStepOut, responses=_errors(401, 422, 429))
def signin_password(
    body: SigninBody,
    request: Request,
    response: Response,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    _check_origin(request)
    done = signin.sign_in(
        _email(body.email), body.password, _client_ip(request), request_id(request), idp, clock.today()
    )
    if isinstance(done, signin.TotpStep):
        return TotpStepOut(challenge=done.challenge)
    return _signed_in(response, done)


@router.post("/signin/totp", response_model=SignedInOut, responses=_errors(401, 422, 429))
def signin_totp(
    body: TotpBody,
    request: Request,
    response: Response,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    _check_origin(request)
    done = signin.sign_in_totp(
        _email(body.email), body.challenge, body.code, _client_ip(request), request_id(request), idp, clock.today()
    )
    return _signed_in(response, done)


def _signed_in(response: Response, done: signin.SignedIn) -> SignedInOut:
    _set_cookie(response, done.refresh_token)
    return SignedInOut(
        access_token=done.access_token,
        expires_in=done.expires_in,
        user=UserOut(id=str(done.user_id), email=done.email),
        memberships=[
            MembershipOut(business_id=str(m.business_id), display_name=m.display_name, gstin=m.gstin, role=m.role)
            for m in done.memberships
        ],
    )


def _set_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        refresh_token,
        max_age=COOKIE_MAX_AGE,
        path=COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


@router.post("/refresh", response_model=AccessTokenOut, responses=_errors(401, 429))
def refresh(
    request: Request,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    try:
        _check_origin(request)
        tokens = sessions.refresh(
            request.cookies.get(REFRESH_COOKIE),
            _client_ip(request),
            request_id(request),
            idp,
            clock.today(),
            background=request.headers.get("x-background") == "1",
        )
    except Deny as e:
        failed = deny_response(request, e)
        clear_refresh_cookie(failed)
        return failed
    # The refresh token isn't rotated (L1-5), so the cookie is left as it is.
    return AccessTokenOut(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post("/signout", status_code=204)
def signout(request: Request, idp: Annotated[AuthProvider, Depends(auth_provider)]):
    auth = request.headers.get("authorization", "")
    bearer = auth[7:] if auth.lower().startswith("bearer ") else None
    sessions.sign_out(bearer, request.cookies.get(REFRESH_COOKIE), request_id(request), idp)
    done = Response(status_code=204)
    clear_refresh_cookie(done)
    return done
