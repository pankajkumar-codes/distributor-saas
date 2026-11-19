"""POST /api/v1/gstin-lookup (#249, D-100): details for a GSTIN, to fill the sign-up form.

Signed in, no business yet (sign-up step 3 runs before the business exists), so it sits outside /b/{business_id}. The reply
is a suggestion for the person to confirm or change; nothing is stored. The GSTIN goes in the body, not the URL, so it stays
out of access logs. Failure is always soft for the web: the form keeps working by hand.

The counter is spent before the unit of work opens (rate.hit's rule), keyed by the signed-in user's `sub` from the verified
token, so a person cannot use a paid provider as a free directory. The limit is a refdata row.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.refdata import value_on
from platform_common import rate
from platform_common.auth import current_caller
from platform_common.clock import Clock, get_clock
from platform_common.errors import AppError, Invalid, request_id
from platform_common.uow import MeUoW, Principal, unit_of_work

from . import gstin as g
from .gstin_lookup import Address, LookupOff, LookupUnavailable, provider

router = APIRouter(tags=["business"])
HOUR = timedelta(hours=1)
LIMIT_KEY = "business.gstin_lookup.per_user_per_hour"


class LookupUnavailableError(AppError):
    status = 503
    code = "lookup_unavailable"


class LookupOffError(AppError):
    status = 503
    code = "lookup_off"


class GstinLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gstin: str = Field(max_length=40)


class LookupAddress(BaseModel):
    line1: str | None
    line2: str | None
    city: str | None
    pin: str | None
    state_code: str | None


class GstinLookupOut(BaseModel):
    found: bool  # false: the provider has no record of this GSTIN (the person may still use it; we only checked its format)
    gstin: str
    legal_name: str | None
    trade_name: str | None
    status: str | None  # the provider's word for the registration's state, e.g. "Active"; not our verdict
    address: LookupAddress | None
    source: str  # which provider answered ("demo" locally): the form says where the details came from


def _spend_try(request: Request, clock: Annotated[Clock, Depends(get_clock)]) -> None:
    """Count this try against the user before anything else runs. 429 with Retry-After past the limit."""
    caller = current_caller(request)
    today: date = clock.today()
    with unit_of_work(Principal(user_sub=None, request_id=request_id(request)), read_only=True) as uow:
        limit = int(value_on(uow.tx, LIMIT_KEY, today))
    rate.hit(rate.bucket("gstin_lookup:user", caller.user_sub), limit, HOUR)


@router.post(
    "/gstin-lookup",
    response_model=GstinLookupOut,
    dependencies=[Depends(_spend_try)],
    responses={422: {"description": "not a well-formed GSTIN"}, 429: {"description": "rate_limited"}, 503: {"description": "lookup_off or lookup_unavailable"}},
)
def gstin_lookup(body: GstinLookupIn, uow: MeUoW) -> GstinLookupOut:
    """Only a GSTIN that passes the format and check-digit test is sent to the provider (`gstin_*` 422 otherwise). The reply
    never says "verified": it is the provider's record, for the person to confirm."""
    check = g.check_gstin(body.gstin)
    if not check.ok:
        code = check.errors[0]
        raise Invalid(code, g.message(code, body.gstin), field="gstin")
    try:
        chosen = provider()
        taxpayer = chosen.lookup(check.normalised)
    except LookupOff:
        raise LookupOffError(message="GSTIN lookup is not switched on") from None
    except LookupUnavailable:
        raise LookupUnavailableError(message="The lookup did not answer. Type the details in by hand.") from None
    name = chosen.name
    if taxpayer is None:
        return GstinLookupOut(found=False, gstin=check.normalised, legal_name=None, trade_name=None, status=None, address=None, source=name)
    a: Address = taxpayer.address
    return GstinLookupOut(
        found=True,
        gstin=taxpayer.gstin,
        legal_name=taxpayer.legal_name,
        trade_name=taxpayer.trade_name,
        status=taxpayer.status,
        address=LookupAddress(line1=a.line1, line2=a.line2, city=a.city, pin=a.pin, state_code=a.state_code),
        source=name,
    )
