"""The per-period gate and the one-click file button (R3-M1, R3-M2).

A business that invoices in our portal files from its own records. Before it may, for each month (or quarter, for a
quarterly filer) it confirms two things: every purchase invoice is uploaded, and every invoice is in the portal. Each
confirmation is stored against a fingerprint of the period's rows, so adding or changing a purchase or a sales document
afterwards makes it stale and the business confirms again. The button is open only when the period has ended (the filing
period starts the day after it ends) and both confirmations stand. The server decides; the screen only shows it.

The due date is the one refdata holds for the period's GSTR-1 (D-106: shown whether or not the row is confirmed yet). No
other date is made up here.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import text

from app.modules.business.interface import channels, get_profile, quarter_months
from app.modules.imports.interface import missing_platform_months
from platform_common import audit
from platform_common.errors import Conflict
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import period_files, periods

ITEMS = ("purchases_uploaded", "invoices_in_portal")
CLOSED_MESSAGE = "This period is not ready to file yet."


@dataclass(frozen=True)
class Confirmation:
    item: str
    confirmed: bool  # the latest answer says yes
    stale: bool  # said yes, but the period's rows have changed since
    at: datetime | None


@dataclass(frozen=True)
class Gate:
    kind: str
    period_start: date
    period_end: date
    ended: bool
    opens_on: date  # the filing period starts the day after the period ends
    confirmations: tuple[Confirmation, ...]
    reasons: tuple[str, ...]  # codes, empty when the button is open
    platform_files: tuple  # (platform, months missing) for each marketplace the business sells on and lacks files for
    gstr1_returns: tuple  # return instances (GSTR-1, IFF) of the period, when they exist
    due_date: date | None  # from refdata; None means no return instance or no date: "check on the GST portal"

    @property
    def can_file(self) -> bool:
        return not self.reasons


class _Answer(NamedTuple):
    confirmed: bool
    fingerprint: str
    at: datetime


def _latest(tx, business: uuid.UUID, kind: str, start: date) -> dict[str, _Answer]:
    rows = tx.execute(
        text("select distinct on (item) item, confirmed, data_fingerprint, created_at from filing.period_confirmations"
             " where business_id = :b and kind = :k and period_start = :s order by item, created_at desc, id desc"),
        {"b": business, "k": kind, "s": start}).all()
    return {r.item: _Answer(r.confirmed, r.data_fingerprint, r.created_at) for r in rows}


def _confirmation(item: str, answer: _Answer | None, fp: str | None) -> Confirmation:
    if answer is None:
        return Confirmation(item, False, False, None)
    return Confirmation(item, answer.confirmed, answer.confirmed and answer.fingerprint != fp, answer.at)


def status(uow: UnitOfWork, kind: str, start: date, today: date) -> Gate:
    tx = uow.tx
    business = uow.principal.business_id
    period = period_files.period_of(tx, kind, start, today, require_ended=False)
    ended = period.end < today
    got = _latest(tx, business, kind, start)
    fp = period_files.data_fingerprint(tx, period, today)[0] if got else None
    confirmations = tuple(_confirmation(item, got.get(item), fp) for item in ITEMS)
    reasons: list[str] = []
    if not ended:
        reasons.append("period_not_ended")
    for c in confirmations:
        if not c.confirmed:
            reasons.append(f"{c.item}_missing")
        elif c.stale:
            reasons.append(f"{c.item}_stale")
    missing = _platform_gaps(uow, period)
    if missing:
        reasons.append("platform_files_missing")
    profile = get_profile(tx)
    found = periods.instances_between(tx, profile.gstin if profile else None, period.start, period.end)
    mine = tuple(i for i in found if i.form in ("GSTR1", "IFF") and i.period_end <= period.end)
    due = None
    if mine:
        d = periods.due_now(tx, next((i for i in mine if i.form == "GSTR1"), mine[0]))
        due = d.date  # shown whenever refdata has one (D-106, issue #424)
    return Gate(kind, period.start, period.end, ended, period.end + timedelta(days=1), confirmations,
                tuple(reasons), tuple(sorted(missing.items())), mine, due)


def _platform_gaps(uow: UnitOfWork, period) -> dict[str, list[str]]:
    """R3-M4: a business that also sells on Amazon, Flipkart or Meesho (chosen in Business setup) needs each platform's files
    for every month of the period, or a note that the platform had no sales that month. Read from uploads, not attested."""
    chosen = channels(uow.tx)
    platforms = [p for p in ("amazon", "flipkart", "meesho") if getattr(chosen, p)]
    months = list(quarter_months(period.start)) if period.kind == "quarter" else [period.start]
    return missing_platform_months(uow, platforms, months)


def confirm(uow: UnitOfWork, kind: str, start: date, item: str, confirmed: bool, today: date) -> Gate:
    """Records the business's answer for one item. Only a finished period can be confirmed: its rows are not final before."""
    if item not in ITEMS:
        raise Conflict("gate_item_invalid", "Choose one of the two confirmations")
    tx = uow.tx
    business = uow.principal.business_id
    period = period_files.period_of(tx, kind, start, today)  # refuses a period that has not ended
    fp, _, _ = period_files.data_fingerprint(tx, period, today)
    profile = get_profile(tx)
    row_id = uuid7()
    tx.execute(
        text("insert into filing.period_confirmations (id, business_id, gstin, kind, period_start, item, confirmed,"
             " data_fingerprint, created_by) values (:i, :b, :g, :k, :s, :it, :c, :f, :me)"),
        {"i": row_id, "b": business, "g": profile.gstin, "k": kind, "s": period.start, "it": item, "c": confirmed,
         "f": fp, "me": uow.principal.user_id})
    audit.record(uow, "filing.period_confirmation", "period_confirmation", row_id,
                 data={"kind": kind, "period": f"{period.start:%Y-%m}", "item": item, "confirmed": confirmed})
    return status(uow, kind, start, today)


