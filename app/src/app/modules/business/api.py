"""Business routes (LLD-1 §8.2), all under /api/v1/b/{business_id} on business_uow.

Reads are open to any member (billing and CA included) and run as app_ro; writes need
settings.edit (owner, admin). A non-member, or a role without the permission, gets the
same 404 as an unknown business.

POST /filing-profile/frequency belongs to filing's router (LLD-5 §11, erratum L5-9).
Business serves it, with LLD-5's path, body and reply, until filing exists (EM,
2026-10-27); moving it then changes nothing for the web client or the OpenAPI. Until
then there are no return instances, so `superseded_instances` is always empty and
`409 quarter_has_documents` can't arise.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Request
from pydantic import BaseModel, ConfigDict, Field

from app.modules.refdata import state_name
from platform_common.clock import Clock, get_clock
from platform_common.errors import Deny
from platform_common.idempotency import run_once
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW

from . import frequency as freq
from . import profile as prof
from .fiscal import fy_of
from .registration import STATE

router = APIRouter(prefix="/b/{business_id}", tags=["business"])
EDIT = [Depends(require(Permission.SETTINGS_EDIT))]
Band = Literal["up_to_threshold", "above_threshold"]
Frequency = Literal["monthly", "quarterly"]
FY = r"^[0-9]{4}-[0-9]{2}$"
MONEY = r"^[0-9]{1,16}(\.[0-9]{1,2})?$"  # decimal string, never a JSON number (LLD-0 §3.6)


# --- Shapes ---------------------------------------------------------------------------

class RegistrationOut(BaseModel):
    kind: Literal["gstin", "enrolment"]
    gstin: str | None
    enrolment_number: str | None
    state_code: str = Field(pattern=STATE)
    state_name: str | None
    locked: bool  # L1-14: fixed once the first live document is finalized


class AddressOut(BaseModel):
    line1: str | None
    line2: str | None
    city: str | None
    pin: str | None
    state_code: str | None


class TurnoverBandOut(BaseModel):
    fy: str
    band: Band
    declared_turnover: str | None  # decimal string


class ReadinessOut(BaseModel):
    ok: bool
    missing: list[Literal["legal_name", "address", "gstin"]]


class ProfileOut(BaseModel):
    business_id: str
    legal_name: str | None
    trade_name: str | None
    registration: RegistrationOut
    address: AddressOut
    einvoice_history: Literal["no", "yes", "not_sure"] | None
    turnover_band: TurnoverBandOut | None  # the current FY's
    ready_for_documents: ReadinessOut


class ProfileUpdateOut(BaseModel):
    profile: ProfileOut
    warnings: list[str]  # address_state_mismatch, pan_shape, gstin_not_z, frequency_carried


class TurnoverBandIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    band: Band
    declared_turnover: str | None = Field(default=None, pattern=MONEY)


class FrequencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Frequency
    effective_from: date  # a quarter's first day


class FrequencyRowOut(BaseModel):
    id: str
    gstin: str
    frequency: Frequency
    effective_from: date
    chosen_at: datetime
    warnings: list[str]


class FrequencyOut(BaseModel):
    row: FrequencyRowOut
    warnings: list[str]
    superseded_instances: list[str]  # filing's; always empty until LLD-5


class CurrentFrequencyOut(BaseModel):
    frequency: Frequency
    effective_from: date


class WindowOut(BaseModel):
    for_quarter: date
    opens: date | None  # null: unknown until the GST expert's refdata rows are loaded
    closes: date | None


class FilingProfileOut(BaseModel):
    gstin: str | None
    current: CurrentFrequencyOut | None
    history: list[FrequencyRowOut]
    window: WindowOut
    warnings: list[str]


class ChannelsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amazon: bool
    flipkart: bool
    meesho: bool


class ChannelsOut(ChannelsIn):
    model_config = ConfigDict(extra="ignore")
    answered: bool


def _profile_out(uow, today: date) -> ProfileOut:
    p = prof.get_profile(uow.tx)
    if p is None:
        raise Deny("not_found")
    band = prof.turnover_band(uow.tx, fy_of(today))
    ready = prof.ready_for_documents(uow.tx)
    return ProfileOut(
        business_id=str(p.business_id),
        legal_name=p.legal_name,
        trade_name=p.trade_name,
        registration=RegistrationOut(
            kind=p.registration_kind, gstin=p.gstin, enrolment_number=p.enrolment_number, state_code=p.state_code,
            state_name=state_name(uow.tx, p.state_code, today), locked=p.gstin_locked,
        ),
        address=AddressOut(line1=p.address_line1, line2=p.address_line2, city=p.city, pin=p.pin,
                           state_code=p.address_state_code),
        einvoice_history=p.einvoice_history,
        turnover_band=None if band is None else _band_out(band),
        ready_for_documents=ReadinessOut(ok=ready.ok, missing=ready.missing),
    )


def _band_out(band: prof.TurnoverBand) -> TurnoverBandOut:
    turnover = None if band.declared_turnover is None else str(band.declared_turnover)
    return TurnoverBandOut(fy=band.fy, band=band.band, declared_turnover=turnover)


def _row_out(r: freq.FrequencyRow) -> FrequencyRowOut:
    return FrequencyRowOut(id=str(r.id), gstin=r.gstin, frequency=r.frequency, effective_from=r.effective_from,
                           chosen_at=r.chosen_at, warnings=r.warnings)


Today = Annotated[Clock, Depends(get_clock)]


# --- Profile --------------------------------------------------------------------------

@router.get("/profile")
def get_profile(uow: BusinessUoW, clock: Today) -> ProfileOut:
    uow.become_read_only()
    return _profile_out(uow, clock.today())


@router.patch("/profile", dependencies=EDIT)
def patch_profile(body: prof.ProfilePatch, uow: BusinessUoW, clock: Today) -> ProfileUpdateOut:
    warnings = prof.update_profile(uow, body, today=clock.today())
    return ProfileUpdateOut(profile=_profile_out(uow, clock.today()), warnings=warnings)


@router.put("/turnover-bands/{fy}", dependencies=EDIT)
def put_turnover_band(
    body: TurnoverBandIn, uow: BusinessUoW, clock: Today, fy: Annotated[str, Path(pattern=FY)]
) -> TurnoverBandOut:
    turnover = None if body.declared_turnover is None else Decimal(body.declared_turnover)
    return _band_out(prof.set_turnover_band(uow, fy, body.band, turnover, today=clock.today()))


# --- Filing profile -------------------------------------------------------------------

@router.get("/filing-profile")
def get_filing_profile(uow: BusinessUoW, clock: Today) -> FilingProfileOut:
    uow.become_read_only()
    f = freq.filing_profile(uow.tx, today=clock.today())
    return FilingProfileOut(
        gstin=f.gstin,
        current=None if f.current is None else CurrentFrequencyOut(
            frequency=f.current.frequency, effective_from=f.current.effective_from),
        history=[_row_out(r) for r in f.history],
        window=WindowOut(for_quarter=f.window.for_quarter, opens=f.window.opens, closes=f.window.closes),
        warnings=f.warnings,
    )


@router.post("/filing-profile/frequency", status_code=201, dependencies=EDIT)
def post_frequency(
    body: FrequencyIn,
    request: Request,
    uow: BusinessUoW,
    clock: Today,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> FrequencyOut:
    def choose() -> dict:
        p = prof.get_profile(uow.tx)
        row, warnings = freq.add_frequency_row(
            uow, p.gstin if p else None, body.frequency, body.effective_from, today=clock.today()
        )
        return FrequencyOut(row=_row_out(row), warnings=warnings, superseded_instances=[]).model_dump(mode="json")

    return run_once(
        uow.tx,
        uow.principal.business_id,
        idempotency_key,
        method=request.method,
        route=request.scope["route"].path,
        payload=body.model_dump(mode="json"),
        operation=choose,
    )


# --- Marketplace channels -------------------------------------------------------------

def _channels_out(c: prof.Channels) -> ChannelsOut:
    return ChannelsOut(amazon=c.amazon, flipkart=c.flipkart, meesho=c.meesho, answered=c.answered)


@router.get("/channels")
def get_channels(uow: BusinessUoW) -> ChannelsOut:
    uow.become_read_only()
    return _channels_out(prof.channels(uow.tx))


@router.put("/channels", dependencies=EDIT)
def put_channels(body: ChannelsIn, uow: BusinessUoW) -> ChannelsOut:
    return _channels_out(prof.set_channels(uow, body.model_dump()))
