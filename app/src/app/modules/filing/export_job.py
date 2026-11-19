"""Making the GSTR-1 file: the export job and its status (LLD-5 §7; R1-M8 slice 4).

`start` is the route's half. It refuses, in plain words, when the return is not ready (the same gate the screen shows),
when the business may not download (`entitlement`, closed until M9 outside demo and local runs) and when the return cannot
be written as a file at all, then queues one `filing.export` job whose natural key is the return and its fingerprint: a
second click on an unchanged return joins the same job.

The job is the other half. It runs as the user who asked, takes the instance's snapshot lock first, builds the return
under it, and stops with `changed_during_export` if what it built is not what the user saw. It then re-checks the gate, makes
the model, splits it on document boundaries (files of at most `gstr1.offline_tool.max_lines` rows, at most
`gstr1.portal_file.max_bytes` each), stores the files, writes the snapshot, its files and the acceptances it relied on, and logs
`filing.exported`. The snapshot id comes from the job id, so a retry after a crash writes the same files under the same keys
and finds the snapshot if it already committed; two jobs never share a key.

`status` hands out 60-second links to the files of a finished export. A file made while a table has no tool sample behind it
(`render_json.unverified_tables`) is shown with that list and is never "ready to upload"; nor is any file until `gstr1.portal_file.verified` says a file like it
has been through the portal.
"""

import hashlib
import uuid

from sqlalchemy import text

from platform_common import audit, jobs
from platform_common.clock import get_clock
from platform_common.errors import Conflict, Deny
from platform_common.permissions import Permission, has_permission
from platform_common.storage import get_store, key_for
from platform_common.uow import UnitOfWork

from app.modules.identity.interface import member_role
from app.modules.refdata import value_on

from . import entitlement, periods, snapshots, table13
from .acceptance import accepted_set
from .build import build_return
from .checks import run_checks
from .export_model import NOT_IN_FILE, NotRenderable, ExportModel, export_model, rows_in, split
from .gate import accepted_key, export_gate
from .render_json import UNVERIFIED, render_json

JOB = "filing.export"
AREA = "exports"
CONTENT_TYPE = "application/json"


