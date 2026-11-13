"""Which marketplace files are in, month by month (R1-M4 S4; LLD-7 §8). Read-only.

A run says which calendar months it covers (`summary.months`, set when it was staged from the date field
each reader names for this). That is for this view only: it is not the return period, which the build
decides once the CA has answered. For each month that any live preview covers, each platform lists the
report types it needs (from its readers), the ones with a live preview, and the held rows still open in
those previews. A preview covering two months counts in both, so `held_rows` is per preview, not per row-month.
`complete` means every required report type has a live preview; the stricter "confirmed" meaning comes
with confirm (R1-M7).
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from platform_common.uow import UnitOfWork

from .readers import PLATFORM_SECTIONS, readers_for
from .uploads import month_range


@dataclass(frozen=True)
class PlatformMonth:
    marketplace: str
    required: list[str]
    received: list[str]
    complete: bool
    held_rows: int


@dataclass(frozen=True)
class MonthCoverage:
    month: str
    marketplaces: list[PlatformMonth]


def required_reports(marketplace: str) -> list[str]:
    return sorted({r.report_type for r in readers_for(marketplace)})


def coverage(uow: UnitOfWork, frm: date | None, to: date | None) -> list[MonthCoverage]:
    bounds = month_range(frm, to)
    b = uow.principal.business_id
    found = uow.tx.execute(
        text("with latest as (select distinct on (row_id) row_id, kind from imports.row_resolutions"
             "   where business_id = :b order by row_id, created_at desc, id desc)"
             " select r.id, r.marketplace, r.report_type, r.summary -> 'months' as months,"
             "   (select count(*) from imports.import_rows w left join latest l on l.row_id = w.id"
             "     where w.run_id = r.id and w.business_id = r.business_id and w.status = 'held' and l.kind is null)"
             "   as held from imports.import_runs r"
             " where r.business_id = :b and r.status <> 'discarded' and r.upload_id is not null"),
        {"b": b},
    ).all()
    by_month: dict[str, dict[str, dict]] = {}
    for run in found:
        for m in run.months or []:
            if bounds and not bounds[0] <= m <= bounds[1]:
                continue
            slot = by_month.setdefault(m, {}).setdefault(run.marketplace, {"received": set(), "held": 0})
            slot["received"].add(run.report_type)
            slot["held"] += int(run.held)
    out = []
    for month in sorted(by_month):
        platforms = []
        for marketplace in PLATFORM_SECTIONS:
            need = required_reports(marketplace)
            slot = by_month[month].get(marketplace, {"received": set(), "held": 0})
            got = sorted(slot["received"])
            platforms.append(PlatformMonth(marketplace, need, got, bool(need) and set(need) <= set(got), slot["held"]))
        out.append(MonthCoverage(month, platforms))
    return out
