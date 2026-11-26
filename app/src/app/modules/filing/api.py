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

from sqlalchemy import text
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field

from app.modules.business.interface import (
    FrequencyRowOut,
    add_frequency_row,
    filing_frequency_on,
    frequency_row_out,
    fy_of,
    fy_quarters,
    get_profile,
    is_fy,
    quarter_months,
    quarter_start,
)
from platform_common.clock import Clock, get_clock
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.idempotency import run_once
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import acceptance, export_job, lock, period_gate, periods, plans
from .build import build_return
from .checks import run_checks
from .gate import accepted_key, export_gate
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
    filed_on: date | None = None  # when the user filed it on the portal, once it is locked
    arn: str | None = None  # the acknowledgement number they gave


def _filed_on_arn(tx, inst) -> dict:
    """The date and ARN of a locked return's `filed` event (the latest, after a relock); empty otherwise."""
    if inst.status != "filed_locked":
        return {}
    r = tx.execute(
        text(
            "select filed_on, arn from filing.instance_events where instance_id = :i and kind = 'filed'"
            " order by at desc, id desc limit 1"
        ),
        {"i": inst.id},
    ).first()
    return {} if r is None else {"filed_on": r.filed_on, "arn": r.arn}


class ReturnsOut(BaseModel):
    fy: str
    gstin: str | None
    filing_frequency: Literal["monthly", "quarterly"] | None  # in force today; None: not set
    returns: list[ReturnOut]


@router.get("/returns", dependencies=[Depends(require(Permission.RETURNS_VIEW, support_may_read=True))])
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
                due_date_source_url=due.source_url, status=inst.status, **_filed_on_arn(uow.tx, inst),
            ))  # fmt: skip
    return ReturnsOut(fy=fy, gstin=gstin, filing_frequency=None if current is None else current.frequency, returns=out)


# -- Filing frequency (LLD-5 §11, L5-9, AC5-24, AC5-26; issue #476) ---------------------------------------------------


class FrequencyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    frequency: Literal["monthly", "quarterly"]
    effective_from: date  # a quarter's first day


class FrequencyOut(BaseModel):
    row: FrequencyRowOut
    warnings: list[str]
    superseded_instances: list[str]  # the empty returns this change replaced; reads make the new ones


@router.post("/filing-profile/frequency", status_code=201,
             dependencies=[Depends(require(Permission.SETTINGS_EDIT))])
def post_frequency(
    body: FrequencyIn,
    request: Request,
    uow: BusinessUoW,
    clock: Today,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> FrequencyOut:
    """Record a filing frequency (business keeps every rule: L1-13, the rule 61A warnings, insert-only history),
    then supersede the open, empty returns from its start on that were made for the other frequency, so the
    returns list shows the new frequency's returns (with their due dates) on its next read. A quarter whose
    replaced returns hold documents or saved work, or are filed, skipped or unlocked, refuses the change: 409
    `quarter_has_documents`, and nothing is written (the history row rolls back with the transaction)."""

    def choose() -> dict:
        profile = get_profile(uow.tx)
        gstin = None if profile is None else profile.gstin
        row, warnings = add_frequency_row(uow, gstin, body.frequency, body.effective_from, today=clock.today())
        stale = periods.mismatched(uow.tx, row.gstin, row.effective_from)
        held = [m.instance for m in stale if m.blocked]
        if not held:
            done, held = periods.supersede(uow.tx, [m.instance for m in stale], uow.principal.user_id)
        if held:
            q = quarter_start(min(i.period_start for i in held))
            raise Conflict(
                "quarter_has_documents",
                f"The quarter starting {q:%d-%b-%Y} already has invoices, saved work or a filed return, so the"
                " frequency can't change for it. Choose a later quarter.",
            )
        return FrequencyOut(row=frequency_row_out(row), warnings=warnings,
                            superseded_instances=[str(i) for i in done]).model_dump(mode="json")

    return run_once(
        uow.tx,
        uow.principal.business_id,
        idempotency_key,
        method=request.method,
        route=request.scope["route"].path,
        payload=body.model_dump(mode="json"),
        operation=choose,
    )


# -- A built return (R1-M7 slice 5) ---------------------------------------------------------------------------------

PREPARE = [Depends(require(Permission.RETURNS_PREPARE))]
SECTIONS = ("b2b", "b2cl", "b2cs", "cdnr", "cdnur", "hsn_b2b", "hsn_b2c")
PAGE = 100
BANNER = "Draft: not filed. Check every figure against your own records before you use it."
DEBIT_NOTE_NOTICE = ("{n} debit note(s) uploaded before debit notes were supported are not in this return yet."
                     " They need a CA check.")


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
    accepted: bool  # a warning accepted as it is now; a block or an information finding is never "accepted"


class FindingGroupOut(BaseModel):
    code: str
    accepted: int  # how many of its items are accepted
    level: Literal["block", "warn", "info"]
    count: int
    needs_ca_check: bool


class CaFlagOut(BaseModel):
    code: str
    text: str


class DebitNotesOut(BaseModel):
    count: int
    notice: str | None  # "N debit note(s) are not in this return yet..."; null when there are none


class ReasonOut(BaseModel):
    code: Literal["not_open", "blocks", "debit_notes", "reconciliation"]
    message: str


class ExportGateOut(BaseModel):
    """Whether an export could start now, and why not (R1-M8). Nothing is exported by this read."""

    ready: bool
    reasons: list[ReasonOut]
    to_accept: int  # warnings still waiting for an acceptance


class AcceptFindingIn(BaseModel):
    check_code: str = Field(pattern=r"^[A-Z]-[0-9]{2}$")
    subject_fp: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )  # none: every current warning with this code
    note: str = Field(min_length=1, max_length=500)  # why it is accepted: kept with who and when


