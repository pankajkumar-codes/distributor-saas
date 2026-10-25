"""Refusals and errors, and the one response shape for them (LLD-0 §3.2).

`Deny` is every refusal that must not tell the caller whether the thing exists: not a
member, wrong role, unknown or malformed ID. All of them render as the same 404 body,
and only the log carries the reason. The one exception is `session_invalid`, which is
401 so the web app knows to refresh or sign in; it reveals nothing about any business.

`AppError` and its subclasses are errors the caller is meant to see and fix. Anything
else becomes a 500 with no exception text in the body.
"""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("platform_common.errors")

DenyReason = Literal["not_member", "role_denied", "not_found", "support_no_grant", "session_invalid"]
DENY_REASONS: frozenset[str] = frozenset(DenyReason.__args__)


class Deny(Exception):
    def __init__(self, reason: DenyReason):
        if reason not in DENY_REASONS:
            raise ValueError(f"unknown deny reason {reason!r}")
        super().__init__(reason)
        self.reason = reason


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, code: str | None = None, message: str = "", *, field: str | None = None, fix: str | None = None):
        super().__init__(message or code or self.code)
        self.code = code or self.code
        self.message = message
        self.field = field
        self.fix = fix

    def body(self) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.field:
            error["field"] = self.field
        if self.fix:
            error["fix"] = self.fix
        return {"error": error}


class Conflict(AppError):
    status = 409
    code = "conflict"


class Invalid(AppError):
    status = 422
    code = "invalid"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"

    def __init__(self, retry_after: int, message: str = "too many requests"):
        super().__init__(message=message)
        self.retry_after = retry_after


NOT_FOUND_BODY = {"error": {"code": "not_found", "message": "not found"}}
SESSION_BODY = {"error": {"code": "session_invalid", "message": "sign in again"}}


def request_id(request: Request) -> str:
    """API Gateway's request ID in AWS; a caller-supplied X-Request-ID only locally."""
    event = request.scope.get("aws.event") or {}
    return event.get("requestContext", {}).get("requestId") or request.headers.get("x-request-id") or "-"


def _route(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def deny_response(request: Request, exc: Deny) -> JSONResponse:
    log.info(
        "deny",
        extra={"event": "deny", "reason": exc.reason, "request_id": request_id(request), "route": _route(request)},
    )
    if exc.reason == "session_invalid":
        return JSONResponse(SESSION_BODY, status_code=401)
    return JSONResponse(NOT_FOUND_BODY, status_code=404)


def app_error_response(request: Request, exc: AppError) -> JSONResponse:  # noqa: ARG001
    headers = {"Retry-After": str(exc.retry_after)} if isinstance(exc, RateLimited) else None
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


def internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error", exc_info=exc, extra={"request_id": request_id(request), "route": _route(request)})
    return JSONResponse({"error": {"code": "internal", "message": "something went wrong"}}, status_code=500)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Deny, deny_response)
    app.add_exception_handler(AppError, app_error_response)
    app.add_exception_handler(Exception, internal_error_response)
