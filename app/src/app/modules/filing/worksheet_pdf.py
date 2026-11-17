"""The GSTR-3B worksheet as a PDF through the renderer Lambda (R1-M8b, W5b). Asynchronous, like the draft preview.

`start` queues one `filing.worksheet_pdf` job for the instance's latest build and current entries (the natural key is the
instance, the version and the entries save, so asking again for the same state joins the job; after a failed job a counter lets a
new request through). The job runs as the user who asked, checks the role and the plan again, builds the same figures the screen
and the Excel file show, and hands them to `platform_common.render` with the `gstr3b-worksheet` template. `status` says
queued, rendering, ready (a 60-second link) or failed.
"""

import uuid

from sqlalchemy import text

from platform_common import jobs, render
from platform_common.clock import get_clock
from platform_common.errors import Conflict, Deny
from platform_common.permissions import Permission, has_permission
from platform_common.storage import get_store
from platform_common.uow import UnitOfWork

from app.modules.identity.interface import member_role

from . import entitlement, periods, worksheet
from .gstr3b import excel, pdf

JOB = "filing.worksheet_pdf"


def _key(instance_id: uuid.UUID, version: int, seq: int, attempt: int = 0) -> str:
    base = f"{instance_id}:{version}:{seq}"
    return base if attempt == 0 else f"{base}:{attempt}"


def _attempt(tx, business: uuid.UUID, instance_id: uuid.UUID, version: int, seq: int) -> int:
    base = _key(instance_id, version, seq)
    failed = {
        r.natural_key
        for r in tx.execute(
            text(
                "select natural_key from platform.jobs where business_id = :b and type = :t and status = 'failed'"
                " and (natural_key = :k or natural_key like :k || ':%')"
            ),
            {"b": business, "t": JOB, "k": base},
        )
    }
    attempt = 0
    while _key(instance_id, version, seq, attempt) in failed:
        attempt += 1
    return attempt


def start(uow: UnitOfWork, inst: periods.ReturnInstance) -> uuid.UUID:
    tx = uow.tx
    if not entitlement.allowed(tx, uow.principal.business_id):
        raise Conflict("worksheet_not_available", "The worksheet is not available for your plan yet.")
    latest = worksheet.latest_version(tx, inst.id)
    if latest is None:
        raise Conflict("worksheet_not_built", "Build the worksheet first.")
    cur = worksheet.current_entry(tx, inst.id)
    seq = cur.seq if cur else 0
    attempt = _attempt(tx, uow.principal.business_id, inst.id, latest.version, seq)
    return jobs.create(uow, JOB, natural_key=_key(inst.id, latest.version, seq, attempt))


def status(uow: UnitOfWork, instance_id: uuid.UUID, job_id: uuid.UUID) -> dict:
    """queued, rendering, ready (with a 60-second link) or failed (the job's error code, or render_failed when the renderer gave
    up). A job that is not this instance's worksheet PDF is the same 404 as one that does not exist."""
    job = jobs.get(uow, job_id)
    if job is None or job.type != JOB or not (job.natural_key or "").startswith(f"{instance_id}:"):
        raise Deny("not_found")
    if job.status == "failed":
        return {"status": "failed", "error_code": job.error_code}
    if job.status != "done":
        return {"status": "queued"}
    business = uow.principal.business_id
    if not entitlement.allowed(uow.tx, business):
        raise Conflict("worksheet_not_available", "The worksheet is not available for your plan yet.")
    if not render.is_rendered(business, job_id):
        if render.has_failed(business, job_id) or get_clock().now() - job.updated_at > render.GIVE_UP_AFTER:
            return {"status": "failed", "error_code": "render_failed"}
        return {"status": "rendering"}
    inst = periods.get_instance(uow.tx, instance_id)
    name = f"GSTR3B_worksheet_{inst.gstin}_{inst.period_end:%m%Y}.pdf" if inst else "GSTR3B_worksheet.pdf"
    return {"status": "ready", "url": get_store().presign_get(business, render.document_key(business, job_id), download_name=name)}


@jobs.handler(JOB)
def run(ctx: jobs.JobContext) -> dict:
    uow = ctx.uow
    p = uow.principal
    tx = uow.tx
    if not has_permission(member_role(tx, p.business_id, p.user_id), Permission.RETURNS_PREPARE):
        raise jobs.JobFailed("not_allowed")
    if not entitlement.allowed(tx, p.business_id):
        raise jobs.JobFailed("not_available")
    view = jobs.get(uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    raw, version, seq, *_attempt = view.natural_key.split(":")
    inst = periods.get_instance(tx, uuid.UUID(raw))
    if inst is None or inst.form != "GSTR3B":
        raise jobs.JobFailed("not_found")
    latest = worksheet.latest_version(tx, inst.id)
    cur = worksheet.current_entry(tx, inst.id)
    if latest is None or latest.version != int(version) or (cur.seq if cur else 0) != int(seq):
        raise jobs.JobFailed("changed")  # a newer build or save exists; the user asks again
    now = get_clock().now()
    model = excel.SheetModel(
        gstin=inst.gstin, period_label=periods.period_label(inst), version=latest.version,
        built_at=f"{latest.built_at:%d %b %Y %H:%M} UTC", generated_at=f"{now:%d %b %Y %H:%M} UTC",
        out_of_date=worksheet.is_out_of_date(tx, inst, latest), outward=latest.outward,
        entries=cur.entry if cur else {}, flags=tuple(latest.outward["flags"]),
    )  # fmt: skip
    render.request(p.business_id, ctx.job_id, pdf.render_input(model))
    return {"render_id": str(ctx.job_id)}
