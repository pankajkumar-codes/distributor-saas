"""Filing routes (LLD-5 §11): the returns list and a built return (R1-M7 slice 5).

GET /returns/{instance} is the on-screen GSTR-1 or IFF from the confirmed uploads: section totals, findings (report-only in
M7), what the build rests on, and a draft banner. GET /returns/{instance}/sections/{section} lists a section's rows
with their source references. Both need `returns.prepare`; another business's instance, or a form that is not built
from supply lines, is a 404. Nothing here changes anything.

GET /b/{id}/returns?fy=2026-27 lists the FY's return instances with their due dates, for
the business's GSTIN. Any member may read it (CA included). The server computes every
date from refdata; each carries `due_date_confirmed`, false until the GST expert or CA
confirms the refdata row, and a null date means none exists, never a guess. Instances are
created on first read (ensure_instances) for quarters that have started, so this is a read that
writes: no app_ro switch. Under a support grant (read-only) it shows only the rows that exist.
"""

import uuid
from dataclasses import fields
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.modules.business.interface import (
    filing_frequency_on,
    fy_of,
    fy_quarters,
    get_profile,
    is_fy,
    quarter_months,
    quarter_start,
)
from platform_common.clock import Clock, get_clock
from platform_common.errors import Deny, Invalid
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW

from . import periods
from .build import build_return
from .checks import run_checks
from .gstr1 import Amounts
from .periods import month_end

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
    support = uow.principal.support_grant_id is not None
    out: list[ReturnOut] = []
    for q in fy_quarters(fy):
        # Only quarters that have started: a later frequency change takes effect from a
        # quarter's start, and rows made early under today's frequency would be wrong then.
        # A quarter before any frequency was chosen has no returns to show either.
        if q > today or filing_frequency_on(uow.tx, gstin, quarter_start(q)) is None:
            continue
        if support:  # a support grant is read-only (RLS refuses the insert): show what exists
            insts = periods.instances_between(uow.tx, gstin, q, month_end(quarter_months(q)[-1]))
        else:
            insts = periods.ensure_instances(uow.tx, gstin, q)
        for inst in insts:
            due = periods.due_now(uow.tx, inst)
            out.append(ReturnOut(
                instance_id=str(inst.id), form=inst.form, period=periods.period_key(inst),
                period_label=periods.period_label(inst), period_start=inst.period_start,
                period_end=inst.period_end, due_date=due.date, due_date_confirmed=due.confirmed,
                due_date_source_url=due.source_url, status=inst.status,
            ))  # fmt: skip
    return ReturnsOut(fy=fy, gstin=gstin, filing_frequency=None if current is None else current.frequency, returns=out)


# -- A built return (R1-M7 slice 5) ---------------------------------------------------------------------------------

PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]
SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn_b2b", "hsn_b2c")
PAGE = 100
BANNER = "Draft: not filed. Check every figure against your own records before you use it."
DEBIT_NOTE_NOTICE = "{n} debit note(s) are not in this return yet. They need a CA check."


class Heads(BaseModel):
    taxable_value: str
    igst: str
    cgst: str
    sgst: str
    cess: str


class SectionOut(BaseModel):
    name: Literal["b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn_b2b", "hsn_b2c"]
    rows_count: int
    totals: Heads


class TotalsOut(BaseModel):
    liability: Heads  # Tables 4A + 5 + 7 less 9B
    table_12: Heads
    gap: Heads  # liability less Table 12; zero when they agree


class FindingOut(BaseModel):
    code: str
    level: Literal["block", "warn", "info"]  # what the export will do; in this release findings only report
    message: str
    source_refs: list[str]
    subject_fp: str
    needs_ca_check: bool


class FindingGroupOut(BaseModel):
    code: str
    level: Literal["block", "warn", "info"]
    count: int
    needs_ca_check: bool


class CaFlagOut(BaseModel):
    code: str
    text: str


class DebitNotesOut(BaseModel):
    count: int
    notice: str | None  # "N debit note(s) are not in this return yet..."; null when there are none


class ReturnDetailOut(BaseModel):
    instance: ReturnOut
    draft: bool
    banner: str | None  # shown on top of the return while it is a draft
    report_only: Literal[True] = True  # findings never block in this release
    fingerprint: str
    line_items: int
    members_count: int
    totals: TotalsOut
    sections: list[SectionOut]
    debit_notes: DebitNotesOut
    ca_flags: list[CaFlagOut]  # what this return rests on that a CA has not answered
    findings: list[FindingOut]
    finding_groups: list[FindingGroupOut]


