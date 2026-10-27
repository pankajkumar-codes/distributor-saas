"""Indian financial years and quarters (pure). An FY runs 1 April to 31 March and is
written '2026-27'."""

from datetime import date


def fy_of(day: date) -> str:
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def quarter_start(day: date) -> date:
    return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)


def fy_start(day: date) -> date:
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def previous_fy(fy: str) -> str:
    start = int(fy[:4]) - 1
    return f"{start}-{(start + 1) % 100:02d}"


def add_months(day: date, months: int) -> date:
    """The first of the month `months` after (or before) `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)
