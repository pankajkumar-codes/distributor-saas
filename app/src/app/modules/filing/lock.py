"""Mark filed, lock, unlock and relock a return (LLD-5 §9, L5-5; R1-M8 slice 5).

Marking a return filed records what the user says they filed on the portal (the date and the ARN) and locks the return as it
is now: a lock snapshot of the build, the `filed` event, and the status `filed_locked`, all in one transaction under the
instance's row lock and snapshot lock. Before it does, it compares the build with the file the user took (the latest export
snapshot; for a relock after an unlock, the latest lock snapshot). If they differ, or nothing was ever exported, it refuses with
`changed_since_export` unless the user confirms with a reason, which is stored with the difference by document number on
the lock snapshot (L5-5): the one thing worse than a refusal is a silent mismatch between what was filed and what we hold.

The lock also stores the GSTR-1 file of the locked build, when the return can be rendered, so a locked return is downloaded
from its lock snapshot and not rebuilt. Unlock (owner only, with a reason) changes the status and keeps every snapshot.

`diff_rows` is pure: it compares two lists of output rows by document number.
"""

import uuid
from collections import Counter
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from platform_common import audit, jobs
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.uow import UnitOfWork

from . import entitlement, export_job, periods, snapshots, table13
from .build import ReturnBuild, build_return
from .export_model import NotRenderable, export_model

DOCUMENT_SECTIONS = ("b2b", "b2cl", "cdnr", "cdnur")
SUMMARY_SECTIONS = ("b2cs", "hsn_b2b", "hsn_b2c", "docs")
FIGURES = ("doc_date", "counterparty_gstin", "pos_state_code", "rate", "invoice_value", "taxable_value", "igst", "cgst",
           "sgst", "cess", "note_type", "ur_type", "hsn", "uqc", "quantity", "nature", "from_no", "to_no", "total_count",
           "cancelled_count")  # fmt: skip
ARN_MAX = 32  # the column's width; there is no cited format to check against (TD-12)


def _plain(v) -> str:
    """A value as text that is the same whether it came from the build or from the database."""
    if v is None:
        return ""
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    return str(v).strip()


def _sig(row: dict) -> tuple[str, ...]:
    return tuple(_plain(row.get(f)) for f in FIGURES)


def diff_rows(old: list[dict], new: list[dict]) -> dict:
    """What differs between two sets of output rows: documents added, removed or changed (by section and number), and the
    summary sections whose figures differ. Empty lists everywhere mean the two give the same file."""

    def docs(rows):
        out: dict[tuple[str, str], Counter] = {}
        for r in rows:
            if r["section"] in DOCUMENT_SECTIONS:
                out.setdefault((r["section"], r["doc_number"]), Counter())[_sig(r)] += 1
        return out

    def summaries(rows):
        out: dict[str, Counter] = {}
        for r in rows:
            if r["section"] in SUMMARY_SECTIONS:
                out.setdefault(r["section"], Counter())[_sig(r)] += 1
        return out

    a, b = docs(old), docs(new)
    sa, sb = summaries(old), summaries(new)

    def listed(keys):
        return [{"section": s, "number": n} for s, n in sorted(keys)]

    return {
        "added": listed(b.keys() - a.keys()),
        "removed": listed(a.keys() - b.keys()),
        "changed": listed(k for k in a.keys() & b.keys() if a[k] != b[k]),
        "summaries": sorted(s for s in SUMMARY_SECTIONS if sa.get(s, Counter()) != sb.get(s, Counter())),
    }


def is_same(diff: dict) -> bool:
    return not any(diff[k] for k in ("added", "removed", "changed", "summaries"))


def _reference(tx, inst) -> snapshots.Snapshot | None:
    """What the user last took: the latest export, or after an unlock the latest lock (an unlocked return is not exported)."""
    return snapshots.latest(tx, inst.id, "lock" if inst.status == "unlocked" else "export")


OUTSIDE_REASON = "Filed outside Kartaa"


