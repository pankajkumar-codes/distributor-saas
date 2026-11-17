"""The GSTR-3B worksheet of one return instance: numbers to check and enter on the GST portal, never a filing (R1-M8b, W2).

Outward supplies are built from the matching GSTR-1 build and stored as insert-only versions; what the seller types is stored as
insert-only entries. Both are written in the caller's transaction under the per-instance advisory lock that numbers them, so two
writers get n and n + 1. No net payable, offset or interest is computed anywhere (BRD GF-21).
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.business.interface import gstin_state
from platform_common import audit
from platform_common.errors import Conflict, Invalid
from platform_common.ids import uuid7
from platform_common.uow import BusinessUoW

from . import entitlement, periods
from .build import ReturnBuild, build_return
from .checks import run_checks
from .gstr3b import Outward, build_outward
from .gstr3b.entries import EntryError, normalize
from .periods import ReturnInstance


@dataclass(frozen=True)
class Version:
    id: uuid.UUID
    version: int
    fingerprint: str
    outward: dict
    built_at: object
    created: bool = False


@dataclass(frozen=True)
class Entry:
    seq: int
    entry: dict[str, str]


def gstr1_of(tx: Session, inst: ReturnInstance) -> ReturnInstance | None:
    """The GSTR-1 of the same business, GSTIN and period (the month, or the QRMP quarter): where the outward supplies come from."""
    for i in periods.instances_between(tx, inst.gstin, inst.period_start, inst.period_start):
        if i.form == "GSTR1" and i.period_end == inst.period_end:
            return i
    return None


def outward_json(out: Outward) -> dict:
    a = out.taxable
    return {
        "taxable": {k: str(getattr(a, k)) for k in ("taxable_value", "igst", "cgst", "sgst", "cess")},
        "taxable_refs": list(out.taxable_refs),
        "inter_state": [{"pos_state_code": r.pos_state_code, "unregistered_taxable": str(r.unregistered_taxable),
                         "unregistered_igst": str(r.unregistered_igst), "source_refs": list(r.source_refs)}
                        for r in out.inter_state],
        "zero_rate_rows": out.zero_rate_rows,
        "inter_state_taxable": str(out.inter_state_taxable),
        "inter_state_igst": str(out.inter_state_igst),
    }  # fmt: skip


def outward_of(build: ReturnBuild) -> Outward:
    return build_outward([build.sections, *build.iff_sections], gstin_state(build.instance.gstin))


def blocks_of(tx: Session, build: ReturnBuild) -> int:
    return sum(1 for f in run_checks(tx, build) if f.level == "block")


def lock(tx: Session, instance_id: uuid.UUID) -> None:
    tx.execute(
        text("select pg_advisory_xact_lock(hashtextextended('filing.worksheet:' || cast(:i as text), 0))"),
        {"i": instance_id},
    )


def latest_version(tx: Session, instance_id: uuid.UUID) -> Version | None:
    r = tx.execute(
        text(
            "select id, version, build_fingerprint, outward, flags, built_at from filing.worksheet_versions"
            " where instance_id = :i order by version desc limit 1"
        ),
        {"i": instance_id},
    ).first()
    return None if r is None else Version(r.id, r.version, r.build_fingerprint, {**r.outward, "flags": r.flags}, r.built_at)


def current_entry(tx: Session, instance_id: uuid.UUID) -> Entry | None:
    r = tx.execute(
        text("select seq, entry from filing.worksheet_entries where instance_id = :i order by seq desc limit 1"),
        {"i": instance_id},
    ).first()
    return None if r is None else Entry(r.seq, dict(r.entry))


def require_allowed(uow: BusinessUoW) -> None:
    if not entitlement.allowed(uow.tx, uow.principal.business_id):
        raise Conflict("worksheet_not_available", "The worksheet is not available for your plan yet.")


def build_version(uow: BusinessUoW, inst: ReturnInstance) -> Version:
    """Build the next version from the matching GSTR-1 as it is now. Refused (409) with no GSTR-1, a return that is not open,
    or any unresolved block. Asking again for an unchanged GSTR-1 returns the latest version instead of writing a copy."""
    tx = uow.tx
    if inst.status != "open":
        raise Conflict("return_not_open", "This return is not open, so its worksheet cannot be rebuilt.")
    g1 = gstr1_of(tx, inst)
    if g1 is None:
        raise Conflict("no_gstr1", "There is no GSTR-1 for this period to build the worksheet from.")
    lock(tx, inst.id)
    b = build_return(tx, g1)
    n = blocks_of(tx, b)
    if n:
        raise Conflict("worksheet_blocked",
                       f"{n} item{'s' if n != 1 else ''} to fix in your GSTR-1 before the worksheet can be built.")  # fmt: skip
    cur = latest_version(tx, inst.id)
    if cur is not None and cur.fingerprint == b.fingerprint:
        return Version(cur.id, cur.version, cur.fingerprint, cur.outward, cur.built_at, False)
    out = outward_of(b)
    vid, number = uuid7(), (cur.version if cur else 0) + 1
    built_at = tx.execute(
        text(
            "insert into filing.worksheet_versions (id, business_id, instance_id, version, build_fingerprint, outward,"
            " flags, built_by) values (:id, :b, :i, :v, :fp, cast(:o as jsonb), cast(:f as jsonb), :u) returning built_at"
        ),
        {"id": vid, "b": uow.principal.business_id, "i": inst.id, "v": number, "fp": b.fingerprint,
         "o": json.dumps(outward_json(out)), "f": json.dumps(list(out.flags)), "u": uow.principal.user_id},
    ).scalar_one()  # fmt: skip
    audit.record(uow, "worksheet.built", "return_instance", inst.id, data={"version": number})
    return Version(vid, number, b.fingerprint, {**outward_json(out), "flags": list(out.flags)}, built_at, True)


def save_entries(uow: BusinessUoW, inst: ReturnInstance, raw: dict, based_on: int | None) -> Entry:
    """Replace the seller's entries with `raw` (cleaned) as the next save. `based_on` is the save the screen was showing: a
    different one means someone else saved meanwhile (409). The same entries as now write nothing (a retry is safe)."""
    tx = uow.tx
    if inst.status != "open":
        raise Conflict("return_not_open", "This return is not open, so its worksheet cannot be changed.")
    try:
        entry = normalize(raw)
    except EntryError as exc:
        raise Invalid("invalid_entry", exc.message, field=exc.field) from None
    lock(tx, inst.id)
    cur = current_entry(tx, inst.id)
    if (cur.seq if cur else None) != based_on:
        raise Conflict("worksheet_changed", "The worksheet was changed somewhere else. Reload it and try again.")
    if cur is not None and cur.entry == entry:
        return cur
    if cur is None and not entry:
        return Entry(0, {})
    before = cur.entry if cur else {}
    seq = (cur.seq if cur else 0) + 1
    tx.execute(
        text(
            "insert into filing.worksheet_entries (id, business_id, instance_id, seq, entry, previous_seq, changed_by)"
            " values (:id, :b, :i, :s, cast(:e as jsonb), :p, :u)"
        ),
        {"id": uuid7(), "b": uow.principal.business_id, "i": inst.id, "s": seq, "e": json.dumps(entry),
         "p": cur.seq if cur else None, "u": uow.principal.user_id},
    )  # fmt: skip
    changed = sorted(k for k in set(before) | set(entry) if before.get(k) != entry.get(k))
    audit.record(uow, "worksheet.entered", "return_instance", inst.id,
                 data={"seq": seq, "previous_seq": cur.seq if cur else 0, "fields": changed})  # fmt: skip
    return Entry(seq, entry)


