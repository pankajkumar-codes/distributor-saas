"""Insert-only snapshots of a built return (LLD-5 §2.3, TD-13; R1-M8 slice 2).

A snapshot records what an export or a lock contained: one row per output row and the documents behind them.
It is written inside the caller's transaction, under a per-instance advisory lock that
also numbers the versions, so two writers on one instance get versions n and n + 1 and never the same one. A caller that
retries with the same `snapshot_id` gets the snapshot it already wrote, not a second one.

Nothing here edits or removes a snapshot (the tables refuse it). The files an export produced arrive with the export job.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from platform_common.errors import Conflict
from platform_common.ids import uuid7
from platform_common.uow import BusinessUoW

from .build import ReturnBuild
from .gstr1 import Gstr1Sections
from .periods import ReturnInstance

# Bump when `build_return` or the rows below change what a fingerprint means, so an old snapshot says which rules made it.
BUILDER_VERSION = "r1-m8.1"

PURPOSES = ("export", "lock")


@dataclass(frozen=True)
class Snapshot:
    id: uuid.UUID
    version: int
    purpose: str
    fingerprint: str
    created: bool  # False when this call found the snapshot it had already written


def rows_of(sections: Gstr1Sections) -> list[dict]:
    """The output rows of a build, in a fixed order (section order, then the build's own row order), numbered from 1."""
    out: list[dict] = []

    def add(section: str, **v) -> None:
        a = v.pop("amounts")
        out.append({"section": section, "row_no": len(out) + 1, **v, "taxable_value": a.taxable_value, "igst": a.igst,
                    "cgst": a.cgst, "sgst": a.sgst, "cess": a.cess})  # fmt: skip

    for r in sections.b2b:
        add("b2b", doc_number=r.invoice_number, doc_date=r.invoice_date, counterparty_gstin=r.recipient_gstin,
            pos_state_code=r.pos_state_code, rate=r.rate, invoice_value=r.invoice_value, amounts=r.amounts)  # fmt: skip
    for r in sections.b2cl:
        add("b2cl", doc_number=r.invoice_number, doc_date=r.invoice_date, pos_state_code=r.pos_state_code,
            rate=r.rate, invoice_value=r.invoice_value, amounts=r.amounts)  # fmt: skip
    for r in sections.b2cs:
        add("b2cs", pos_state_code=r.pos_state_code, rate=r.rate, amounts=r.amounts)
    for r in sections.cdnr:
        add("cdnr", doc_number=r.note_number, doc_date=r.note_date, counterparty_gstin=r.recipient_gstin,
            pos_state_code=r.pos_state_code, rate=r.rate, note_type=r.note_type, invoice_value=r.note_value,
            amounts=r.amounts)  # fmt: skip
    for r in sections.cdnur:
        add("cdnur", doc_number=r.note_number, doc_date=r.note_date, pos_state_code=r.pos_state_code, rate=r.rate,
            note_type=r.note_type, ur_type=r.ur_type, invoice_value=r.note_value, amounts=r.amounts)  # fmt: skip
    for name in ("hsn_b2b", "hsn_b2c"):
        for r in getattr(sections, name):
            add(name, hsn=r.hsn, uqc=r.uqc, rate=r.rate, quantity=r.quantity, amounts=r.amounts)
    return out


_COLUMNS = (
    "doc_number", "doc_date", "counterparty_gstin", "pos_state_code", "rate", "hsn", "uqc", "note_type", "ur_type",
    "quantity", "invoice_value", "series_prefix", "from_no", "to_no", "total_count", "cancelled_count", "file_part",
)  # fmt: skip


def _members(build: ReturnBuild) -> dict[tuple[str, uuid.UUID], uuid.UUID]:
    """(source_kind, source_id) to the instance the line is assigned to, one entry per document."""
    out: dict[tuple[str, uuid.UUID], uuid.UUID] = {}
    for ln in build.lines:
        out[(ln.source_kind, ln.source_id)] = ln.return_instance_id or build.instance.id
    return out


def _totals(build: ReturnBuild) -> dict:
    heads = ("taxable_value", "igst", "cgst", "sgst", "cess")

    def one(a):
        return {h: str(getattr(a, h)) for h in heads}

    return {"liability": one(build.liability), "table_12": one(build.hsn_total), "line_items": build.line_items,
            "documents": len(build.members)}  # fmt: skip


def lock_instance(tx: Session, instance_id: uuid.UUID) -> None:
    """Serialise writers of this instance's snapshots until the transaction ends. A writer that builds the return takes
    this first, then builds, so the snapshot it writes is of the state it holds the lock over (the same lock is taken
    again, harmlessly, by `write_snapshot`)."""
    tx.execute(
        text("select pg_advisory_xact_lock(hashtextextended('filing.snapshot:' || cast(:i as text), 0))"),
        {"i": instance_id},
    )


def write_snapshot(
    uow: BusinessUoW,
    instance: ReturnInstance,
    build: ReturnBuild,
    *,
    purpose: str,
    snapshot_id: uuid.UUID | None = None,
    template_version: str | None = None,
    changed_since_export: bool = False,
    accept_reason: str | None = None,
    difference: dict | None = None,
) -> Snapshot:
    """Write the build as the next version of this instance's snapshots. Must run in the caller's transaction.

    The advisory lock is taken before the version is read, which needs the usual READ COMMITTED: under REPEATABLE READ a
    second writer would fail on `unique (instance_id, version)` rather than write a duplicate. The caller supplies a
    `snapshot_id` it generated on the server (never one from a client) so that its own retry finds the snapshot it wrote.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown snapshot purpose {purpose!r}")
    if build.instance.id != instance.id:
        raise ValueError("the build is of another return")
    tx = uow.tx
    business = uow.principal.business_id
    lock_instance(tx, instance.id)
    sid = snapshot_id or uuid7()
    existing = tx.execute(
        text("select id, instance_id, version, purpose, fingerprint from filing.return_snapshots where id = :s"),
        {"s": sid},
    ).first()
    if existing:  # a retry of a write that already committed
        if (existing.instance_id, existing.purpose, existing.fingerprint) != (instance.id, purpose, build.fingerprint):
            raise Conflict("snapshot_id_reused", "That snapshot number was already used for something else.")
        return Snapshot(existing.id, existing.version, existing.purpose, existing.fingerprint, False)
    version = tx.execute(
        text("select coalesce(max(version), 0) + 1 from filing.return_snapshots where instance_id = :i"),
        {"i": instance.id},
    ).scalar_one()
    tx.execute(
        text(
            "insert into filing.return_snapshots (id, business_id, instance_id, version, purpose, fingerprint,"
            " builder_version, template_version, refdata_as_of, totals, changed_since_export, accept_reason,"
            " difference, created_by) values (:id, :b, :i, :v, :p, :fp, :bv, :tv, cast(:ra as jsonb),"
            " cast(:t as jsonb), :c, :ar, cast(:d as jsonb), :u)"
        ),
        {"id": sid, "b": business, "i": instance.id, "v": version, "p": purpose, "fp": build.fingerprint,
         "bv": BUILDER_VERSION, "tv": template_version, "ra": json.dumps(build.refdata_as_of),
         "t": json.dumps(_totals(build)), "c": changed_since_export, "ar": accept_reason,
         "d": json.dumps(difference) if difference is not None else None, "u": uow.principal.user_id},
    )  # fmt: skip
    rows = rows_of(build.sections)
    if rows:
        cols = ("section", "row_no", "taxable_value", "igst", "cgst", "sgst", "cess", *_COLUMNS)
        tx.execute(
            text(
                f"insert into filing.snapshot_lines (snapshot_id, business_id, {', '.join(cols)})"
                f" values (:snapshot_id, :business_id, {', '.join(':' + c for c in cols)})"
            ),
            [{"snapshot_id": sid, "business_id": business, **{c: r.get(c) for c in cols}} for r in rows],
        )
    members = _members(build)
    if members:
        tx.execute(
            text(
                "insert into filing.snapshot_members (snapshot_id, business_id, source_kind, source_id, via_instance)"
                " values (:s, :b, :k, :d, :v)"
            ),
            [{"s": sid, "b": business, "k": k, "d": d, "v": v} for (k, d), v in members.items()],
        )
    return Snapshot(sid, version, purpose, build.fingerprint, True)


def latest(tx: Session, instance_id: uuid.UUID, purpose: str) -> Snapshot | None:
    r = tx.execute(
        text(
            "select id, version, purpose, fingerprint from filing.return_snapshots"
            " where instance_id = :i and purpose = :p order by version desc limit 1"
        ),
        {"i": instance_id, "p": purpose},
    ).first()
    return Snapshot(r.id, r.version, r.purpose, r.fingerprint, False) if r else None


def read_rows(tx: Session, snapshot_id: uuid.UUID) -> list[dict]:
    """The rows of a snapshot in row order, as stored (Decimals, dates)."""
    return [
        dict(r._mapping)
        for r in tx.execute(
            text("select * from filing.snapshot_lines where snapshot_id = :s order by row_no"), {"s": snapshot_id}
        )
    ]


def read_members(tx: Session, snapshot_id: uuid.UUID) -> set[tuple[str, uuid.UUID]]:
    return {
        (r.source_kind, r.source_id)
        for r in tx.execute(
            text("select source_kind, source_id from filing.snapshot_members where snapshot_id = :s"),
            {"s": snapshot_id},
        )
    }


__all__ = ["BUILDER_VERSION", "Snapshot", "latest", "lock_instance", "read_members", "read_rows", "rows_of",
           "write_snapshot"]  # fmt: skip
