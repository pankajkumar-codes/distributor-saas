"""The per-period gate and the file button (R3-M1, R3-M2) under /api/v1/b/{business_id}.

GET shows a period's gate: whether it has ended, the two confirmations and whether each still stands, the reasons the button is
closed, and the GSTR-1 due date from refdata (D-106). PUT records the business's answer for one item. POST opens the file
button, refused with 409 `period_gate_closed` until the gate is open. `returns.prepare` is needed for all of it.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from platform_common.clock import Clock, get_clock
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW

from . import period_gate

router = APIRouter(prefix="/b/{business_id}", tags=["filing"])
PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]
Item = Literal["purchases_uploaded", "invoices_in_portal"]


class GateConfirmationOut(BaseModel):
    item: Item
    confirmed: bool
    stale: bool  # confirmed once, but the period's rows have changed since: confirm again
    at: datetime | None


class GateReturnOut(BaseModel):
    instance_id: str
    form: str
    period_start: date
    period_end: date


class GatePlatformOut(BaseModel):
    platform: Literal["amazon", "flipkart", "meesho"]
    missing_months: list[str]  # 'YYYY-MM': files not uploaded and not marked as no sales


class PeriodGateOut(BaseModel):
    kind: Literal["month", "quarter"]
    period_start: date
    period_end: date
    ended: bool
    opens_on: date
    can_file: bool
    reasons: list[str]
    confirmations: list[GateConfirmationOut]
    platform_files: list[GatePlatformOut]
    gstr1_returns: list[GateReturnOut]
    due_date: date | None  # the GSTR-1 due date (D-106); None: the screen says "Check on the GST portal"
    due_dates: str = "Check on the GST portal"


class GateConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["month", "quarter"]
    start: date
    item: Item
    confirmed: bool


class GateOpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["month", "quarter"]
    start: date


def _out(g: period_gate.Gate) -> PeriodGateOut:
    return PeriodGateOut(
        kind=g.kind, period_start=g.period_start, period_end=g.period_end, ended=g.ended, opens_on=g.opens_on,
        can_file=g.can_file, reasons=list(g.reasons),
        confirmations=[GateConfirmationOut(item=c.item, confirmed=c.confirmed, stale=c.stale, at=c.at) for c in g.confirmations],
        platform_files=[GatePlatformOut(platform=p, missing_months=m) for p, m in g.platform_files],
        gstr1_returns=[GateReturnOut(instance_id=str(i.id), form=i.form, period_start=i.period_start, period_end=i.period_end)
                       for i in g.gstr1_returns],
        due_date=g.due_date)


@router.get("/period-gate", response_model=PeriodGateOut, dependencies=PREPARE)
def get_gate(uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)], kind: Annotated[Literal["month", "quarter"], Query()],
             start: Annotated[date, Query()]):
    return _out(period_gate.status(uow, kind, start, clock.today()))


@router.put("/period-gate", response_model=PeriodGateOut, dependencies=PREPARE)
def put_confirmation(body: GateConfirmIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    return _out(period_gate.confirm(uow, body.kind, body.start, body.item, body.confirmed, clock.today()))


@router.post("/period-gate/file", response_model=PeriodGateOut, dependencies=PREPARE)
def open_file(body: GateOpenIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    return _out(period_gate.open_file(uow, body.kind, body.start, clock.today()))
