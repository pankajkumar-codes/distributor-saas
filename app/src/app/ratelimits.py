"""Per-user limits on the API's writes and heavy reads (#472, D-120).

API Gateway's stage throttle (infra/modules/api) protects the servers but is shared by every caller, so one user can
use it all. This adds the inner layer: each signed-in user gets an hourly allowance per business for each kind of
call, counted in `platform.rate_counters` (platform_common.rate) and answered with 429 and Retry-After past it.

One dependency, `throttle`, is added to every router in app.api, so routes don't each carry one. It reads the matched
route and looks it up in LIMITS; a route that isn't there costs nothing (no database call). Every write route must be
in LIMITS or in NO_LIMIT with a reason; app/tests/test_ratelimits.py fails otherwise, so a new route can't skip it.

The count is per user AND per business: a user's tries never use up another user's allowance, and a stranger calling
someone else's business (who gets 404 anyway) only spends their own. Counting runs before the request's unit of work
opens (rate.hit needs that), so it comes before the permission check: a refused call still counts, as it should.

The numbers are refdata rows (`ratelimit.<kind>_per_user_per_business_per_hour`), so they can be tuned without a
release. They are sized well above what one person does by hand.
"""

import uuid
from datetime import timedelta

from typing import Annotated

from fastapi import Depends, Request

from app.modules.refdata import value_on
from platform_common import rate
from platform_common.auth import current_caller
from platform_common.clock import Clock, get_clock
from platform_common.errors import Deny, request_id
from platform_common.uow import Principal, unit_of_work

HOUR = timedelta(hours=1)
API = "/api/v1"
P = f"{API}/b/{{business_id}}"

# What each kind protects. The refdata key is ratelimit.<kind>_per_user_per_business_per_hour.
KINDS = {
    "render": "a PDF made by the renderer, the heaviest job",
    "export": "a file built from a whole period or log",
    "upload": "a file stored and read",
    "rebuild": "a return recomputed from every row",
    "issue": "a legal document issued or cancelled",
    "estimate": "the invoice form's live totals",
    "write": "any other change",
}

LIMITS: dict[tuple[str, str], str] = {
    # render
    ("POST", f"{P}/documents/{{document_id}}/pdf"): "render",
    ("POST", f"{P}/drafts/{{draft_id}}/preview"): "render",
    ("POST", f"{P}/returns/{{instance_id}}/worksheet/pdf"): "render",
    # export (two are GETs that build the file on the spot)
    ("POST", f"{P}/audit-log/exports"): "export",
    ("POST", f"{P}/period-files"): "export",
    ("POST", f"{P}/returns/{{instance_id}}/exports"): "export",
    ("GET", f"{P}/returns/{{instance_id}}/worksheet/excel"): "export",
    ("GET", f"{P}/returns/{{instance_id}}/lock-file"): "export",
    # upload
    ("POST", f"{P}/uploads"): "upload",
    ("POST", f"{P}/uploads/{{upload_id}}/complete"): "upload",
    ("POST", f"{P}/upload-bundles"): "upload",
    ("POST", f"{P}/upload-bundles/{{bundle_id}}/stage"): "upload",
    ("POST", f"{P}/upload-bundles/{{bundle_id}}/complete"): "upload",
    ("POST", f"{P}/purchase-files"): "upload",
    ("POST", f"{P}/purchase-files/{{file_id}}/complete"): "upload",
    ("POST", f"{P}/product-imports"): "upload",
    ("POST", f"{P}/product-imports/{{import_id}}/complete"): "upload",
    # rebuild
    ("POST", f"{P}/returns/{{instance_id}}/worksheet/build"): "rebuild",
    ("POST", f"{P}/returns/{{instance_id}}/check-acceptances"): "rebuild",
    # issue
    ("POST", f"{P}/drafts/{{draft_id}}/finalize"): "issue",
    ("POST", f"{P}/documents/{{document_id}}/credit-notes"): "issue",
    ("POST", f"{P}/documents/{{document_id}}/debit-notes"): "issue",
    ("POST", f"{P}/documents/{{document_id}}/cancel"): "issue",
    # estimate
    ("POST", f"{P}/drafts/estimate"): "estimate",
    # write: business data
    ("POST", "/api/v1/b"): "write",
    ("PUT", f"{P}/channels"): "write",
    ("POST", f"{P}/customers"): "write",
    ("PATCH", f"{P}/customers/{{customer_id}}"): "write",
    ("DELETE", f"{P}/customers/{{customer_id}}"): "write",
    ("POST", f"{P}/customers/{{customer_id}}/archive"): "write",
    ("POST", f"{P}/customers/{{customer_id}}/unarchive"): "write",
    ("POST", f"{P}/drafts"): "write",
    ("PUT", f"{P}/drafts/{{draft_id}}"): "write",
    ("DELETE", f"{P}/drafts/{{draft_id}}"): "write",
    ("POST", f"{P}/filing-profile/frequency"): "write",
    ("POST", f"{P}/invitations"): "write",
    ("POST", f"{P}/invitations/{{invitation_id}}/cancel"): "write",
    ("POST", f"{P}/invitations/{{invitation_id}}/resend"): "write",
    ("PATCH", f"{P}/members/{{user_id}}"): "write",
    ("POST", f"{P}/members/{{user_id}}/deactivate"): "write",
    ("POST", f"{P}/members/{{user_id}}/reactivate"): "write",
    ("PUT", f"{P}/numbering"): "write",
    ("PUT", f"{P}/period-gate"): "write",
    ("POST", f"{P}/period-gate/file"): "write",
    ("POST", f"{P}/product-imports/{{import_id}}/confirm"): "write",
    ("POST", f"{P}/product-imports/{{import_id}}/discard"): "write",
    ("POST", f"{P}/products"): "write",
    ("PATCH", f"{P}/products/{{product_id}}"): "write",
    ("DELETE", f"{P}/products/{{product_id}}"): "write",
    ("POST", f"{P}/products/{{product_id}}/archive"): "write",
    ("POST", f"{P}/products/{{product_id}}/unarchive"): "write",
    ("POST", f"{P}/products/{{product_id}}/rates"): "write",
    ("POST", f"{P}/products/{{product_id}}/rates/{{rate_id}}/confirm"): "write",
    ("POST", f"{P}/products/{{product_id}}/rates/{{rate_id}}/unconfirm"): "write",
    ("POST", f"{P}/products/{{product_id}}/rates/{{rate_id}}/void"): "write",
    ("POST", f"{P}/products/{{product_id}}/stock-adjustments"): "write",
    ("PATCH", f"{P}/profile"): "write",
    ("POST", f"{P}/purchase-drafts/{{draft_id}}/confirm"): "write",
    ("POST", f"{P}/purchase-drafts/{{draft_id}}/discard"): "write",
    ("POST", f"{P}/returns/{{instance_id}}/completed"): "write",
    ("POST", f"{P}/returns/{{instance_id}}/filed"): "write",
    ("PUT", f"{P}/returns/{{instance_id}}/table13"): "write",
    ("POST", f"{P}/returns/{{instance_id}}/unlock"): "write",
    ("PUT", f"{P}/returns/{{instance_id}}/worksheet/entries"): "write",
    ("POST", f"{P}/rows/{{row_id}}/resolve"): "write",
    ("POST", f"{P}/runs/{{run_id}}/confirm"): "write",
    ("POST", f"{P}/runs/{{run_id}}/discard"): "write",
    ("POST", f"{P}/stock-movements/{{movement_id}}/reversals"): "write",
    ("POST", f"{P}/support-grants"): "write",
    ("POST", f"{P}/support-grants/{{grant_id}}/revoke"): "write",
    ("PUT", f"{P}/turnover-bands/{{fy}}"): "write",
    ("PATCH", f"{P}/upload-bundles/{{bundle_id}}/files/{{n}}"): "write",
    ("POST", f"{P}/uploads/none-this-month"): "write",
    # write: the signed-in user's own account
    ("POST", "/api/v1/identity/tenants"): "write",
    ("PATCH", "/api/v1/me"): "write",
    ("POST", "/api/v1/me/invitations/{token}/accept"): "write",
    ("POST", "/api/v1/me/sessions/revoke-all"): "write",
    ("POST", "/api/v1/me/totp/setup"): "write",
    ("POST", "/api/v1/me/totp/confirm"): "write",
    ("DELETE", "/api/v1/me/totp"): "write",
}

