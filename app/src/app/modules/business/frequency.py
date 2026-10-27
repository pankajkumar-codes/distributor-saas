"""Filing frequency: insert-only history per GSTIN (LLD-1 §4, §8.2, §8.4, L1-13).

`add_frequency_row` keeps every rule of the frequency route, which LLD-5 serves from
filing's router (erratum L5-9): effective_from is a quarter's first day, the current
quarter or later, except that a business's first row may start at the beginning of the
current FY; rule 61A warnings are returned and stored and never block. Business
serves the route until filing exists (EM, 2026-10-27) with LLD-5's path and shape.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.refdata import RefdataMissing, value_on
from platform_common import audit
from platform_common.errors import Conflict, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import rule61a
from .fiscal import add_months, fy_of, fy_start, previous_fy, quarter_start

FREQUENCIES = ("monthly", "quarterly")
CARRIED = "carried_from_gstin_change"
# Every query names the bound business as well as relying on RLS (defence in depth).
BOUND = "business_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


@dataclass(frozen=True)
class FrequencyRow:
    id: uuid.UUID
    gstin: str
    frequency: str
    effective_from: date
    chosen_at: datetime
    warnings: list[str]


_COLUMNS = "id, gstin, frequency, effective_from, chosen_at, warnings"


def _row(r) -> FrequencyRow:
    return FrequencyRow(r.id, r.gstin, r.frequency, r.effective_from, r.chosen_at, list(r.warnings))


def filing_frequency_on(tx: Session, gstin: str, on: date) -> FrequencyRow | None:
    """The row in force for `on`'s quarter: the latest effective_from on or before the
    quarter's start, ties to the latest chosen_at. None: not set (LLD-1 §4)."""
    r = tx.execute(
        text(f"select {_COLUMNS} from business.filing_frequency_history"
             f" where {BOUND} and gstin = :g and effective_from <= :q order by effective_from desc, chosen_at desc, id desc limit 1"),
        {"g": gstin, "q": quarter_start(on)},
    ).one_or_none()
    return None if r is None else _row(r)


def history(tx: Session, gstin: str) -> list[FrequencyRow]:
    return [_row(r) for r in tx.execute(
        text(f"select {_COLUMNS} from business.filing_frequency_history where {BOUND} and gstin = :g"
             " order by chosen_at desc, id desc"),
        {"g": gstin},
    )]


def window_offsets(tx: Session, on: date) -> tuple[int, int] | None:
    """The rule 61A window offsets, or None until the GST expert's rows are loaded."""
    try:
        return (int(value_on(tx, "qrmp.option_window.open_offset_months", on)),
                int(value_on(tx, "qrmp.option_window.close_offset_months", on)))
    except RefdataMissing:
        return None


def _band(tx: Session, fy: str) -> str | None:
    return tx.execute(text(f"select band from business.turnover_bands where {BOUND} and fy = :fy"), {"fy": fy}).scalar()


def _insert(uow: UnitOfWork, gstin: str, frequency: str, effective_from: date, warnings: list[str]) -> FrequencyRow:
    r = uow.tx.execute(
        text("insert into business.filing_frequency_history (id, business_id, gstin, frequency, effective_from,"
             f" warnings, chosen_by) values (:id, :b, :g, :f, :e, :w, :by) returning {_COLUMNS}"),
        {"id": uuid7(), "b": uow.principal.business_id, "g": gstin, "f": frequency, "e": effective_from,
         "w": warnings, "by": uow.principal.user_id},
    ).one()
    audit.record(uow, "business.frequency_set", "business", uow.principal.business_id,
                 data={"frequency": frequency, "effective_from": effective_from.isoformat(), "warnings": warnings})
    return _row(r)


def add_frequency_row(
    uow: UnitOfWork,
    gstin: str,
    frequency: str,
    effective_from: date,
    *,
    today: date,
    unfiled_due_return: bool | None = None,
) -> tuple[FrequencyRow, list[str]]:
    """Record a frequency choice for the business's current GSTIN (L1-13, §8.4).
    `unfiled_due_return` comes from filing (LLD-5); None until filing exists."""
    tx = uow.tx
    current = tx.execute(
        text("select gstin from business.profiles"
             " where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid for update")
    ).one_or_none()
    if current is None or current.gstin is None:
        raise Conflict("gstin_required", "Add your GSTIN before choosing a filing frequency")
    if gstin != current.gstin:
        raise Invalid("gstin_not_current", "that isn't this business's GSTIN", field="gstin")
    if frequency not in FREQUENCIES:
        raise Invalid("frequency_unknown", "choose monthly or quarterly", field="frequency")
    if effective_from != quarter_start(effective_from):
        raise Invalid("effective_from_not_quarter_start", "a frequency starts on the first day of a quarter",
                      field="effective_from")
    # The profile row lock above serializes choices, so "first row" is decided once.
    first = not tx.execute(text(f"select exists (select 1 from business.filing_frequency_history where {BOUND})")).scalar()
    earliest = fy_start(today) if first else quarter_start(today)
    if effective_from < earliest:
        raise Invalid("effective_from_past",
                      f"choose a quarter starting {earliest.isoformat()} or later", field="effective_from")
    ahead = int(value_on(tx, "business.frequency_max_quarters_ahead", today))
    latest = add_months(quarter_start(today), 3 * ahead)
    if effective_from > latest:
        raise Invalid("effective_from_too_far",
                      f"choose a quarter starting {latest.isoformat()} or earlier", field="effective_from")
    warnings = rule61a.warnings(
        frequency, effective_from, today, window_offsets(tx, today),
        _band(tx, previous_fy(fy_of(effective_from))), unfiled_due_return,
    )
    return _insert(uow, gstin, frequency, effective_from, warnings), warnings


def carry_frequency(uow: UnitOfWork, old_gstin: str, new_gstin: str) -> bool:
    """A GSTIN change before the lock keeps the frequency (LLD-1 §8.2, RM41-7): the old
    GSTIN's latest row is inserted again for the new one. False if there was none."""
    latest = uow.tx.execute(
        text("select frequency, effective_from from business.filing_frequency_history"
             f" where {BOUND} and gstin = :g"
             " order by effective_from desc, chosen_at desc, id desc limit 1"),
        {"g": old_gstin},
    ).one_or_none()
    if latest is None:
        return False
    _insert(uow, new_gstin, latest.frequency, latest.effective_from, [CARRIED])
    return True


@dataclass(frozen=True)
class FilingProfile:
    gstin: str | None
    current: FrequencyRow | None
    history: list[FrequencyRow]
    window: rule61a.Window
    warnings: list[str]


def filing_profile(tx: Session, *, today: date) -> FilingProfile:
    """GET /filing-profile (LLD-1 §8.2)."""
    gstin = tx.execute(
        text("select gstin from business.profiles where business_id = nullif(current_setting('app.tenant_id', true), '')::uuid")
    ).scalar()
    offsets = window_offsets(tx, today)
    window = rule61a.open_window(today, offsets)
    if gstin is None:
        return FilingProfile(None, None, [], window, [] if window.known else [rule61a.WINDOW_UNKNOWN])
    current = filing_frequency_on(tx, gstin, today)
    warnings = [] if window.known else [rule61a.WINDOW_UNKNOWN]
    if current is not None and current.frequency == "quarterly" and _band(tx, previous_fy(fy_of(today))) == "above_threshold":
        warnings.append(rule61a.AATO_ABOVE_THRESHOLD)
    return FilingProfile(gstin, current, history(tx, gstin), window, warnings)
