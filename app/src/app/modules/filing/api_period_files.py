"""Monthly and quarterly sales-and-purchases file routes (R2-M6) under /api/v1/b/{business_id}.

POST makes the Excel workbook and the purchase register for a finished month (or quarter, for a quarterly filer), or
returns the ones already made from the same data. GET lists them and gives 60-second links. `returns.prepare` is
needed for all of it, like the GSTR-1 file. Another business's export is a 404.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from platform_common.clock import Clock, get_clock
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import period_files

router = APIRouter(prefix="/b/{business_id}", tags=["filing"])
PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]


class PeriodFilesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["month", "quarter"]
    start: date  # the first day of the month, or of the quarter


class PeriodFileOut(BaseModel):
    name: Literal["workbook", "purchase_register"]
    sha256: str
    size_bytes: int
    url: str  # a 60-second link


class PeriodReturnOut(BaseModel):
    instance_id: str
    form: str
    period_start: date
    period_end: date


class PeriodExportOut(BaseModel):
    id: str
    kind: Literal["month", "quarter"]
    period_start: date
    period_end: date
    sales_lines: int
    purchase_lines: int
    practice_documents: int
    created_at: datetime
    created: bool  # false when the files from the same data already existed
    gstr1_returns: list[PeriodReturnOut]  # the period's return instances: the GSTR-1 JSON is made from each one's own screen
    files: list[PeriodFileOut]
    due_dates: str = "Check on the GST portal"


class PeriodExportsOut(BaseModel):
    exports: list[PeriodExportOut]
    has_more: bool


def _out(uow, e: period_files.PeriodExport, *, with_links: bool) -> PeriodExportOut:
    return PeriodExportOut(
        id=str(e.id), kind=e.kind, period_start=e.start, period_end=e.end, sales_lines=e.sales_lines,
        purchase_lines=e.purchase_lines, practice_documents=e.practice_documents, created_at=e.created_at,
        created=e.created,
        gstr1_returns=[PeriodReturnOut(instance_id=str(i.id), form=i.form, period_start=i.period_start,
                                       period_end=i.period_end) for i in period_files.returns_in(uow, e)],
        files=[PeriodFileOut(**f) for f in period_files.links(uow, e)] if with_links else [])


@router.post("/period-files", response_model=PeriodExportOut, dependencies=PREPARE)
def make_period_files(body: PeriodFilesIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    return _out(uow, period_files.generate(uow, body.kind, body.start, clock.today()), with_links=True)


@router.get("/period-files", response_model=PeriodExportsOut, dependencies=PREPARE)
def list_period_files(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)]):
    found, more = period_files.list_exports(uow, page.limit, page.offset)
    return PeriodExportsOut(exports=[_out(uow, e, with_links=False) for e in found], has_more=more)


@router.get("/period-files/{export_id}", response_model=PeriodExportOut, dependencies=PREPARE)
def get_period_files(export_id: str, uow: BusinessUoW):
    return _out(uow, period_files.get_export(uow, parse_id(export_id)), with_links=True)
