"""Pagination and date-range filters shared by list and report endpoints (Global AC 5).

Use as FastAPI dependencies:

    def list_x(page: PageParams = Depends(page_params), dates: DateRange = Depends(date_range)): ...
"""

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, Query, status

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_RANGE_DAYS = 366


@dataclass(frozen=True)
class PageParams:
    limit: int
    offset: int


@dataclass(frozen=True)
class DateRange:
    date_from: date | None
    date_to: date | None


def page_params(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0, le=1_000_000),
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


def date_range(
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
) -> DateRange:
    """Inclusive on both ends. A bounded range may span at most MAX_RANGE_DAYS."""
    if date_from and date_to:
        if date_from > date_to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'from' is after 'to'")
        if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"date range is limited to {MAX_RANGE_DAYS} days"
            )
    return DateRange(date_from=date_from, date_to=date_to)
