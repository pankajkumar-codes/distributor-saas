"""The per-period gate and the one-click file button (R3-M1, R3-M2).

A business that invoices in our portal files from its own records. Before it may, for each month (or quarter, for a
quarterly filer) it confirms two things: every purchase invoice is uploaded, and every invoice is in the portal. Each
confirmation is stored against a fingerprint of the period's rows, so adding or changing a purchase or a sales document
afterwards makes it stale and the business confirms again. The button is open only when the period has ended (the filing
period starts the day after it ends) and both confirmations stand. The server decides; the screen only shows it.

The due date is shown only when the refdata row in force is confirmed. No other date is made up here.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import text

from app.modules.business.interface import get_profile
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
    gstr1_returns: tuple  # return instances (GSTR-1, IFF) of the period, when they exist
    due_date: date | None  # only a confirmed date; None means "check on the GST portal"

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
    profile = get_profile(tx)
    found = periods.instances_between(tx, profile.gstin if profile else None, period.start, period.end)
    mine = tuple(i for i in found if i.form in ("GSTR1", "IFF") and i.period_end <= period.end)
    due = None
    if mine:
        d = periods.due_now(tx, next((i for i in mine if i.form == "GSTR1"), mine[0]))
        due = d.date if d.confirmed else None
    return Gate(kind, period.start, period.end, ended, period.end + timedelta(days=1), confirmations,
                tuple(reasons), mine, due)


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


def assert_open_for_instance(uow: UnitOfWork, instance, today: date) -> None:
    """The file of a return is made only through the gate, for a business that invoices in our portal (it has chosen a
    business type). A marketplace seller who never chose one files as in R1. GSTR-3B has no file here, so it is not gated."""
    if instance.form not in ("GSTR1", "IFF"):
        return
    profile = get_profile(uow.tx)
    if profile is None or profile.business_type is None:
        return
    kind = "month" if instance.period_start.month == instance.period_end.month else "quarter"
    if not status(uow, kind, instance.period_start, today).can_file:
        raise Conflict("period_gate_closed", CLOSED_MESSAGE)
