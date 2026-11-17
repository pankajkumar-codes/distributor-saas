"""GSTR-3B worksheet routes (R1-M8b, W2). Numbers to check and enter on the GST portal, never a filing.

GET /returns/{instance}/worksheet shows the latest build of the outward supplies, what the seller typed, whether the GSTR-1 has
changed since the build, and whether a new build is allowed now. POST .../worksheet/build makes the next version. PUT
.../worksheet/entries saves what the seller typed. The instance must be this business's GSTR-3B; anything else is a 404.
There is no net payable, offset, interest or late fee anywhere in these responses. Needs `returns.prepare`. When the plan does
not allow it (the same hook as the GSTR-1 file), the response says the worksheet exists and carries no figures.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi import status as http
from pydantic import BaseModel

from app.modules.business.interface import gstin_state

from platform_common.clock import Clock, get_clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.permissions import Permission, require
from platform_common.storage import get_store, key_for
from platform_common.uow import BusinessUoW, parse_id

from . import entitlement, periods, worksheet, worksheet_pdf
from .build import build_return
from .gstr1 import Amounts
from .gstr3b import FLAG_TEXT, drill, excel
from .gstr3b.entries import net_itc
from .gstr3b.labels import OFFSET_NOTE, PORTAL_NOTE, WORKSHEET_LABEL

router = APIRouter(prefix="/b/{business_id}", tags=["filing"])
PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class AmountsOut(BaseModel):
    taxable_value: str
    igst: str
    cgst: str
    sgst: str
    cess: str


class InterStateOut(BaseModel):
    pos_state_code: str
    unregistered_taxable: str
    unregistered_igst: str
    source_refs: list[str]


class FlagOut(BaseModel):
    code: str
    text: str


class OutwardOut(BaseModel):
    version: int
    built_at: str
    taxable: AmountsOut  # Table 3.1(a)
    taxable_refs: list[str]
    inter_state: list[InterStateOut]  # Table 3.2, unregistered buyers
    inter_state_taxable: str
    inter_state_igst: str
    zero_rate_rows: int
    flags: list[FlagOut]


class WorksheetOut(BaseModel):
    label: str = WORKSHEET_LABEL
    note: str = PORTAL_NOTE
    offset_note: str = OFFSET_NOTE
    available: bool  # false: the plan does not allow it yet; no figures are returned
    built: bool
    out_of_date: bool  # the GSTR-1 has changed since the latest build
    can_build: bool
    build_blocked_by: str | None  # a reason in words when can_build is false
    outward: OutwardOut | None
    entries: dict[str, str]  # what the seller typed, by `<table>.<row>.<head>`
    entries_seq: int | None  # the save the screen is showing; send it back with the next save
    net_itc: dict[str, str]  # Table 4 (C): typed available minus typed reversed, by head. Shown only.


class EntriesIn(BaseModel):
    entries: dict[str, str | int | None]
    based_on_seq: int | None = None


class EntriesOut(BaseModel):
    entries: dict[str, str]
    entries_seq: int | None
    net_itc: dict[str, str]


def _instance_or_404(uow: BusinessUoW, instance_id: str):
    try:
        iid = uuid.UUID(instance_id)
    except ValueError:
        raise Deny("not_found") from None
    inst = periods.get_instance(uow.tx, iid)
    if inst is None or inst.form != "GSTR3B":
        raise Deny("not_found")
    return inst


def _outward_out(v: worksheet.Version) -> OutwardOut:
    o = v.outward
    return OutwardOut(
        version=v.version, built_at=v.built_at.isoformat(), taxable=AmountsOut(**o["taxable"]),
        taxable_refs=o["taxable_refs"], inter_state=[InterStateOut(**r) for r in o["inter_state"]],
        inter_state_taxable=o["inter_state_taxable"], inter_state_igst=o["inter_state_igst"],
        zero_rate_rows=o["zero_rate_rows"], flags=[FlagOut(code=c, text=FLAG_TEXT[c]) for c in o["flags"]],
    )  # fmt: skip


def _live(uow: BusinessUoW, inst, g1, latest) -> tuple[bool, str | None]:
    """Whether the GSTR-1 has changed since the latest build, and why a new build is not possible now (None: it is)."""
    tx = uow.tx
    out_of_date, blocked = False, None
    if g1 is None:
        blocked = "There is no GSTR-1 for this period yet."
    else:
        b = build_return(tx, g1)
        out_of_date = latest is not None and latest.fingerprint != b.fingerprint
        n = worksheet.blocks_of(tx, b)
        if n:
            blocked = f"{n} item{'s' if n != 1 else ''} to fix in your GSTR-1 first."
    if inst.status != "open":
        blocked = "This return is not open."
    return out_of_date, blocked


@router.get("/returns/{instance_id}/worksheet", dependencies=PREPARE)
def get_worksheet(instance_id: str, uow: BusinessUoW) -> WorksheetOut:
    inst = _instance_or_404(uow, instance_id)
    tx = uow.tx
    g1 = worksheet.gstr1_of(tx, inst)
    latest = worksheet.latest_version(tx, inst.id)
    if not entitlement.allowed(tx, uow.principal.business_id):
        return WorksheetOut(available=False, built=latest is not None, out_of_date=False, can_build=False,
                            build_blocked_by=None, outward=None, entries={}, entries_seq=None, net_itc={})  # fmt: skip
    cur = worksheet.current_entry(tx, inst.id)
    out_of_date, blocked = _live(uow, inst, g1, latest)
    entries = cur.entry if cur else {}
    return WorksheetOut(
        available=True, built=latest is not None, out_of_date=out_of_date, can_build=blocked is None,
        build_blocked_by=blocked, outward=None if latest is None else _outward_out(latest), entries=entries,
        entries_seq=cur.seq if cur else None, net_itc=net_itc(entries) if entries else {},
    )  # fmt: skip


@router.post("/returns/{instance_id}/worksheet/build", dependencies=PREPARE)
def build_worksheet(instance_id: str, uow: BusinessUoW) -> OutwardOut:
    inst = _instance_or_404(uow, instance_id)
    worksheet.require_allowed(uow)
    return _outward_out(worksheet.build_version(uow, inst))


@router.put("/returns/{instance_id}/worksheet/entries", dependencies=PREPARE)
def put_entries(instance_id: str, body: EntriesIn, uow: BusinessUoW) -> EntriesOut:
    inst = _instance_or_404(uow, instance_id)
    worksheet.require_allowed(uow)
    e = worksheet.save_entries(uow, inst, dict(body.entries), body.based_on_seq)
    return EntriesOut(entries=e.entry, entries_seq=e.seq or None, net_itc=net_itc(e.entry) if e.entry else {})


class ExcelOut(BaseModel):
    url: str  # a link that works for 60 seconds
    name: str
    version: int  # the build the file shows
    entries_seq: int | None
    out_of_date: bool  # the file says so too


@router.get("/returns/{instance_id}/worksheet/excel", dependencies=PREPARE)
def worksheet_excel(instance_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]) -> ExcelOut:
    """The worksheet as it is now (latest build and typed entries) as an Excel file, stored with the exports and given as a
    60-second link. 409 when the plan does not allow it or nothing has been built."""
    inst = _instance_or_404(uow, instance_id)
    worksheet.require_allowed(uow)
    tx = uow.tx
    latest = worksheet.latest_version(tx, inst.id)
    if latest is None:
        raise Conflict("worksheet_not_built", "Build the worksheet first.")
    out_of_date, _ = _live(uow, inst, worksheet.gstr1_of(tx, inst), latest)
    cur = worksheet.current_entry(tx, inst.id)
    entries = cur.entry if cur else {}
    model = excel.SheetModel(
        gstin=inst.gstin, period_label=periods.period_label(inst), version=latest.version,
        built_at=f"{latest.built_at:%d %b %Y %H:%M} UTC", generated_at=f"{clock.now():%d %b %Y %H:%M}",
        out_of_date=out_of_date, outward=latest.outward, entries=entries, flags=tuple(latest.outward["flags"]),
    )  # fmt: skip
    data = excel.render(model)
    business = uow.principal.business_id
    key = key_for(business, "exports", latest.id, f"v{latest.version}-e{cur.seq if cur else 0}.xlsx")
    store = get_store()
    store.put(business, key, data, XLSX)
    name = f"GSTR3B_worksheet_{inst.gstin}_{inst.period_end:%m%Y}.xlsx"
    return ExcelOut(url=store.presign_get(business, key, download_name=name), name=name, version=latest.version,
                    entries_seq=cur.seq if cur else None, out_of_date=out_of_date)  # fmt: skip


# -- Drill-down (W5): the GSTR-1 rows behind a figure ---------------------------------------------------------------------

PAGE = 100


class DrillRowOut(BaseModel):
    section: str
    kind: str  # invoice, credit_note or b2cs_group
    doc_number: str | None
    doc_date: str | None
    pos_state_code: str
    rate: str
    taxable_value: str  # signed: a credit note is negative
    igst: str
    cgst: str
    sgst: str
    cess: str
    source_refs: list[str]


class DrillOut(BaseModel):
    figure: str
    state: str | None
    rows: list[DrillRowOut]
    next_cursor: str | None
    total: AmountsOut  # the sum of every row, not only this page
    out_of_date: bool  # the GSTR-1 has changed since the build; the rows are the GSTR-1 as it is now


@router.get("/returns/{instance_id}/worksheet/rows", dependencies=PREPARE)
def worksheet_rows(
    instance_id: str,
    uow: BusinessUoW,
    figure: Annotated[Literal["3_1_a", "3_2"], Query()],
    state: Annotated[str | None, Query(pattern=r"^[0-9]{2}$")] = None,
    cursor: Annotated[str | None, Query(max_length=12)] = None,
) -> DrillOut:
    """The GSTR-1 rows behind Table 3.1(a), or behind one place of supply of Table 3.2 (`state` is then required): the same
    rows `build` adds up, credit notes negative, so they sum to the figure. Same plan hook as the rest of the worksheet."""
    inst = _instance_or_404(uow, instance_id)
    worksheet.require_allowed(uow)
    if (figure == "3_2") != (state is not None):
        raise Invalid("invalid_figure", "Give a place of supply for Table 3.2, and only for it.", field="state")
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise Invalid("invalid_cursor", "That page marker is not valid.", field="cursor") from None
    if start < 0:
        raise Invalid("invalid_cursor", "That page marker is not valid.", field="cursor")
    tx = uow.tx
    g1 = worksheet.gstr1_of(tx, inst)
    if g1 is None:
        raise Conflict("no_gstr1", "There is no GSTR-1 for this period.")
    b = build_return(tx, g1)
    latest = worksheet.latest_version(tx, inst.id)
    rows = drill.rows_behind([b.sections, *b.iff_sections], gstin_state(inst.gstin), figure, state)
    total = Amounts()
    for r in rows:
        total += r.amounts
    page = rows[start : start + PAGE]
    more = start + PAGE < len(rows)
    return DrillOut(
        figure=figure, state=state, rows=[_drill_row(r) for r in page], next_cursor=str(start + PAGE) if more else None,
        total=AmountsOut(taxable_value=str(total.taxable_value), igst=str(total.igst), cgst=str(total.cgst),
                         sgst=str(total.sgst), cess=str(total.cess)),
        out_of_date=latest is not None and latest.fingerprint != b.fingerprint,
    )  # fmt: skip


def _drill_row(r: drill.DrillRow) -> DrillRowOut:
    a = r.amounts
    return DrillRowOut(
        section=r.section, kind=r.kind, doc_number=r.doc_number, doc_date=r.doc_date.isoformat() if r.doc_date else None,
        pos_state_code=r.pos_state_code, rate=str(r.rate), taxable_value=str(a.taxable_value), igst=str(a.igst),
        cgst=str(a.cgst), sgst=str(a.sgst), cess=str(a.cess), source_refs=list(r.source_refs),
    )  # fmt: skip


# -- PDF (W5b) ------------------------------------------------------------------------------------------------------------


class PdfRef(BaseModel):
    job_id: str


class PdfStatusOut(BaseModel):
    status: Literal["queued", "rendering", "ready", "failed"]
    url: str | None = None  # a link that works for 60 seconds, when ready
    error_code: str | None = None


@router.post("/returns/{instance_id}/worksheet/pdf", dependencies=PREPARE, status_code=http.HTTP_202_ACCEPTED)
def start_pdf(instance_id: str, uow: BusinessUoW) -> PdfRef:
    """Queues the worksheet PDF for the latest build and current entries. 409 when nothing is built or the plan says no; asking
    again for the same state joins the same job."""
    inst = _instance_or_404(uow, instance_id)
    return PdfRef(job_id=str(worksheet_pdf.start(uow, inst)))


@router.get("/returns/{instance_id}/worksheet/pdf/{job_id}", dependencies=PREPARE)
def pdf_status(instance_id: str, job_id: str, uow: BusinessUoW) -> PdfStatusOut:
    inst = _instance_or_404(uow, instance_id)
    return PdfStatusOut(**worksheet_pdf.status(uow, inst.id, parse_id(job_id)))
