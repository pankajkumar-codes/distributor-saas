"""Rate history rules (LLD-3 §3), as plain functions over a product's rate rows.

A rate row has only `valid_from`; it ends where the next live row starts (L3-1). A
voided row is never live. The service reads the rows under the product's lock and
calls these, so the rules have one implementation for the API, the interface for
sales and the CSV import.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.modules.refdata import gst_rates, value_on
from platform_common.errors import Invalid


@dataclass(frozen=True)
class RateRow:
    id: object
    rate: Decimal
    valid_from: date
    voided: bool
    confirmed: bool


@dataclass(frozen=True)
class RateOn:
    row: RateRow
    changed_within_warning_window: bool


def live(rows: list[RateRow]) -> list[RateRow]:
    """Live rows, oldest first."""
    return sorted((r for r in rows if not r.voided), key=lambda r: r.valid_from)


def valid_until(rows: list[RateRow]) -> dict[object, date | None]:
    """Each live row's computed end: the next live row's valid_from (exclusive), or None."""
    ordered = live(rows)
    return {r.id: (ordered[i + 1].valid_from if i + 1 < len(ordered) else None) for i, r in enumerate(ordered)}


def rate_on(rows: list[RateRow], on: date, warning_days: int) -> RateOn | None:
    """The live row with the latest valid_from on or before `on` (AC3-1), or None.

    The rate changed recently (tax-computation §5) when that row replaced an earlier live
    row no more than `warning_days` days before `on`: at 30 days it warns, at 31 it
    doesn't. A product's first rate is not a change.
    """
    ordered = [r for r in live(rows) if r.valid_from <= on]
    if not ordered:
        return None
    current = ordered[-1]
    changed = len(ordered) > 1 and (on - current.valid_from).days <= warning_days
    return RateOn(current, changed)


def allowed_rates(tx: Session, on: date) -> frozenset[Decimal]:
    """The GST rates a taxable product's rate row may carry on `on` (refdata gst.rate_values,
    L3-4). The list only catches typos; it never says which rate fits a product."""
    return frozenset(gst_rates(tx, on))


def parse_rate(raw: str) -> Decimal:
    """A rate as the user typed it: a decimal string such as "18" or "18.00", never a float."""
    if not isinstance(raw, str):
        raise Invalid("rate_invalid", "Enter the GST rate as a number, like 18", field="rate")
    try:
        rate = Decimal(raw.strip())
    except InvalidOperation:
        raise Invalid("rate_invalid", "Enter the GST rate as a number, like 18", field="rate") from None
    if not rate.is_finite():
        raise Invalid("rate_invalid", "Enter the GST rate as a number, like 18", field="rate")
    return rate


def check_rate(tx: Session, rate: Decimal, valid_from: date, today: date) -> None:
    """Refuse a rate not on the list for its date, or a date outside the allowed window (§3)."""
    start = date.fromisoformat(str(value_on(tx, "gst.regime_start_date", today)))
    ahead = int(value_on(tx, "catalog.rate_valid_from_max_days_ahead", today))
    if valid_from < start or (valid_from - today).days > ahead:
        raise Invalid(
            "valid_from_out_of_range",
            f"The date must be on or after {start:%d-%m-%Y} and at most {ahead} days from today",
            field="valid_from",
        )
    if rate not in allowed_rates(tx, valid_from):
        raise Invalid(
            "rate_not_allowed",
            f"{rate.normalize():f}% isn't a GST rate on {valid_from:%d-%m-%Y}. Check the rate with your CA",
            field="rate",
        )
