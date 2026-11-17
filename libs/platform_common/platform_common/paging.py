"""Pagination and date-range filters shared by list and report endpoints (Global AC 5).

Use as FastAPI dependencies:

    def list_x(page: PageParams = Depends(page_params), dates: DateRange = Depends(date_range)): ...
"""

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import Depends, Query

from .clock import Clock, get_clock
from .errors import Invalid

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_RANGE_DAYS = 366


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


@dataclass(frozen=True)
class DateRange:
    date_from: date
    date_to: date


def page_params(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0, le=1_000_000),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


def date_range(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    clock: Clock = Depends(get_clock),
) -> DateRange:
    """Inclusive on both ends, and always bounded, so no list scans all of history.

    A missing `to` is today's Indian date; a missing `from` is the start of the longest
    allowed window ending at `to`. A range may span at most MAX_RANGE_DAYS.
    """
    date_to = date_to or clock.today()
    date_from = date_from or date_to - timedelta(days=MAX_RANGE_DAYS - 1)
    if date_from > date_to:
        raise Invalid("date_range_reversed", "'from' is after 'to'", field="from")
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise Invalid("date_range_too_long", f"date range is limited to {MAX_RANGE_DAYS} days", field="from")
    return DateRange(date_from=date_from, date_to=date_to)


def bounded_range(
    date_from: date | None,
    date_to: date | None,
    today: date,
    *,
    default_days: int,
    max_days: int,
    allow_future: bool = False,
) -> DateRange:
    """Inclusive on both ends, at least one day (`from` equal to `to`), at most `max_days`, and no day after
    `today` unless `allow_future`. A missing `to` is today; a missing `from` is `default_days` ending at `to`."""
    date_to = date_to or today
    if not allow_future and date_to > today:
        raise Invalid("date_in_future", "'to' is a day that has not come yet", field="to")
    date_from = date_from or date_to - timedelta(days=default_days - 1)
    if not allow_future and date_from > today:
        raise Invalid("date_in_future", "'from' is a day that has not come yet", field="from")
    if date_from > date_to:
        raise Invalid("date_range_reversed", "'from' is after 'to'", field="from")
    if (date_to - date_from).days + 1 > max_days:
        raise Invalid("date_range_too_long", f"date range is limited to {max_days} days", field="from")
    return DateRange(date_from=date_from, date_to=date_to)
