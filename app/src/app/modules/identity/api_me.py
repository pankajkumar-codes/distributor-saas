"""Signed-in routes that need no business yet (LLD-1 §5.9, §5.10), on me_uow.

S1-d1 adds GET /me/businesses and POST /b, S1-c3 POST /me/sessions/revoke-all, S1-c4
GET and PATCH /me and POST /me/password; TOTP enrolment joins with S1-c4b.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, Field, field_validator

from app.modules.business.interface import NewBusinessProfile
from platform_common.authprovider import AuthProvider
from platform_common.auth import current_caller
from platform_common.clock import Clock, get_clock
from platform_common.errors import Deny, request_id
from platform_common.idempotency import run_once
from platform_common.mailer import Mailer
from platform_common.uow import MeUoW

from .api_auth import clear_refresh_cookie, error_responses
from .interface import create_business, list_my_businesses
from .providers import auth_provider, mailer
from .service import account, sessions

router = APIRouter(tags=["me"])


class MyBusiness(BaseModel):
    business_id: str
    display_name: str
    gstin: str | None
    role: Literal["owner", "admin", "billing", "ca"]


class MyBusinessesOut(BaseModel):
    businesses: list[MyBusiness]


class MeUser(BaseModel):
    id: str
    email: str
    name: str | None
    totp_enabled: bool


class MeMembership(MyBusiness):
    permissions: list[str]  # from the permissions matrix, so the SPA hides what the role can't do


class MeOut(BaseModel):
    user: MeUser
    memberships: list[MeMembership]


class NameBody(BaseModel):
    name: str | None = Field(max_length=100)

    @field_validator("name")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class PasswordBody(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(max_length=1024)  # the policy's own limit gives the friendly error


def _me_out(me: account.Me) -> MeOut:
    return MeOut(
        user=MeUser(id=str(me.user_id), email=me.email, name=me.name, totp_enabled=me.totp_enabled),
        memberships=[
            MeMembership(
                business_id=str(m.business_id),
                display_name=m.display_name,
                gstin=m.gstin,
                role=m.role,
                permissions=m.permissions,
            )
            for m in me.memberships
        ],
    )


class NewBusinessOut(BaseModel):
    business_id: str
    warnings: list[str]  # pan_shape, gstin_not_z, address_state_mismatch


@router.get("/me")
def me(uow: MeUoW) -> MeOut:
    return _me_out(account.get_me(uow))


@router.patch("/me")
def set_my_name(body: NameBody, uow: MeUoW) -> MeOut:
    return _me_out(account.set_name(uow, body.name))


@router.post("/me/password", status_code=204, responses=error_responses(401, 422, 429))
def change_password(
    body: PasswordBody,
    request: Request,
    idp: Annotated[AuthProvider, Depends(auth_provider)],
    mail: Annotated[Mailer, Depends(mailer)],
    clock: Annotated[Clock, Depends(get_clock)],
):
    """§5.9. Every session ends, this one included: the SPA goes to sign-in. Not on
    me_uow, because rate.hit runs before the first transaction (service/account.py)."""
    bearer = request.headers.get("authorization", "")
    if not bearer.lower().startswith("bearer "):  # ChangePassword needs the caller's own token
        raise Deny("session_invalid")
    account.change_password(
        current_caller(request),
        bearer[7:].strip(),
        body.current_password,
        body.new_password,
        request_id(request),
        idp,
        mail,
        clock.today(),
    )
    done = Response(status_code=204)
    clear_refresh_cookie(done)
    return done


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