class ExportRef(BaseModel):
    job_id: str


class ExportFileOut(BaseModel):
    part: int
    rows: int
    size_bytes: int
    url: str  # good for 60 seconds


class ExportStatusOut(BaseModel):
    status: Literal["preparing", "ready", "failed"]
    error_code: str | None = None  # when failed: changed_during_export, not_ready, file_too_large, not_allowed, ...
    version: int | None = None  # when ready: the snapshot's version
    files: list[ExportFileOut] = []
    not_in_file: list[str] = []  # tables the file does not carry yet, to be entered on the portal
    unverified_tables: list[str] = []  # tables written without a tool sample behind them
    portal_tested: bool = False  # false until a file like this has been accepted by the portal (the test upload)
    ready_to_upload: bool = False  # true only when portal_tested and no table is unverified


class AcceptFindingOut(BaseModel):
    check_code: str
    accepted: int  # newly recorded; saying it again records nothing


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
    export: ExportGateOut


class RowBase(Heads):
    """Every section row: the five heads (strings) and where the figures came from (file and row)."""

    source_refs: list[str]


class B2BRowOut(RowBase):
    recipient_gstin: str
    recipient_name: str | None
    invoice_number: str
    invoice_date: str
    invoice_value: str
    pos_state_code: str
    rate: str


class B2CLRowOut(RowBase):
    invoice_number: str
    invoice_date: str
    invoice_value: str
    pos_state_code: str
    rate: str


class B2CSRowOut(RowBase):
    pos_state_code: str
    rate: str


class CDNRRowOut(RowBase):
    recipient_gstin: str
    recipient_name: str | None
    note_number: str
    note_date: str
    note_value: str
    pos_state_code: str
    rate: str
    original_doc_number: str | None
    original_doc_date: str | None
    note_type: str


class CDNURRowOut(RowBase):
    note_number: str
    note_date: str
    note_value: str
    pos_state_code: str
    rate: str
    original_doc_number: str | None
    original_doc_date: str | None
    note_type: str
    ur_type: str


class HSNRowOut(RowBase):
    hsn: str
    uqc: str
    rate: str
    quantity: str


class _Page(BaseModel):
    has_more: bool
    next_cursor: str | None
    fingerprint: str  # of the build these rows came from: a screen must not mix pages with different ones


class B2BPage(_Page):
    section: Literal["b2b"]
    rows: list[B2BRowOut]


class B2CLPage(_Page):
    section: Literal["b2cl"]
    rows: list[B2CLRowOut]


class B2CSPage(_Page):
    section: Literal["b2cs"]
    rows: list[B2CSRowOut]


class CDNRPage(_Page):
    section: Literal["cdnr"]
    rows: list[CDNRRowOut]


class CDNURPage(_Page):
    section: Literal["cdnur"]
    rows: list[CDNURRowOut]


class HsnB2bPage(_Page):
    section: Literal["hsn_b2b"]
    rows: list[HSNRowOut]


class HsnB2cPage(_Page):
    section: Literal["hsn_b2c"]
    rows: list[HSNRowOut]


SectionRowsOut = Annotated[
    B2BPage | B2CLPage | B2CSPage | CDNRPage | CDNURPage | HsnB2bPage | HsnB2cPage, Field(discriminator="section")
]
_PAGES = {
    "b2b": B2BPage, "b2cl": B2CLPage, "b2cs": B2CSPage, "cdnr": CDNRPage, "cdnur": CDNURPage,
    "hsn_b2b": HsnB2bPage, "hsn_b2c": HsnB2cPage,
}  # fmt: skip


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


