"""Business time (LLD-0 §3.5). Business dates are Indian dates: 23 Oct 20:00 UTC is 24 Oct.

Code that needs "today" or "now" takes a Clock instead of calling datetime itself, so
tests can freeze it with FrozenClock.
"""

from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")


class Clock:
    def now(self) -> datetime:
        """The current instant, timezone-aware, in UTC."""
        return datetime.now(timezone.utc)

    def today(self) -> date:
        """Today's business date in India."""
        return self.now().astimezone(IST).date()


class FrozenClock(Clock):
    def __init__(self, at: datetime):
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self.at = at

    def now(self) -> datetime:
        return self.at.astimezone(timezone.utc)

    def advance(self, delta: timedelta) -> None:
        self.at += delta


def get_clock() -> Clock:
    """FastAPI dependency; tests override it with a FrozenClock."""
    return Clock()
