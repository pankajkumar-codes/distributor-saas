"""Signed-in routes that need no business yet (LLD-1 §5.9, §5.10), on me_uow.

S1-d1 adds GET /me/businesses and POST /b, S1-c3 POST /me/sessions/revoke-all; the
rest of §5.9 (password, TOTP, GET /me) joins this router with S1-c4.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel

from app.modules.business.interface import NewBusinessProfile
from platform_common.authprovider import AuthProvider
from platform_common.clock import Clock, get_clock
from platform_common.idempotency import run_once
from platform_common.uow import MeUoW

from .api_auth import clear_refresh_cookie
from .interface import create_business, list_my_businesses
from .providers import auth_provider
from .service import sessions

router = APIRouter(tags=["me"])


class MyBusiness(BaseModel):
    business_id: str
    display_name: str
    gstin: str | None
    role: Literal["owner", "admin", "billing", "ca"]


class MyBusinessesOut(BaseModel):
    businesses: list[MyBusiness]


class NewBusinessOut(BaseModel):
    business_id: str
    warnings: list[str]  # pan_shape, gstin_not_z, address_state_mismatch


@router.get("/me/businesses")
def my_businesses(uow: MeUoW) -> MyBusinessesOut:
    uow.become_read_only()
    return MyBusinessesOut(businesses=[
        MyBusiness(business_id=str(m.business_id), display_name=m.display_name, gstin=m.gstin, role=m.role)
        for m in list_my_businesses(uow.tx, uow.principal.user_id)
    ])


@router.post("/b", status_code=201, response_model=NewBusinessOut)
def new_business(
    body: NewBusinessProfile,
    request: Request,
    uow: MeUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    def create() -> dict:
        created = create_business(uow, body, today=clock.today())
        return {"business_id": str(created.business_id), "warnings": created.warnings}

    # Scoped to the user (LLD-0 §3.8): a retry returns the first answer and creates nothing.
    return run_once(
        uow.tx,
        uow.principal.user_id,
        idempotency_key,
        method=request.method,
        route=request.scope["route"].path,
        payload=body.model_dump(mode="json"),
        operation=create,
    )


@router.post("/me/sessions/revoke-all", status_code=204)
def revoke_all_sessions(uow: MeUoW, idp: Annotated[AuthProvider, Depends(auth_provider)]):
    """§5.7 Sign out everywhere, this device included: the SPA goes to sign-in."""
    sessions.revoke_all(uow, idp)
    done = Response(status_code=204)
    clear_refresh_cookie(done)
    return done
