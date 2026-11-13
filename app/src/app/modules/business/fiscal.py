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


def quarter_months(day: date) -> tuple[date, date, date]:
    """The first days of the three months of `day`'s quarter."""
    start = quarter_start(day)
    return start, add_months(start, 1), add_months(start, 2)


def fy_quarters(fy: str) -> tuple[date, date, date, date]:
    """The first days of an FY's four quarters ('2026-27': Apr, Jul, Oct, Jan)."""
    start = date(int(fy[:4]), 4, 1)
    return start, add_months(start, 3), add_months(start, 6), add_months(start, 9)


def is_fy(fy: str) -> bool:
    """'2026-27' yes; '2026-29' no."""
    return len(fy) == 7 and fy[:4].isdigit() and fy[4] == "-" and int(fy[5:]) == (int(fy[:4]) + 1) % 100


def fy_quarter_label(first_day: date) -> str:
    """'2026-Q3' for the quarter starting `first_day`: the FY's start year, Q1 = Apr-Jun."""
    fy_year = first_day.year if first_day.month >= 4 else first_day.year - 1
    return f"{fy_year}-Q{(first_day.month - 4) % 12 // 3 + 1}"


def gstin_state(gstin: str) -> str:
    """The GST state code: a GSTIN's first two characters."""
    return gstin[:2]
