"""rule61a (LLD-1 §8.4), pure. The offsets here are test inputs shaped like the BRD's
example ("for Q4: 1 Nov to 31 Jan"), not product values: those come from refdata."""

from datetime import date

import pytest

from app.modules.business import rule61a
from app.modules.business.fiscal import add_months, fy_start, previous_fy

EXAMPLE = (-2, 1)
Q4 = date(2027, 1, 1)


def test_the_window_matches_the_brd_example_shape():
    w = rule61a.window_for(Q4, EXAMPLE)
    assert (w.opens, w.closes, w.known) == (date(2026, 11, 1), date(2027, 1, 31), True)


def test_unknown_offsets_give_an_unknown_window_and_never_outside_window():
    assert not rule61a.window_for(Q4, None).known
    assert rule61a.warnings("quarterly", Q4, date(2020, 1, 1), None, None, None) == ["window_unknown"]


def test_a_quarter_must_be_a_quarter_start():
    with pytest.raises(ValueError):
        rule61a.window_for(date(2027, 2, 1), EXAMPLE)


@pytest.mark.parametrize(
    "today,outside",
    [(date(2026, 10, 31), True), (date(2026, 11, 1), False), (date(2027, 1, 31), False), (date(2027, 2, 1), True)],
)
def test_outside_window_is_inclusive_at_both_ends(today, outside):
    got = rule61a.warnings("monthly", Q4, today, EXAMPLE, None, None)
    assert ("outside_window" in got) is outside


def test_aato_and_unfiled_warnings():
    inside = date(2026, 12, 1)
    assert rule61a.warnings("quarterly", Q4, inside, EXAMPLE, "above_threshold", True) == [
        "last_return_unfiled", "aato_above_threshold"]
    assert rule61a.warnings("monthly", Q4, inside, EXAMPLE, "above_threshold", False) == []
    assert rule61a.warnings("quarterly", Q4, inside, EXAMPLE, "up_to_threshold", None) == []


def test_open_window_is_the_first_one_not_yet_closed():
    assert rule61a.open_window(date(2027, 1, 20), EXAMPLE).for_quarter == Q4
    assert rule61a.open_window(date(2027, 2, 1), EXAMPLE).for_quarter == date(2027, 4, 1)
    assert rule61a.open_window(date(2027, 1, 20), None).for_quarter == date(2027, 4, 1)


def test_fiscal_helpers():
    assert fy_start(date(2027, 3, 31)) == date(2026, 4, 1) and fy_start(date(2026, 4, 1)) == date(2026, 4, 1)
    assert previous_fy("2026-27") == "2025-26" and previous_fy("2000-01") == "1999-00"
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 1) and add_months(Q4, -2) == date(2026, 11, 1)


@pytest.mark.parametrize(
    "quarter,opens,closes",
    [  # team/gst/refdata-lld4.md §5, with the loaded rows' offsets (-2, 1)
        (date(2027, 4, 1), date(2027, 2, 1), date(2027, 4, 30)),
        (date(2026, 7, 1), date(2026, 5, 1), date(2026, 7, 31)),  # Circular 143/13/2020's example
        (date(2026, 10, 1), date(2026, 8, 1), date(2026, 10, 31)),
        (date(2027, 1, 1), date(2026, 11, 1), date(2027, 1, 31)),  # crosses the calendar year
    ],
)
def test_the_gst_experts_cases(quarter, opens, closes):
    w = rule61a.window_for(quarter, EXAMPLE)
    assert (w.opens, w.closes) == (opens, closes)
