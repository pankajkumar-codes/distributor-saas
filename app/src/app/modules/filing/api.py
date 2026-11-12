"""Filing routes (LLD-5 §11): the returns list.

GET /b/{id}/returns?fy=2026-27 lists the FY's return instances with their due dates, for
the business's GSTIN. Any member may read it (CA included). The server computes every
date from refdata; each carries `due_date_confirmed`, false until the GST expert or CA
confirms the refdata row, and a null date means none exists, never a guess. Instances are
created on first read (ensure_instances), so this is a read that writes: no app_ro switch.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.modules.business.interface import (
    filing_frequency_on,
    fy_of,
    fy_quarters,
    get_profile,
    is_fy,
    quarter_start,
)
from platform_common.clock import Clock, get_clock
from platform_common.errors import Invalid
from platform_common.uow import BusinessUoW

from . import periods

router = APIRouter(prefix="/b/{business_id}", tags=["filing"])
FY = r"^[0-9]{4}-[0-9]{2}$"
Today = Annotated[Clock, Depends(get_clock)]


class ReturnOut(BaseModel):
    instance_id: str
    form: Literal["GSTR1", "IFF", "GSTR3B", "PMT06"]
    period: str  # '2026-10' for a month, '2026-Q3' for a quarter (FY start year; Q1 = Apr-Jun)
    period_label: str  # 'Oct 2026' or 'Oct–Dec 2026'
    period_start: date
    period_end: date
    due_date: date | None  # None: no date exists (state 97 quarterly GSTR-3B)
    due_date_confirmed: bool  # false until the refdata row is expert- or CA-confirmed
    due_date_source_url: str | None  # the refdata source citation
    status: Literal["open", "filed_locked", "unlocked", "skipped"]


class ReturnsOut(BaseModel):
    fy: str
    gstin: str | None
    filing_frequency: Literal["monthly", "quarterly"] | None  # in force today; None: not set
    returns: list[ReturnOut]


@router.get("/returns")
def list_returns(uow: BusinessUoW, clock: Today, fy: Annotated[str | None, Query(pattern=FY)] = None) -> ReturnsOut:
    today = clock.today()
    fy = fy or fy_of(today)
    if not is_fy(fy):
        raise Invalid("invalid_fy", "That is not a financial year.", field="fy")
    profile = get_profile(uow.tx)
    gstin = None if profile is None else profile.gstin
    if gstin is None:
        return ReturnsOut(fy=fy, gstin=None, filing_frequency=None, returns=[])
    current = filing_frequency_on(uow.tx, gstin, today)
    out: list[ReturnOut] = []
    for q in fy_quarters(fy):
        # A quarter before any frequency was chosen has no returns to show.
        if filing_frequency_on(uow.tx, gstin, quarter_start(q)) is None:
            continue
        for inst in periods.ensure_instances(uow.tx, gstin, q):
            due = periods.due_now(uow.tx, inst)
            out.append(ReturnOut(
                instance_id=str(inst.id), form=inst.form, period=periods.period_key(inst),
                period_label=periods.period_label(inst), period_start=inst.period_start,
                period_end=inst.period_end, due_date=due.date, due_date_confirmed=due.confirmed,
                due_date_source_url=due.source_url, status=inst.status,
            ))  # fmt: skip
    return ReturnsOut(fy=fy, gstin=gstin, filing_frequency=None if current is None else current.frequency, returns=out)
