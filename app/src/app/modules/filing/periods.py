"""Return instances and assignment (LLD-5 §4, §8; LLD-4 §11, L4-12; HLD §5.4).

One return instance per GSTIN, form and period, created lazily from the filing frequency
(business.filing_frequency_on) and the due dates in refdata (refdata/values/returns.yaml).
Finalize calls `target_return_instance` and then `assert_period_open` in its transaction,
before allocating a number (agreed with Staff 2 (4) for F2).

Every query names the bound business as well as relying on RLS (defence in depth).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.business.interface import (
    add_months,
    filing_frequency_on,
    fy_quarter_label,
    gstin_state,
    quarter_months,
    quarter_start,
)
from app.modules.refdata import provenance_on, value_on
from platform_common.clock import Clock
from platform_common.errors import Conflict
from platform_common.ids import uuid7

BOUND = "business_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
Form = Literal["GSTR1", "IFF", "GSTR3B", "PMT06"]
FORM_ORDER = ("IFF", "PMT06", "GSTR1", "GSTR3B")
# Classes an IFF carries: B2B invoices and registered credit notes (LLD-5 §4 step 2).
IFF_CLASSES = ("B2B", "CDNR")


class PeriodLocked(Conflict):
    """The covering return is filed and locked (or unlocked): 409 (LLD-5 §4)."""

    code = "period_locked"  # Conflict is 409


@dataclass(frozen=True)
class ReturnInstance:
    id: uuid.UUID
    gstin: str
    form: Form
    period: str  # 'YYYY-MM' of period_end, as documents.return_period
    period_start: date
    period_end: date
    due_date: date | None  # None only for a quarterly GSTR-3B with no date (state 97)
    status: str
    rolled_forward_from: uuid.UUID | None = None  # L5-4: the locked instance a credit note skipped


@dataclass(frozen=True)
class DocumentRef:
    """A credit note's original, for the audit row only (LLD-5 §4 step 5)."""

    id: uuid.UUID
    doc_number: str
    doc_date: date


@dataclass(frozen=True)
class _Spec:
    form: Form
    frequency: Literal["monthly", "quarterly"]
    start: date
    end: date
    due_key: str


# -- Periods and due dates (pure apart from the refdata reads) ----------------------------


def month_end(first: date) -> date:
    return add_months(first, 1) - timedelta(days=1)


def specs(filer: Literal["monthly", "qrmp"], on: date) -> list[_Spec]:
    """The instances of `on`'s quarter for a filer (LLD-5 §8 ensure_instances)."""
    months = quarter_months(on)
    if filer == "monthly":
        return [
            _Spec(form, "monthly", m, month_end(m), f"due.{form.lower()}.monthly.day")
            for m in months
            for form in ("GSTR1", "GSTR3B")
        ]
    q_start, q_end = months[0], month_end(months[-1])
    return [
        *(_Spec("IFF", "monthly", m, month_end(m), "due.iff.day") for m in months[:-1]),
        *(_Spec("PMT06", "monthly", m, month_end(m), "due.pmt06.day") for m in months[:-1]),
        _Spec("GSTR1", "quarterly", q_start, q_end, "due.gstr1.quarterly.day"),
        _Spec("GSTR3B", "quarterly", q_start, q_end, "due.gstr3b.quarterly"),
    ]


@dataclass(frozen=True)
class Due:
    date: date | None  # None: no date exists (state 97 quarterly GSTR-3B); never a guess
    ref: str
    confirmed: bool  # the refdata row in force is expert- or CA-confirmed
    source_url: str | None


def due_date(tx: Session, spec: _Spec, gstin: str) -> Due:
    """Day N of the month after the period, N from refdata in force on the period's last
    day. The quarterly GSTR-3B day follows the GSTIN's state group; a state in neither
    group (97) has no due date: date None (refdata-lld4.md §3)."""
    key = spec.due_key
    if key == "due.gstr3b.quarterly":
        state = gstin_state(gstin)
        for group in ("group_a", "group_b"):
            states = value_on(tx, f"{key}.{group}.states", spec.end)
            if state in {s.strip() for s in states.split(",")}:
                key = f"{key}.{group}.day"
                break
        else:
            return Due(None, f"{key}.group: no group for state {state}", False, None)
    day = value_on(tx, key, spec.end)
    confirmed, url = provenance_on(tx, key, spec.end)
    following = add_months(spec.end, 1)
    return Due(following.replace(day=day), f"{key} on {spec.end.isoformat()}", confirmed, url or None)


