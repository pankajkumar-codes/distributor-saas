"""/api/v1/support/* (LLD-2 §6.3): TOTP recovery, for signed-in support users with TOTP
on. Anyone else gets 404, as if the routes didn't exist.

The routes open their own short transactions (service/support_totp.py) instead of
taking me_uow, because rate.hit must commit before the first one opens.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from platform_common.auth import current_caller
from platform_common.authprovider import AuthProvider
from platform_common.clock import Clock, get_clock
from platform_common.errors import request_id
from platform_common.mailer import Mailer

from .api_auth import CodeSent, _client_ip, _email, error_responses
from .providers import auth_provider, mailer
from .service import support_totp

router = APIRouter(prefix="/support", tags=["support"])


class RecoveryBody(BaseModel):
    email: str = Field(max_length=254)


class RecoveryConfirmBody(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(max_length=16)


@router.post("/totp-recovery", status_code=202, response_model=CodeSent, responses=error_responses(404, 422, 429))
def start_totp_recovery(
    body: RecoveryBody,
    request: Request,
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    """Mails a code to the account if it has TOTP on. The reply is the same for any email,
    so support can't use it to learn who has an account or TOTP."""
    terms = support_totp.start(current_caller(request), _email(body.email), request_id(request), mail, clock.today())
    return CodeSent(code_ttl_minutes=terms.ttl_minutes, code_max_tries=terms.max_tries)


@router.post("/totp-recovery/confirm", status_code=204, responses=error_responses(400, 404, 422, 429))
def confirm_totp_recovery(
    body: RecoveryConfirmBody,
    request: Request,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    """The code the user read out. Right: the account's TOTP is off and every session of
    it ends. Wrong: 400 code_not_accepted, and the fifth wrong try voids the code."""
    support_totp.confirm(
        current_caller(request),
        _email(body.email),
        body.code,
        _client_ip(request),
        request_id(request),
        idp,
        mail,
        clock.today(),
    )
    return Response(status_code=204)