def mark_completed_outside(uow: UnitOfWork, instance_id: uuid.UUID, filed_on: date, arn: str, today: date) -> dict:
    """The user filed this return on the GST portal without Kartaa's file (issue #424). A GSTR-1 or IFF is locked as it is
    now, the same way as marking it filed, with the reason "Filed outside Kartaa" kept when it differs from the file we
    made (or none was made). A GSTR-3B or PMT-06 has nothing we build, so it gets the `filed` event and `filed_locked` only.
    The period must have ended; the date and ARN follow the same rules as marking filed."""
    tx = uow.tx
    business = uow.principal.business_id
    row = tx.execute(
        text("select form, status from filing.return_instances where id = :i and business_id = :b for update"),
        {"i": instance_id, "b": business},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    if row.form in ("GSTR1", "IFF"):
        out = mark_filed(uow, instance_id, filed_on, arn, OUTSIDE_REASON, today)
        return {"status": out["status"], "filed_on": out["filed_on"], "arn": out["arn"]}
    if row.status not in ("open", "unlocked"):
        raise Conflict("period_not_open", "This return is not open, so it cannot be marked filed.")
    inst = periods.get_instance(tx, instance_id)
    arn = (arn or "").strip()
    if not arn or len(arn) > ARN_MAX:
        raise Invalid("arn_invalid", "Enter the ARN the portal gave you", field="arn")
    if filed_on > today:
        raise Invalid("filed_on_future", "The filing date cannot be in the future", field="filed_on")
    if filed_on < inst.period_end:
        raise Invalid("filed_on_before_period", "The filing date cannot be before the period ends", field="filed_on")
    tx.execute(
        text(
            "insert into filing.instance_events (id, business_id, instance_id, kind, filed_on, arn, reason, actor_user_id)"
            " values (:i, :b, :n, 'filed', :d, :a, :r, :u)"
        ),
        {"i": uuid.uuid4(), "b": business, "n": inst.id, "d": filed_on, "a": arn, "r": OUTSIDE_REASON,
         "u": uow.principal.user_id},
    )  # fmt: skip
    tx.execute(
        text("update filing.return_instances set status = 'filed_locked', status_changed_at = now() where id = :i"),
        {"i": inst.id},
    )
    audit.record(uow, "returns.filed_outside", "return_instance", inst.id, data={"form": inst.form})
    return {"status": "filed_locked", "filed_on": filed_on, "arn": arn}


def changes(uow: UnitOfWork, instance_id: uuid.UUID) -> dict:
    """The difference between the return as it is now and the file the user took, for the screen to show before it asks
    to confirm. Reads only; the filing itself re-checks under the lock."""
    inst = periods.get_instance(uow.tx, instance_id)
    if inst is None:
        raise Deny("not_found")
    build = build_return(uow.tx, inst)
    ref = _reference(uow.tx, inst)
    diff = _difference(uow, ref, build)
    return {
        "reference": None if ref is None else {"purpose": ref.purpose, "version": ref.version},
        "same": ref is not None and ref.fingerprint == build.fingerprint and is_same(diff),
        "difference": diff,
    }


def _difference(uow: UnitOfWork, ref: snapshots.Snapshot | None, build: ReturnBuild) -> dict:
    old = snapshots.read_rows(uow.tx, ref.id) if ref else []
    return diff_rows(old, snapshots.rows_of(build.sections, table13.counted_rows(uow.tx, build)))


def mark_filed(
    uow: UnitOfWork, instance_id: uuid.UUID, filed_on: date, arn: str, accept_reason: str | None, today: date
) -> dict:
    tx = uow.tx
    business = uow.principal.business_id
    row = tx.execute(
        text("select status from filing.return_instances where id = :i and business_id = :b for update"),
        {"i": instance_id, "b": business},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    if row.status not in ("open", "unlocked"):
        raise Conflict("period_not_open", "This return is not open, so it cannot be marked filed.")
    inst = periods.get_instance(tx, instance_id)
    arn = (arn or "").strip()
    if not arn or len(arn) > ARN_MAX:
        raise Invalid("arn_invalid", "Enter the ARN the portal gave you", field="arn")
    if filed_on > today:
        raise Invalid("filed_on_future", "The filing date cannot be in the future", field="filed_on")
    if filed_on < inst.period_end:
        raise Invalid("filed_on_before_period", "The filing date cannot be before the period ends", field="filed_on")
    reason = (accept_reason or "").strip() or None
    if accept_reason is not None and reason is None:
        raise Invalid("reason_required", "Say why what you filed differs from the file we made", field="accept_changed")

    snapshots.lock_instance(tx, inst.id)
    build = build_return(tx, inst)
    ref = _reference(tx, inst)
    diff = _difference(uow, ref, build)
    # Table 13 is confirmed apart from the build, so the same fingerprint can still give a different file: compare the rows too.
    differs = ref is None or ref.fingerprint != build.fingerprint or not is_same(diff)
    diff = diff if differs else None
    if differs and reason is None:
        raise Conflict(
            "changed_since_export",
            "This return has changed since the file you took, or no file was made yet. Make the file again, or confirm"
            " with a reason that what you filed is different.",
        )
    sid = uuid.uuid4()
    snap = snapshots.write_snapshot(
        uow, inst, build, purpose="lock", snapshot_id=sid, changed_since_export=differs, accept_reason=reason if differs else None,
        difference=diff, docs=table13.counted_rows(tx, build),
    )  # fmt: skip
    has_file = _store_file(uow, inst, build, sid)
    tx.execute(
        text(
            "insert into filing.instance_events (id, business_id, instance_id, kind, filed_on, arn, snapshot_id,"
            " actor_user_id) values (:i, :b, :n, 'filed', :d, :a, :s, :u)"
        ),
        {"i": uuid.uuid4(), "b": business, "n": inst.id, "d": filed_on, "a": arn, "s": sid, "u": uow.principal.user_id},
    )
    tx.execute(
        text("update filing.return_instances set status = 'filed_locked', status_changed_at = now() where id = :i"),
        {"i": inst.id},
    )
    audit.record(uow, "returns.filed", "return_instance", inst.id,
                 data={"snapshot_id": str(sid), "version": snap.version, "changed_since_export": differs})  # fmt: skip
    return {"status": "filed_locked", "filed_on": filed_on, "arn": arn, "snapshot_version": snap.version,
            "changed_since_export": differs, "has_file": has_file}  # fmt: skip


def _store_file(uow: UnitOfWork, inst, build: ReturnBuild, sid: uuid.UUID) -> bool:
    """The GSTR-1 file of the locked build, kept with its lock snapshot. A return that cannot be written as a file (an IFF, a
    quarterly return, nothing in it, a part over the size limit) is locked all the same, without one."""
    try:
        model = export_model(build, table13.counted_rows(uow.tx, build))
        if model.empty:
            return False
        files = export_job.make_files(uow.tx, model)
    except (NotRenderable, jobs.JobFailed):
        return False
    export_job.store_parts(uow, sid, files)
    return True


def lock_files(uow: UnitOfWork, instance_id: uuid.UUID) -> dict:
    """The file of the latest lock snapshot, with 60-second links; the same answer as a finished export."""
    inst = periods.get_instance(uow.tx, instance_id)
    if inst is None:
        raise Deny("not_found")
    if not entitlement.allowed(uow.tx, uow.principal.business_id):
        raise Conflict("download_not_available", "Downloading the file is not available for your plan yet.")
    snap = snapshots.latest(uow.tx, inst.id, "lock")
    if snap is None:
        raise Conflict("not_locked", "This return has not been marked filed.")
    out = export_job.files_of(uow, inst, snap.id, snap.version)
    if not out["files"]:
        raise Conflict("no_file", "No file was kept for this return.")
    return out


def unlock(uow: UnitOfWork, instance_id: uuid.UUID, reason: str) -> dict:
    tx = uow.tx
    business = uow.principal.business_id
    why = (reason or "").strip()
    if not why:
        raise Invalid("reason_required", "Say why you are unlocking this return", field="reason")
    row = tx.execute(
        text("select status, form, gstin, period_start, period_end from filing.return_instances"
             " where id = :i and business_id = :b for update"),
        {"i": instance_id, "b": business},
    ).one_or_none()  # fmt: skip
    if row is None:
        raise Deny("not_found")
    if row.status != "filed_locked":
        raise Conflict("not_locked", "This return is not locked.")
    if row.form == "IFF":
        quarter = tx.execute(
            text(
                "select 1 from filing.return_instances where business_id = :b and gstin = :g and form = 'GSTR1'"
                " and status = 'filed_locked' and period_start <= :s and period_end >= :e"
            ),
            {"b": business, "g": row.gstin, "s": row.period_start, "e": row.period_end},
        ).first()
        if quarter:
            raise Conflict("quarter_locked", "Unlock the quarterly GSTR-1 first.")
    tx.execute(
        text(
            "insert into filing.instance_events (id, business_id, instance_id, kind, reason, actor_user_id)"
            " values (:i, :b, :n, 'unlocked', :r, :u)"
        ),
        {"i": uuid.uuid4(), "b": business, "n": instance_id, "r": why, "u": uow.principal.user_id},
    )
    tx.execute(
        text("update filing.return_instances set status = 'unlocked', status_changed_at = now() where id = :i"),
        {"i": instance_id},
    )
    audit.record(uow, "returns.unlock", "return_instance", instance_id, reason=why)
    return {"status": "unlocked"}
