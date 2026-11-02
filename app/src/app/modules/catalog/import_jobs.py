"""The product import's two jobs (LLD-3 L3-8, §7.3, §7.4) on the job runner (#49).

Each runs as the business and the user who queued it, in one transaction with the job's
own status, so a crash rolls the run back and the runner retries it. A refusal that a
retry can't change (the run moved on, say) fails the job with the error's code.
"""

import uuid

from platform_common import jobs
from platform_common.clock import get_clock
from platform_common.errors import AppError, Deny

from . import product_import as imp

PARSE = "catalog.import_parse"
APPLY = "catalog.import_apply"


def _run_id(ctx: jobs.JobContext) -> uuid.UUID:
    """The run is the job's natural key, read from the job row under RLS, never from the
    queue message."""
    view = jobs.get(ctx.uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    return uuid.UUID(view.natural_key)


@jobs.handler(PARSE)
def parse(ctx: jobs.JobContext) -> dict:
    run_id = _run_id(ctx)
    try:
        run = imp.get_run(ctx.uow, run_id)
        content = imp.read_upload(ctx.uow, run)
        done = imp.parse(ctx.uow, run_id, content, get_clock().today())
    except (AppError, Deny) as exc:
        raise jobs.JobFailed(getattr(exc, "code", None) or str(exc)) from None
    return {"run_id": str(run_id), "status": done.status}


@jobs.handler(APPLY)
def apply(ctx: jobs.JobContext) -> dict:
    run_id = _run_id(ctx)
    try:
        run = imp.get_run(ctx.uow, run_id)
        done = imp.apply(ctx.uow, run_id, bool(run.apply_changes), get_clock().today())
    except (AppError, Deny) as exc:
        raise jobs.JobFailed(getattr(exc, "code", None) or str(exc)) from None
    return {"run_id": str(run_id), "status": done.status}
