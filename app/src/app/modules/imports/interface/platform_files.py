"""Which marketplace files a period still lacks (R3-M4), for the filing gate.

A platform's month is covered when every report type its readers need has been received (the coverage view), or when the
business has said the platform had no sales that month ("none this month"). Nothing here changes data."""

from collections.abc import Sequence
from datetime import date

from platform_common.uow import UnitOfWork

from .. import confirm, coverage


def missing_platform_months(uow: UnitOfWork, platforms: Sequence[str], months: Sequence[date]) -> dict[str, list[str]]:
    """For each platform with a month not covered, the months (as 'YYYY-MM') still missing. A platform fully covered is left out."""
    if not platforms or not months:
        return {}
    wanted = sorted({f"{m:%Y-%m}" for m in months})
    first, last = date.fromisoformat(wanted[0] + "-01"), max(months)
    complete = {(m.month, p.marketplace) for m in coverage.coverage(uow, first, last) for p in m.marketplaces if p.complete}
    none = {(f"{month:%Y-%m}", section) for section, month in confirm.list_none_this_month(uow)}
    out: dict[str, list[str]] = {}
    for platform in platforms:
        gaps = [m for m in wanted if (m, platform) not in complete and (m, platform) not in none]
        if gaps:
            out[platform] = gaps
    return out
