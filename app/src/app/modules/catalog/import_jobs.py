"""The product import's two jobs (LLD-3 L3-8, §7.3, §7.4) on the job runner (#49).

Each runs as the business and the user who queued it, in one transaction with the job's
own status, so a crash rolls the run back and the runner retries it. A refusal that a
retry can't change (the run moved on, say) fails the job with the error's code.
"""

import uuid

from app.modules.identity.interface import member_role
from platform_common import jobs
from platform_common.clock import get_clock
from platform_common.errors import AppError, Deny
from platform_common.permissions import Permission, has_permission

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


def _still_allowed(ctx: jobs.JobContext, run_id: uuid.UUID) -> bool:
    """The job runs as the user who queued it, minutes later at most, but that user may
    have left the business or lost catalog.edit since (#69 review). Checked again here,
    from the membership as it is now; if not, the run ends failed with nothing saved."""
    p = ctx.uow.principal
    if has_permission(member_role(ctx.uow.tx, p.business_id, p.user_id), Permission.CATALOG_EDIT):
        return True
    if imp.get_run(ctx.uow, run_id).status in ("awaiting_upload", "parsing", "preview"):
        imp.fail(ctx.uow, run_id, "not_allowed", "Whoever started this import can no longer edit products")
    return False


@jobs.handler(PARSE)
def parse(ctx: jobs.JobContext) -> dict:
    run_id = _run_id(ctx)
    if not _still_allowed(ctx, run_id):
        return {"run_id": str(run_id), "status": "failed"}
    try:
        run = imp.get_run(ctx.uow, run_id)
        content = imp.read_upload(ctx.uow, run)
        done = imp.parse(ctx.uow, run_id, content, get_clock().today())
    except (AppError, Deny) as exc:
        raise jobs.JobFailed(getattr(exc, "code", None) or str(exc)) from None
    return {"run_id": str(run_id), "status": done.status}


@jobs.handler(APPLY)
def apply(ctx: jobs.JobContext) -> dict:
    """All or nothing. If the apply can't finish (a refusal, or the last attempt's error),
    its work is rolled back and the run ends `failed` in the same transaction, so the user
    sees why and can discard it or upload again instead of waiting on a dead job."""
    run_id = _run_id(ctx)
    if not _still_allowed(ctx, run_id):
        return {"run_id": str(run_id), "status": "failed"}
    run = imp.get_run(ctx.uow, run_id)
    try:
        with ctx.uow.tx.begin_nested():
            done = imp.apply(ctx.uow, run_id, bool(run.apply_changes), get_clock().today())
    except Exception as exc:
        last = ctx.attempt >= jobs.MAX_ATTEMPTS
        if not isinstance(exc, (AppError, Deny)) and not last:
            raise  # retried by the runner
        if imp.get_run(ctx.uow, run_id).status != "preview":
            raise jobs.JobFailed(getattr(exc, "code", None) or "error") from None  # applied meanwhile
        code = getattr(exc, "code", None) if isinstance(exc, AppError) else "apply_failed"
        imp.fail(ctx.uow, run_id, code, "The import couldn't be saved; nothing was changed. Upload the file again")
        return {"run_id": str(run_id), "status": "failed"}
    return {"run_id": str(run_id), "status": done.status}
