"""Indian financial years and quarters (pure). An FY runs 1 April to 31 March and is
written '2026-27'."""

from datetime import date


def fy_of(day: date) -> str:
    start = day.year if day.month >= 4 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def quarter_start(day: date) -> date:
    return date(day.year, (day.month - 1) // 3 * 3 + 1, 1)
