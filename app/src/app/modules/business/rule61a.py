"""The QRMP option window and the frequency warnings (LLD-1 §8.4, ON-4). Pure.

The window for a quarter Q opens on the first of the month `open_offset_months` from
Q's start and closes the day before the first of the month `close_offset_months` from
Q's start, both inclusive. The offsets are refdata rows the GST expert supplies with a
citation (`qrmp.option_window.open_offset_months`, `close_offset_months`); until they
exist the window is unknown, the reply says so, and `outside_window` is never raised.
None of the warnings blocks a choice.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from .fiscal import add_months, quarter_start

OUTSIDE_WINDOW = "outside_window"
WINDOW_UNKNOWN = "window_unknown"
LAST_RETURN_UNFILED = "last_return_unfiled"
AATO_ABOVE_THRESHOLD = "aato_above_threshold"
# `portal_stricter_reading` (LLD-1 §8.4) has no stated condition yet; it is raised once
# the GST expert defines one (docs/OPEN_QUESTIONS.md).


@dataclass(frozen=True)
class Window:
    for_quarter: date
    opens: date | None  # None: the refdata offsets aren't loaded
    closes: date | None

    @property
    def known(self) -> bool:
        return self.opens is not None


def window_for(quarter: date, offsets: tuple[int, int] | None) -> Window:
    if quarter != quarter_start(quarter):
        raise ValueError("quarter must be a quarter's first day")
    if offsets is None:
        return Window(quarter, None, None)
    open_offset, close_offset = offsets
    return Window(quarter, add_months(quarter, open_offset), add_months(quarter, close_offset) - timedelta(days=1))


def open_window(today: date, offsets: tuple[int, int] | None) -> Window:
    """The window Filing settings shows: the earliest quarter, from this one on, whose
    window hasn't closed. Unknown offsets show the next quarter."""
    this = quarter_start(today)
    if offsets is not None:
        for quarter in (this, add_months(this, 3)):
            w = window_for(quarter, offsets)
            if today <= w.closes:
                return w
    return window_for(add_months(this, 3), offsets)


def warnings(
    frequency: str,
    effective_from: date,
    today: date,
    offsets: tuple[int, int] | None,
    last_fy_band: str | None,
    unfiled_due_return: bool | None,
) -> list[str]:
    out: list[str] = []
    w = window_for(effective_from, offsets)
    if not w.known:
        out.append(WINDOW_UNKNOWN)
    elif not (w.opens <= today <= w.closes):
        out.append(OUTSIDE_WINDOW)
    if unfiled_due_return:
        out.append(LAST_RETURN_UNFILED)
    if frequency == "quarterly" and last_fy_band == "above_threshold":
        out.append(AATO_ABOVE_THRESHOLD)  # monthly applies from the next quarter
    return out