def _any_instance_or_404(uow: BusinessUoW, instance_id: str):
    """This business's instance of any form (GSTR-3B included), for marking it filed outside Kartaa or unlocking it."""
    try:
        iid = uuid.UUID(instance_id)
    except ValueError:
        raise Deny("not_found") from None
    inst = periods.get_instance(uow.tx, iid)
    if inst is None:  # another business's instance is not found either (RLS and the bound business)
        raise Deny("not_found")
    return inst


@router.get("/returns/{instance_id}", dependencies=PREPARE)
def get_return(instance_id: str, uow: BusinessUoW) -> ReturnDetailOut:
    inst = _instance_or_404(uow, instance_id)
    b = build_return(uow.tx, inst)
    findings = run_checks(uow.tx, b)
    due = periods.due_now(uow.tx, inst)
    s = b.sections
    accepted = acceptance.accepted_set(uow.tx, inst.id)
    gate = export_gate(inst, b, findings, accepted)

    def _acc(f) -> bool:
        return f.level == "warn" and accepted_key(f) in accepted

    groups: dict[str, FindingGroupOut] = {}
    for f in findings:
        g = groups.get(f.code)
        groups[f.code] = FindingGroupOut(
            code=f.code, level=f.level, count=1 if g is None else g.count + 1,
            needs_ca_check=f.needs_ca_check or (g is not None and g.needs_ca_check),
            accepted=(0 if g is None else g.accepted) + _acc(f),
        )  # fmt: skip
    return ReturnDetailOut(
        instance=ReturnOut(
            instance_id=str(inst.id), form=inst.form, period=periods.period_key(inst),
            period_label=periods.period_label(inst), period_start=inst.period_start, period_end=inst.period_end,
            due_date=due.date, due_date_confirmed=due.confirmed, due_date_source_url=due.source_url, status=inst.status,
            **_filed_on_arn(uow.tx, inst),
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
                             subject_fp=f.subject_fp, needs_ca_check=f.needs_ca_check, accepted=_acc(f)) for f in findings],
        finding_groups=list(groups.values()),
        export=ExportGateOut(ready=gate.ready, reasons=[ReasonOut(code=r.code, message=r.message) for r in gate.reasons],
                             to_accept=gate.to_accept),
    )  # fmt: skip


@router.post("/returns/{instance_id}/check-acceptances", dependencies=PREPARE)
def accept_finding(instance_id: str, body: AcceptFindingIn, uow: BusinessUoW) -> AcceptFindingOut:
    inst = _instance_or_404(uow, instance_id)
    if inst.status != "open":
        raise Conflict("return_not_open", "This return is not open, so nothing can be accepted on it.")
    findings = run_checks(uow.tx, build_return(uow.tx, inst))
    n = acceptance.accept(uow, inst, findings, body.check_code, body.subject_fp, body.note)
    return AcceptFindingOut(check_code=body.check_code, accepted=n)


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
    b = build_return(uow.tx, inst)
    rows = getattr(b.sections, section)
    page = rows[start : start + PAGE]
    more = start + PAGE < len(rows)
    return _PAGES[section](section=section, rows=[_row(r) for r in page], has_more=more,
                           next_cursor=str(start + PAGE) if more else None, fingerprint=b.fingerprint)  # fmt: skip


@router.post("/returns/{instance_id}/exports", dependencies=PREPARE, status_code=http.HTTP_202_ACCEPTED)
def start_export(instance_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]) -> ExportRef:
    """Queues the file of this return as it is now. Refused (409) when it is not ready, not allowed for the plan or cannot be
    written as a file; asking again for an unchanged return gives the same job."""
    inst = _instance_or_404(uow, instance_id)
    period_gate.assert_open_for_instance(uow, inst, clock.today())  # R3: a business that invoices here files through the gate
    return ExportRef(job_id=str(export_job.start(uow, inst.id)))


@router.get("/returns/{instance_id}/exports/{job_id}", dependencies=PREPARE)
def export_status(instance_id: str, job_id: str, uow: BusinessUoW) -> ExportStatusOut:
    inst = _instance_or_404(uow, instance_id)
    return ExportStatusOut(**export_job.status(uow, inst.id, parse_id(job_id)))


class PlanOut(BaseModel):
    name: str
    monthly_rupees: int
    quarterly_rupees: int
    gst_note: str
    free_for_now: bool  # true while payments are a placeholder: nothing is charged


