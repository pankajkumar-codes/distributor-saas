"""Read-only refdata routes the web needs (LLD-1 §11.2 onboarding). Signed-in users
only, on me_uow, as app_ro: refdata is global, so no business is needed."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from platform_common.clock import Clock, get_clock
from platform_common.uow import MeUoW

from .reader import state_codes

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