def open_file(uow: UnitOfWork, kind: str, start: date, today: date) -> Gate:
    """The button. Refused with the reasons while the gate is closed; otherwise the period's return instances exist and are
    returned, and the screen takes the business to the GSTR-1 file of each."""
    gate = status(uow, kind, start, today)
    if not gate.can_file:
        raise Conflict("period_gate_closed", CLOSED_MESSAGE)
    profile = get_profile(uow.tx)
    periods.ensure_instances(uow.tx, profile.gstin, gate.period_start)
    gate = status(uow, kind, start, today)
    audit.record(uow, "filing.period_file_opened", "period", uuid7(),
                 data={"kind": kind, "period": f"{gate.period_start:%Y-%m}"})
    return gate


def invoices_in_portal(tx) -> bool:
    """True once the business has an own invoice here: a finalized one (sales.v_filing_lines) or a practice one
    (sales.v_practice_documents). Both views are security_invoker, so this reads the bound business only."""
    return bool(tx.execute(text(
        "select exists (select 1 from sales.v_filing_lines where business_id = nullif(current_setting("
        "'app.tenant_id', true), '')::uuid) or exists (select 1 from sales.v_practice_documents where business_id ="
        " nullif(current_setting('app.tenant_id', true), '')::uuid)")).scalar())


def assert_open_for_instance(uow: UnitOfWork, instance, today: date) -> None:
    """The file of a return is made only through the gate, for a business that invoices in our portal (it has own
    invoices, finalized or practice, D-095). A marketplace seller with none files as in R1, whatever its business type.
    GSTR-3B has no file here, so it is not gated."""
    if instance.form not in ("GSTR1", "IFF"):
        return
    if not invoices_in_portal(uow.tx):
        return
    kind = "month" if instance.period_start.month == instance.period_end.month else "quarter"
    if not status(uow, kind, instance.period_start, today).can_file:
        raise Conflict("period_gate_closed", CLOSED_MESSAGE)