@router.get("/plan", dependencies=PREPARE)
def get_plan() -> PlanOut:
    """The GST-filing plan and its prices, and whether it is free for now (`plans.FREE_FOR_NOW`). Read-only; nothing is charged."""
    return PlanOut(
        name="GST filing",
        monthly_rupees=plans.FILING_ONLY["monthly"],
        quarterly_rupees=plans.FILING_ONLY["quarterly"],
        gst_note=plans.GST_NOTE,
        free_for_now=plans.FREE_FOR_NOW,
    )


# -- Mark filed, lock, unlock (R1-M8 slice 5) --------------------------------------------------------------------

LOCK = [Depends(require(Permission.RETURNS_LOCK))]
UNLOCK = [Depends(require(Permission.RETURNS_UNLOCK))]


class AcceptChangedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class FiledIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filed_on: date
    arn: str
    accept_changed: AcceptChangedIn | None = None  # what was filed differs from the file we made, and why


class FiledOut(BaseModel):
    status: Literal["filed_locked"]
    filed_on: date
    arn: str
    snapshot_version: int
    changed_since_export: bool
    has_file: bool  # a file of the locked return is kept and can be downloaded again


class DocumentRef(BaseModel):
    section: str
    number: str


class DifferenceOut(BaseModel):
    added: list[DocumentRef]
    removed: list[DocumentRef]
    changed: list[DocumentRef]
    summaries: list[str]  # summary tables (B2CS, HSN) whose figures differ


class SnapshotRefOut(BaseModel):
    purpose: Literal["export", "lock"]
    version: int


class ChangesOut(BaseModel):
    reference: SnapshotRefOut | None  # the file the user took, or None when no file was made yet
    same: bool
    difference: DifferenceOut


class UnlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class UnlockOut(BaseModel):
    status: Literal["unlocked"]


@router.get("/returns/{instance_id}/changes", dependencies=LOCK)
def changes_since_export(instance_id: str, uow: BusinessUoW) -> ChangesOut:
    """The return as it is now against the file the user took, by document number, for the confirm step of marking filed."""
    inst = _instance_or_404(uow, instance_id)
    return ChangesOut(**lock.changes(uow, inst.id))


@router.post("/returns/{instance_id}/filed", dependencies=LOCK)
def mark_filed(instance_id: str, body: FiledIn, uow: BusinessUoW, clock: Today) -> FiledOut:
    """Records the filing and locks the return as it is now. 409 `changed_since_export` when it differs from the file the user
    took, unless `accept_changed` gives a reason; 409 `period_not_open` when it is already locked."""
    inst = _instance_or_404(uow, instance_id)
    reason = None if body.accept_changed is None else body.accept_changed.reason
    return FiledOut(**lock.mark_filed(uow, inst.id, body.filed_on, body.arn, reason, clock.today()))


class CompletedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filed_on: date
    arn: str


class CompletedOut(BaseModel):
    status: Literal["filed_locked"]
    filed_on: date
    arn: str


@router.post("/returns/{instance_id}/completed", dependencies=LOCK)
def mark_completed(instance_id: str, body: CompletedIn, uow: BusinessUoW, clock: Today) -> CompletedOut:
    """The user filed this return on the GST portal outside Kartaa (issue #424): any form, GSTR-3B included. A GSTR-1 or
    IFF is locked as it is now with the reason "Filed outside Kartaa"; 409 `period_not_open` when it is already locked."""
    inst = _any_instance_or_404(uow, instance_id)
    return CompletedOut(**lock.mark_completed_outside(uow, inst.id, body.filed_on, body.arn, clock.today()))


@router.get("/returns/{instance_id}/lock-file", dependencies=PREPARE)
def lock_file(instance_id: str, uow: BusinessUoW) -> ExportStatusOut:
    """The file of a locked return, from its lock snapshot, with 60-second links."""
    inst = _instance_or_404(uow, instance_id)
    return ExportStatusOut(**lock.lock_files(uow, inst.id))


@router.post("/returns/{instance_id}/unlock", dependencies=UNLOCK)
def unlock_return(instance_id: str, body: UnlockIn, uow: BusinessUoW) -> UnlockOut:
    """Owner only, with a reason. The snapshots stay; marking filed again is a relock. Any form: a GSTR-3B marked
    completed outside Kartaa by mistake is unlocked the same way (#424)."""
    inst = _any_instance_or_404(uow, instance_id)
    return UnlockOut(**lock.unlock(uow, inst.id, body.reason))
