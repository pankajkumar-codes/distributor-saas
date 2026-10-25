"""Business dates are Indian dates (LLD-0 §3.5, AC-14)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from platform_common.clock import IST, Clock, FrozenClock


def test_23_oct_2000_utc_is_24_oct_in_india():
    assert FrozenClock(datetime(2026, 10, 23, 20, 0, tzinfo=UTC)).today() == date(2026, 10, 24)


def test_just_before_ist_midnight_is_still_the_same_day():
    assert FrozenClock(datetime(2026, 10, 23, 18, 29, 59, tzinfo=UTC)).today() == date(2026, 10, 23)
    assert FrozenClock(datetime(2026, 10, 23, 18, 30, tzinfo=UTC)).today() == date(2026, 10, 24)


def test_now_is_utc_and_aware():
    now = Clock().now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    frozen = FrozenClock(datetime(2026, 10, 24, 9, 0, tzinfo=IST))
    assert frozen.now() == datetime(2026, 10, 24, 3, 30, tzinfo=UTC)


def test_frozen_clock_advances_and_refuses_naive_times():
    c = FrozenClock(datetime(2026, 10, 23, 18, 0, tzinfo=UTC))
    c.advance(timedelta(hours=1))
    assert c.today() == date(2026, 10, 24)
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 10, 23, 18, 0))
