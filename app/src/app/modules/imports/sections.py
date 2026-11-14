"""One entry per upload section, so the page needs no logic of its own (R1-M3 §4).

Status is exactly one of "not uploaded", "processing", "ready" or "rows held":
processing while a parse job may still run, rows held while a live staged run has held rows,
ready when a file was read (or stored) and nothing is held, otherwise not uploaded. A
rejected, expired or discarded upload does not count as uploaded. Reader data supplies the
requirement note; this module holds no platform wording.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from app.modules.refdata import first_valid_from, value_on
from platform_common.uow import UnitOfWork

from . import uploads
from .readers import HOLD_REASONS, SECTIONS

# The own-invoice Excel section is on since R1-M5 slice 2; the PDF section arrives with its reader (R1-M6).
ENABLED = {"amazon": True, "flipkart": True, "meesho": True, "own_invoices_excel": True, "own_invoices_pdf": False}
LIVE_LIMIT = 50


@dataclass(frozen=True)
class Section:
    section: str
    enabled: bool
    status: str
    uploads: list[uploads.Upload]
    held_rows: int
    needs_ca_check: bool
    requirement_note: str | None


def sections(uow: UnitOfWork, today: date, months: tuple[str, str] | None = None) -> list[Section]:
    b = uow.principal.business_id
    ups = uow.tx.execute(
        text(f"select {uploads._COLUMNS} from imports.uploads u where business_id = :b"
             " and status in ('received', 'parsing', 'parsed', 'stored')"
             " and not (run_id is not null and not exists (select 1 from imports.import_runs r where"
             "   r.upload_id = u.id and r.business_id = u.business_id and r.status <> 'discarded'))"
             + (uploads.in_range_sql("u") if months else "")
             + " order by created_at desc, id desc"),
        {"b": b, **({"fm": months[0], "tm": months[1]} if months else {})},
    ).all()
    held: dict[tuple[str, str], int] = {}
    flagged: set[tuple[str, str]] = set()  # unresolved or accepted rows by (section, reason)
    for section, reason, kind, n in uow.tx.execute(
        text("with latest as (select distinct on (row_id) row_id, kind from imports.row_resolutions"
             "   where business_id = :b order by row_id, created_at desc, id desc)"
             " select u.section, w.hold_reason, l.kind, count(*) from imports.import_rows w"
             " join imports.import_runs r on r.id = w.run_id and r.business_id = w.business_id"
             " join imports.uploads u on u.id = r.upload_id and u.business_id = r.business_id"
             " left join latest l on l.row_id = w.id"
             " where w.business_id = :b and w.status = 'held' and r.status = 'staged'"
             + (uploads.in_range_sql("u") if months else "")
             + " group by u.section, w.hold_reason, l.kind"),
        {"b": b, **({"fm": months[0], "tm": months[1]} if months else {})},
    ):
        if kind is None:
            held[(section, reason)] = held.get((section, reason), 0) + n
        if kind in (None, "accepted"):
            flagged.add((section, reason))
    ca_flag = {reason: bool(value_on(uow.tx, f"imports.held.{reason}.needs_ca_check", today))
               for reason in HOLD_REASONS}
    out = []
    for section in SECTIONS:
        mine = [uploads.Upload(*r) for r in ups if r.section == section]
        held_here = {reason: n for (s, reason), n in held.items() if s == section}
        count = sum(held_here.values())
        if any(u.status in ("received", "parsing") for u in mine):
            status = "processing"
        elif count:
            status = "rows held"
        elif mine:
            status = "ready"
        else:
            status = "not uploaded"
        key = f"imports.requirement.{section}.note"
        note = str(value_on(uow.tx, key, today)) if first_valid_from(uow.tx, key) is not None else None
        out.append(Section(section, ENABLED[section], status, mine[:LIVE_LIMIT], count,
                           any(ca_flag.get(reason, False) for s, reason in flagged if s == section),
                           note))
    return out
