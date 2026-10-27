"""Read-only refdata routes the web needs (LLD-1 §11.2 onboarding). Signed-in users
only, on me_uow, as app_ro: refdata is global, so no business is needed."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from platform_common.clock import Clock, get_clock
from platform_common.uow import MeUoW

from .reader import gst_rates, state_codes

router = APIRouter(prefix="/refdata", tags=["refdata"])


class StateCode(BaseModel):
    code: str
    name: str


class StateCodesOut(BaseModel):
    on: date
    states: list[StateCode]


@router.get("/state-codes")
def get_state_codes(
    uow: MeUoW, clock: Annotated[Clock, Depends(get_clock)], on: Annotated[date | None, Query()] = None
) -> StateCodesOut:
    """The GST state and UT codes valid on `on` (default: today in India), exactly as
    loaded from refdata/state_codes.yaml. Code 96 (other country) is a place of supply
    only; business refuses it as a registration or address state (gstin.md §3)."""
    uow.become_read_only()
    day = on or clock.today()
    return StateCodesOut(on=day, states=[StateCode(code=c, name=n) for c, n in state_codes(uow.tx, day)])


class GstRatesOut(BaseModel):
    on: date
    rates: list[str]  # decimal strings, never numbers


@router.get("/gst-rates")
def get_gst_rates(
    uow: MeUoW, clock: Annotated[Clock, Depends(get_clock)], on: Annotated[date | None, Query()] = None
) -> GstRatesOut:
    """The GST rates a product's rate may take on `on` (default: today in India), exactly
    as loaded from refdata gst.rate_values, ascending. For the rate picker: it lists the
    rates, never suggests one (GC-P3). Empty before GST began."""
    uow.become_read_only()
    day = on or clock.today()
    return GstRatesOut(on=day, rates=[f"{r.normalize():f}" for r in gst_rates(uow.tx, day)])