def _snapshot_id(job_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(job_id, "filing.export.snapshot")


def _key(instance_id: uuid.UUID, fingerprint: str, attempt: int = 0) -> str:
    """The return and its fingerprint; a later request after a failed job adds a counter, so a failure never locks a user out."""
    base = f"{instance_id}:{fingerprint}"
    return base if attempt == 0 else f"{base}:{attempt}"


def _failed_before(tx, instance_id: uuid.UUID, fingerprint: str, business: uuid.UUID) -> int:
    """The attempt number a new request for this return as it is now should use: one more than the failed jobs it has had."""
    base = _key(instance_id, fingerprint)
    keys = {
        r.natural_key: r.status
        for r in tx.execute(
            text(
                "select natural_key, status from platform.jobs where business_id = :b and type = :t"
                " and (natural_key = :k or natural_key like :k || ':%')"
            ),
            {"b": business, "t": JOB, "k": base},
        )
    }
    attempt = 0
    while keys.get(_key(instance_id, fingerprint, attempt)) == "failed":
        attempt += 1
    return attempt


def start(uow: UnitOfWork, instance_id: uuid.UUID) -> uuid.UUID:
    inst = periods.get_instance(uow.tx, instance_id)
    if inst is None:
        raise Deny("not_found")
    business = uow.principal.business_id
    if not entitlement.allowed(uow.tx, business):
        raise Conflict("download_not_available", "Downloading the file is not available for your plan yet.")
    build = build_return(uow.tx, inst)
    findings = run_checks(uow.tx, build)
    gate = export_gate(inst, build, findings, accepted_set(uow.tx, inst.id))
    if gate.reasons:
        raise Conflict("not_ready", gate.reasons[0].message)
    if gate.to_accept:
        raise Conflict("not_ready", "Some warnings still need you to accept them.")
    try:
        model = export_model(build, table13.counted_rows(uow.tx, build))
    except NotRenderable as exc:
        raise Conflict("not_renderable", str(exc)) from exc
    if model.empty:
        raise Conflict("nothing_to_file", "There is nothing in this return to put in a file.")
    attempt = _failed_before(uow.tx, inst.id, build.fingerprint, business)
    return jobs.create(uow, JOB, natural_key=_key(inst.id, build.fingerprint, attempt))


def make_files(tx, model: ExportModel) -> list[tuple[bytes, int]]:
    """The files of the model: split by rows, each rendered and checked against the size limit."""
    on = get_clock().today()
    max_rows = int(value_on(tx, "gstr1.offline_tool.max_lines", on))
    max_bytes = int(value_on(tx, "gstr1.portal_file.max_bytes", on))
    out = []
    for part in split(model, max_rows):
        data = render_json(part)
        if len(data) > max_bytes:
            raise jobs.JobFailed("file_too_large")
        out.append((data, rows_in(part)))
    return out


def store_parts(uow: UnitOfWork, sid: uuid.UUID, files: list[tuple[bytes, int]]) -> None:
    """Put each file under a key made from the snapshot id, then record it (sha256, size, rows) against the snapshot.
    Call it in the transaction that writes the snapshot; a retry writes the same keys."""
    p = uow.principal
    store = get_store()
    for n, (data, rows) in enumerate(files, 1):
        key = key_for(p.business_id, AREA, sid, f"part{n}.json")
        store.put(p.business_id, key, data, CONTENT_TYPE)
        uow.tx.execute(
            text(
                "insert into filing.export_files (snapshot_id, business_id, part_no, object_key, sha256, size_bytes,"
                " row_count) values (:s, :b, :n, :k, :h, :z, :r)"
            ),
            {"s": sid, "b": p.business_id, "n": n, "k": key, "h": hashlib.sha256(data).hexdigest(), "z": len(data),
             "r": rows},
        )  # fmt: skip


@jobs.handler(JOB)
def run(ctx: jobs.JobContext) -> dict:
    uow = ctx.uow
    p = uow.principal
    tx = uow.tx
    if not has_permission(member_role(tx, p.business_id, p.user_id), Permission.RETURNS_PREPARE):
        raise jobs.JobFailed("not_allowed")
    view = jobs.get(uow, ctx.job_id)
    if view is None or not view.natural_key or ":" not in view.natural_key:
        raise jobs.JobFailed("not_found")
    raw_instance, _, rest = view.natural_key.partition(":")
    fingerprint = rest.partition(":")[0]  # a later request after a failure adds a counter
    inst = periods.get_instance(tx, uuid.UUID(raw_instance))
    if inst is None:
        raise jobs.JobFailed("not_found")
    sid = _snapshot_id(ctx.job_id)

    # The lock first, then the build: what is written is the state the lock covers (Lead's note on #165).
    snapshots.lock_instance(tx, inst.id)
    done = tx.execute(text("select version from filing.return_snapshots where id = :s"), {"s": sid}).scalar()
    if done is not None:  # a retry of a job whose work already committed
        return _result(tx, sid, done)

    build = build_return(tx, inst)
    if build.fingerprint != fingerprint:
        raise jobs.JobFailed("changed_during_export")
    findings = run_checks(tx, build)
    accepted = accepted_set(tx, inst.id)
    gate = export_gate(inst, build, findings, accepted)
    if not gate.ready:
        raise jobs.JobFailed("not_ready")
    try:
        docs = table13.counted_rows(tx, build)
        model = export_model(build, docs)
    except NotRenderable as exc:
        raise jobs.JobFailed("not_renderable") from exc
    if model.empty:
        raise jobs.JobFailed("nothing_to_file")
    files = make_files(tx, model)
    ctx.progress(0, len(files))

    snap = snapshots.write_snapshot(uow, inst, build, purpose="export", snapshot_id=sid, docs=docs)
    store_parts(uow, sid, files)
    relied = {accepted_key(f) for f in findings if f.level == "warn"}
    acceptance_ids = [
        r.id
        for r in tx.execute(
            text("select id, check_code, subject_fp from filing.check_acceptances where instance_id = :i"),
            {"i": inst.id},
        )
        if (r.check_code, r.subject_fp) in relied
    ]
    if acceptance_ids:
        tx.execute(
            text(
                "insert into filing.snapshot_acceptances (snapshot_id, business_id, acceptance_id) values (:s, :b, :a)"
            ),
            [{"s": sid, "b": p.business_id, "a": a} for a in acceptance_ids],
        )
    audit.record(uow, "filing.exported", "return_instance", inst.id,
                 data={"snapshot_id": str(sid), "version": snap.version, "parts": len(files)})  # fmt: skip
    return _result(tx, sid, snap.version)


def _result(tx, sid: uuid.UUID, version: int) -> dict:
    n, rows = tx.execute(
        text("select count(*), coalesce(sum(row_count), 0) from filing.export_files where snapshot_id = :s"), {"s": sid}
    ).one()
    return {"snapshot_id": str(sid), "version": version, "parts": n, "rows": int(rows)}


def status(uow: UnitOfWork, instance_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """preparing, failed (with the job's code) or ready (60-second links, what is not in the file, what is unverified).
    A job that is not an export of this return, in this business, is a 404."""
    job = jobs.get(uow, job_id)
    if job is None or job.type != JOB or not (job.natural_key or "").startswith(f"{instance_id}:"):
        raise Deny("not_found")
    if job.status == "failed":
        return {"status": "failed", "error_code": job.error_code}
    if job.status != "done":
        return {"status": "preparing"}
    business = uow.principal.business_id
    if not entitlement.allowed(uow.tx, business):
        raise Conflict("download_not_available", "Downloading the file is not available for your plan yet.")
    sid = uuid.UUID((job.result or {})["snapshot_id"])
    mine = uow.tx.execute(
        text("select 1 from filing.return_snapshots where id = :s and instance_id = :i and business_id = :b"),
        {"s": sid, "i": instance_id, "b": business},
    ).first()
    if mine is None:  # a job result that names another return's snapshot is never served here
        raise Deny("not_found")
    inst = periods.get_instance(uow.tx, instance_id)
    return files_of(uow, inst, sid, (job.result or {}).get("version"))


def files_of(uow: UnitOfWork, inst, sid: uuid.UUID, version: int | None) -> dict:
    """The ready answer for a stored snapshot's files: 60-second links, what is not in the file, what is unverified.
    The caller has checked the entitlement."""
    business = uow.principal.business_id
    rows = uow.tx.execute(
        text(
            "select part_no, object_key, size_bytes, row_count from filing.export_files where snapshot_id = :s"
            " order by part_no"
        ),
        {"s": sid},
    ).all()
    store = get_store()
    name = f"GSTR1_{inst.gstin}_{inst.period_end:%m%Y}"
    unverified = _unverified(uow, inst, sid)
    verified = _portal_verified(uow.tx)
    return {
        "status": "ready",
        "version": version,
        "files": [
            {"part": r.part_no, "rows": r.row_count, "size_bytes": r.size_bytes,
             "url": store.presign_get(business, r.object_key, download_name=f"{name}_part{r.part_no}.json")}
            for r in rows
        ],
        "not_in_file": list(NOT_IN_FILE),
        "unverified_tables": unverified,
        "portal_tested": verified,
        "ready_to_upload": verified and not unverified,
    }  # fmt: skip


def _portal_verified(tx) -> bool:
    """Whether a file of this kind has been accepted by the portal (`gstr1.portal_file.verified`, false until the test upload)."""
    return value_on(tx, "gstr1.portal_file.verified", get_clock().today()) is True


def _unverified(uow: UnitOfWork, inst, sid: uuid.UUID) -> list[str]:
    """The tables in the stored export that have no tool sample behind them, from the snapshot's own rows."""
    sections = {
        r.section
        for r in uow.tx.execute(
            text("select distinct section from filing.snapshot_lines where snapshot_id = :s"), {"s": sid}
        )
    }
    return [t for t in UNVERIFIED if t in sections]