# -- Instances ----------------------------------------------------------------------------

_COLUMNS = "id, gstin, form, return_period, period_start, period_end, due_date, status"


def _instance(r, rolled_forward_from=None) -> ReturnInstance:
    return ReturnInstance(
        r.id, r.gstin, r.form, r.return_period, r.period_start, r.period_end, r.due_date, r.status,
        rolled_forward_from,
    )  # fmt: skip


def filer_on(tx: Session, gstin: str, on: date) -> Literal["monthly", "qrmp"]:
    row = filing_frequency_on(tx, gstin, on)
    if row is None:
        raise Conflict("filing_frequency_not_set", "Set your GST filing frequency first")
    return "qrmp" if row.frequency == "quarterly" else "monthly"


def ensure_instances(tx: Session, gstin: str, on: date) -> list[ReturnInstance]:
    """Create `on`'s quarter's instances if missing (two callers at once both succeed:
    ON CONFLICT DO NOTHING) and return them, in period and form order."""
    filer = filer_on(tx, gstin, quarter_start(on))
    for spec in specs(filer, on):
        due = due_date(tx, spec, gstin)
        tx.execute(
            text(
                "insert into filing.return_instances (id, business_id, gstin, form, frequency, filer_frequency,"
                " period_start, period_end, return_period, due_date, due_date_ref)"
                " values (:id, nullif(current_setting('app.tenant_id', true), '')::uuid, :g, :form, :freq, :filer,"
                " :start, :end, :period, :due, :ref)"
                " on conflict (business_id, gstin, form, period_start) where status <> 'superseded' do nothing"
            ),
            dict(id=uuid7(), g=gstin, form=spec.form, freq=spec.frequency, filer=filer, start=spec.start,
                 end=spec.end, period=spec.end.strftime("%Y-%m"), due=due.date, ref=due.ref),
        )  # fmt: skip
    return instances_between(tx, gstin, quarter_start(on), month_end(quarter_months(on)[-1]))


def instances_between(tx: Session, gstin: str | None, start: date, end: date) -> list[ReturnInstance]:
    rows = tx.execute(
        text(
            f"select {_COLUMNS} from filing.return_instances where {BOUND} and status <> 'superseded'"
            " and (cast(:g as text) is null or gstin = :g) and period_start between :s and :e"
        ),
        {"g": gstin, "s": start, "e": end},
    ).all()
    return sorted((_instance(r) for r in rows), key=lambda i: (i.period_start, FORM_ORDER.index(i.form), i.gstin))


def _lock(tx: Session, gstin: str, form: str, start: date, mode: str):
    """The live instance row, locked; created first (with its quarter) if missing."""
    sql = text(
        f"select {_COLUMNS}, iff_b2b_taxable from filing.return_instances where {BOUND}"
        " and gstin = :g and form = :f and period_start = :s and status <> 'superseded' " + mode
    )
    args = {"g": gstin, "f": form, "s": start}
    r = tx.execute(sql, args).one_or_none()
    if r is None:
        ensure_instances(tx, gstin, start)
        r = tx.execute(sql, args).one()
    return r


def _covering(
    tx: Session, gstin: str, kind: str, on: date, supply_class: str, taxable_value: Decimal | None, today: date
) -> ReturnInstance:
    """LLD-5 §4 steps 1-3: the instance covering `on` for this document, locked FOR SHARE
    (FOR UPDATE on an IFF that takes an invoice, which serialises the cap per IFF)."""
    filer = filer_on(tx, gstin, quarter_start(on))
    months = quarter_months(on)
    month = date(on.year, on.month, 1)
    if filer == "monthly":
        return _instance(_lock(tx, gstin, "GSTR1", month, "for share"))
    if supply_class in IFF_CLASSES and month != months[-1]:
        takes_cap = kind == "invoice"
        if takes_cap and taxable_value is None:
            raise ValueError("taxable_value is required for a QRMP B2B invoice in an IFF month (L5-3)")
        iff = _lock(tx, gstin, "IFF", month, "for update" if takes_cap else "for share")
        fits = not takes_cap or iff.iff_b2b_taxable + taxable_value <= value_on(tx, "iff.max_taxable_value", on)
        if iff.status == "open" and today <= iff.due_date and fits:  # an IFF always has a date
            if takes_cap:
                tx.execute(
                    text(
                        f"update filing.return_instances set iff_b2b_taxable = iff_b2b_taxable + :v"
                        f" where {BOUND} and id = :id"
                    ),
                    {"v": taxable_value, "id": iff.id},
                )
            return _instance(iff)
    return _instance(_lock(tx, gstin, "GSTR1", months[0], "for share"))