class SectionRowsOut(BaseModel):
    section: str
    rows: list[dict[str, str | int | None | list[str]]]
    has_more: bool
    next_cursor: str | None


def _s(v) -> str:
    return f"{v:f}" if isinstance(v, Decimal) else str(v)


def _heads(a) -> Heads:
    return Heads(taxable_value=_s(a.taxable_value), igst=_s(a.igst), cgst=_s(a.cgst), sgst=_s(a.sgst), cess=_s(a.cess))


def _row(r) -> dict:
    """A section row as strings, amounts flattened into the five heads, source references as a list."""
    out: dict = {}
    for f in fields(r):
        v = getattr(r, f.name)
        if f.name == "amounts":
            out.update(_heads(v).model_dump())
        elif f.name == "source_refs":
            out[f.name] = list(v)
        elif isinstance(v, (Decimal, date)):
            out[f.name] = _s(v) if isinstance(v, Decimal) else v.isoformat()
        else:
            out[f.name] = v
    return out


def _total(rows):
    total = Amounts()
    for r in rows:
        total += r.amounts
    return total


def _instance_or_404(uow: BusinessUoW, instance_id: str):
    try:
        iid = uuid.UUID(instance_id)
    except ValueError:
        raise Deny("not_found") from None
    inst = periods.get_instance(uow.tx, iid)
    if inst is None or inst.form not in ("GSTR1", "IFF"):
        raise Deny("not_found")
    return inst


@router.get("/returns/{instance_id}", dependencies=PREPARE)
def get_return(instance_id: str, uow: BusinessUoW) -> ReturnDetailOut:
    inst = _instance_or_404(uow, instance_id)
    b = build_return(uow.tx, inst)
    findings = run_checks(uow.tx, b)
    due = periods.due_now(uow.tx, inst)
    s = b.sections
    groups: dict[str, FindingGroupOut] = {}
    for f in findings:
        g = groups.get(f.code)
        groups[f.code] = FindingGroupOut(
            code=f.code, level=f.level, count=1 if g is None else g.count + 1,
            needs_ca_check=f.needs_ca_check or (g is not None and g.needs_ca_check),
        )  # fmt: skip
    return ReturnDetailOut(
        instance=ReturnOut(
            instance_id=str(inst.id), form=inst.form, period=periods.period_key(inst),
            period_label=periods.period_label(inst), period_start=inst.period_start, period_end=inst.period_end,
            due_date=due.date, due_date_confirmed=due.confirmed, due_date_source_url=due.source_url, status=inst.status,
        ),
        draft=b.draft, banner=BANNER if b.draft else None, fingerprint=b.fingerprint, line_items=b.line_items,
        members_count=len(b.members),
        totals=TotalsOut(liability=_heads(b.liability), table_12=_heads(b.hsn_total), gap=_heads(b.gap)),
        sections=[SectionOut(name=n, rows_count=len(getattr(s, n)), totals=_heads(_total(getattr(s, n))))
                  for n in SECTIONS],
        debit_notes=DebitNotesOut(
            count=b.debit_notes, notice=DEBIT_NOTE_NOTICE.format(n=b.debit_notes) if b.debit_notes else None
        ),
        ca_flags=[CaFlagOut(code=f.code, text=f.text) for f in b.ca_flags],
        findings=[FindingOut(code=f.code, level=f.level, message=f.message, source_refs=list(f.source_refs),
                             subject_fp=f.subject_fp, needs_ca_check=f.needs_ca_check) for f in findings],
        finding_groups=list(groups.values()),
    )  # fmt: skip


@router.get("/returns/{instance_id}/sections/{section}", dependencies=PREPARE)
def get_section(
    instance_id: str, section: str, uow: BusinessUoW, cursor: Annotated[str | None, Query(max_length=12)] = None
) -> SectionRowsOut:
    if section not in SECTIONS:
        raise Deny("not_found")
    inst = _instance_or_404(uow, instance_id)
    try:
        start = int(cursor) if cursor else 0
    except ValueError:
        raise Invalid("invalid_cursor", "That page marker is not valid.", field="cursor") from None
    if start < 0:
        raise Invalid("invalid_cursor", "That page marker is not valid.", field="cursor")
    rows = getattr(build_return(uow.tx, inst).sections, section)
    page = rows[start : start + PAGE]
    more = start + PAGE < len(rows)
    return SectionRowsOut(section=section, rows=[_row(r) for r in page], has_more=more,
                          next_cursor=str(start + PAGE) if more else None)