OWN = "has its own limits per email and IP address (refdata auth.*), counted before anyone is signed in"
NO_LIMIT: dict[tuple[str, str], str] = {
    ("POST", "/api/v1/auth/signup"): OWN,
    ("POST", "/api/v1/auth/signup/verify"): OWN,
    ("POST", "/api/v1/auth/signin"): OWN,
    ("POST", "/api/v1/auth/signin/totp"): OWN,
    ("POST", "/api/v1/auth/reset"): OWN,
    ("POST", "/api/v1/auth/reset/verify"): OWN,
    ("POST", "/api/v1/auth/refresh"): OWN,
    ("POST", "/api/v1/auth/session/replace"): OWN,
    ("POST", "/api/v1/auth/session/cancel"): "ends a pending sign-in; nothing to gain by repeating it",
    ("POST", "/api/v1/auth/signout"): "ends the caller's own session; must always work",
    ("POST", "/api/v1/me/password"): "counted under the sign-in limit per email (identity/service/account.py)",
    ("POST", "/api/v1/gstin-lookup"): "has its own per-user limit (business.gstin_lookup.per_user_per_hour)",
    ("POST", "/api/v1/support/totp-recovery"): "has its own limits per support user and per email (support.*)",
    ("POST", "/api/v1/support/totp-recovery/confirm"): "counted under auth.code_checks_per_ip_per_hour",
}


def route_path(request: Request) -> str:
    """The matched route's template with the /api/v1 prefix. FastAPI 0.165 matches through the included router and
    gives the router's own path (/b/{business_id}/...); older versions give the prefixed copy. Both end up the same."""
    path = getattr(request.scope.get("route"), "path", "") or ""
    return path if path.startswith(API) else API + path


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def key(kind: str) -> str:
    return f"ratelimit.{kind}_per_user_per_business_per_hour"


def throttle(request: Request, clock: Annotated[Clock, Depends(get_clock)]) -> None:
    """Count this call against the caller's allowance for its kind. No-op for a route not in LIMITS, and for a call
    with no signed-in caller (the route's own check answers 401)."""
    kind = LIMITS.get((request.method, route_path(request)))
    if kind is None:
        return
    try:
        caller = current_caller(request)
    except Deny:
        return
    business = request.path_params.get("business_id") or "-"
    if business != "-" and not _is_uuid(business):
        return  # can't be a business: the route answers 404 itself, and no counter row is made for it (#474)
    # Its own short read-only transaction, closed before rate.hit (which must run with no unit of work open).
    with unit_of_work(Principal(user_sub=None, request_id=request_id(request)), read_only=True) as uow:
        limit = int(value_on(uow.tx, key(kind), clock.today()))
    rate.hit(rate.bucket(f"api_{kind}:user_business", f"{caller.user_sub}|{business}"), limit, HOUR, clock=clock)