def target_return_instance(
    tx: Session,
    gstin: str,
    kind: Literal["invoice", "credit_note"],
    doc_date: date,
    supply_class: str,
    original: DocumentRef | None = None,
    *,
    taxable_value: Decimal | None = None,
    today: date | None = None,
) -> ReturnInstance:
    """The return a document is assigned to, set once at finalize (LLD-5 §4, HLD §5.4).
    `taxable_value`: the invoice's taxable total, for the IFF cap (L5-3). Raises
    PeriodLocked when the covering return is not open and the dated treatment row
    (`filing.locked_return_treatment` for invoices, `filing.credit_note_locked_treatment`
    for credit notes, L5-4) does not roll it forward to an open return covering today."""
    today = today or Clock().today()
    inst = _covering(tx, gstin, kind, doc_date, supply_class, taxable_value, today)
    if inst.status == "open":
        return inst
    key = "filing.credit_note_locked_treatment" if kind == "credit_note" else "filing.locked_return_treatment"
    # The treatment in force when the document is finalized (today), not on its date.
    if value_on(tx, key, today) == "roll_forward":
        now = _covering(tx, gstin, kind, today, supply_class, taxable_value, today)
        if now.status == "open" and now.id != inst.id:
            return ReturnInstance(**{**now.__dict__, "rolled_forward_from": inst.id})
    raise PeriodLocked("period_locked", f"Your {_label(inst)} return is already filed. Ask your CA what to do.")


def assert_period_open(tx: Session, instance_id: uuid.UUID) -> None:
    """FOR SHARE on the instance (mark filed and unlock take FOR UPDATE, so finalize and
    lock serialise); raises PeriodLocked unless it is open."""
    r = tx.execute(
        text(f"select {_COLUMNS} from filing.return_instances where {BOUND} and id = :id for share"),
        {"id": instance_id},
    ).one_or_none()
    if r is None:
        raise LookupError(f"return instance {instance_id} is not this business's")
    if r.status != "open":
        raise PeriodLocked("period_locked", f"Your {_label(_instance(r))} return is already filed.")


def _label(inst: ReturnInstance) -> str:
    form = {"GSTR1": "GSTR-1", "IFF": "IFF", "GSTR3B": "GSTR-3B", "PMT06": "PMT-06"}[inst.form]
    return f"{form} {period_label(inst)}"


_DUE_KEY = {
    ("GSTR1", "monthly"): "due.gstr1.monthly.day",
    ("GSTR1", "quarterly"): "due.gstr1.quarterly.day",
    ("GSTR3B", "monthly"): "due.gstr3b.monthly.day",
    ("GSTR3B", "quarterly"): "due.gstr3b.quarterly",
    ("IFF", "monthly"): "due.iff.day",
    ("PMT06", "monthly"): "due.pmt06.day",
}


def due_now(tx: Session, inst: ReturnInstance) -> Due:
    """The due date from refdata as it stands now (an extension is a dated refdata row,
    so reads show it without touching stored instances)."""
    freq = "quarterly" if inst.period_start.month != inst.period_end.month else "monthly"
    spec = _Spec(inst.form, freq, inst.period_start, inst.period_end, _DUE_KEY[(inst.form, freq)])
    return due_date(tx, spec, inst.gstin)


def period_key(inst: ReturnInstance) -> str:
    """'2026-10' for a month; '2026-Q3' for a quarter (FY start year, Q1 = Apr-Jun)."""
    if inst.period_start.month == inst.period_end.month:
        return inst.period
    return fy_quarter_label(inst.period_start)


def period_label(inst: ReturnInstance) -> str:
    if inst.period_start.month == inst.period_end.month:
        return f"{inst.period_start:%b %Y}"
    return f"{inst.period_start:%b}–{inst.period_end:%b %Y}"
