"""The audit log as a CSV file (LLD-2 §7 [D, RM42-11], AC2-12).

`start` writes the `audit.export` row (its filters in `data`) and queues one
`audit.export_csv` job in the same unit of work, so the export is itself in the log. The
job runs as the user who asked, re-checks that they still hold `audit.view`, reads the
same rows the screen shows (`service.audit_log`), and writes When, Who, What happened,
Reason or detail, with only the allowlisted details and every cell made safe for
spreadsheets (`platform_common.csv_export`). The file goes to
`audit-exports/b/<business>/<job>/audit-log.csv`, which S3 expires after a day; `status` hands out a 60-second link to it.

More rows than refdata `audit.export_max_rows` fails the job with `narrow_filter`
rather than writing part of the log.
"""

import json
import uuid
from datetime import date

from platform_common import audit, jobs
from platform_common.clock import IST, get_clock
from platform_common.csv_export import to_csv
from platform_common.errors import Deny
from platform_common.ids import uuid7
from platform_common.permissions import Permission, has_permission
from platform_common.storage import get_store, key_for
from platform_common.uow import UnitOfWork

from app.modules.refdata import value_on

from . import audit_labels
from .interface import member_role
from .service.audit_log import Filters, actor_of, details_of, rows

JOB = "audit.export_csv"
FILE_NAME = "audit-log.csv"
AREA = "audit-exports"  # expired after a day by its own S3 lifecycle rule (infra/modules/storage)
HEADER = ("When (IST)", "Who", "What happened", "Reason or detail")


def start(uow: UnitOfWork, f: Filters) -> uuid.UUID:
    """Logs the export and queues its job. Each call is a new export: the job's natural key
    carries a fresh ID with the filters (the route's Idempotency-Key covers retries)."""
    bid = uow.principal.business_id
    audit.record(uow, "audit.export", "business", bid, data=f.as_data())
    key = json.dumps({"export": str(uuid7()), **f.as_data()}, sort_keys=True)
    return jobs.create(uow, JOB, natural_key=key)


def status(uow: UnitOfWork, job_id: uuid.UUID) -> dict:
    """preparing, ready (with a 60-second link and the row count) or failed (the job's
    error code). Anything that isn't one of this business's audit exports is a 404."""
    job = jobs.get(uow, job_id)
    if job is None or job.type != JOB:
        raise Deny("not_found")
    if job.status == "failed":
        return {"status": "failed", "error_code": job.error_code}
    if job.status != "done":
        return {"status": "preparing"}
    business = uow.principal.business_id
    url = get_store().presign_get(business, key_for(business, AREA, job_id, FILE_NAME), download_name=FILE_NAME)
    return {"status": "ready", "url": url, "rows": (job.result or {}).get("rows")}


def _filters(ctx: jobs.JobContext) -> Filters:
    """The filters are the job's natural key, read under RLS, never from the queue message."""
    view = jobs.get(ctx.uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    k = json.loads(view.natural_key)
    return Filters(k["kind"], None if k["actor"] is None else uuid.UUID(k["actor"]),
                   date.fromisoformat(k["from"]), date.fromisoformat(k["to"]))


def _detail(r) -> str:
    parts = [r.reason] if r.reason else []
    parts += [f"{k}: {v}" for k, v in sorted(details_of(r).items()) if v is not None]
    return "; ".join(parts)


@jobs.handler(JOB)
def run(ctx: jobs.JobContext) -> dict:
    p = ctx.uow.principal
    # The job runs as whoever asked, a moment later; they may have lost access since.
    if not has_permission(member_role(ctx.uow.tx, p.business_id, p.user_id), Permission.AUDIT_VIEW):
        raise jobs.JobFailed("not_allowed")
    f = _filters(ctx)
    cap = int(value_on(ctx.uow.tx, "audit.export_max_rows", get_clock().today()))
    found = rows(ctx.uow, f, after=None, limit=cap + 1)
    if len(found) > cap:
        raise jobs.JobFailed("narrow_filter")
    body = to_csv(HEADER, (
        (f"{r.at.astimezone(IST):%Y-%m-%d %H:%M:%S}", actor_of(r)[1], audit_labels.label(r.action), _detail(r))
        for r in found
    ))
    key = key_for(p.business_id, AREA, ctx.job_id, FILE_NAME)
    get_store().put(p.business_id, key, body.encode("utf-8-sig"), "text/csv; charset=utf-8")
    return {"rows": len(found)}
