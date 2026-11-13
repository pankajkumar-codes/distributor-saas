"""The upload parse job (LLD-7 §10) on the job runner.

Runs as the business and user who queued it, in one transaction with the job's own
status. It re-checks that user's role when it runs (they may have left the business or
lost the permission since, as in catalog's import jobs), and it takes the business only
from the claimed job, never from the queue message.
"""

import uuid

from app.modules.identity.interface import member_role
from platform_common import jobs
from platform_common.errors import AppError, Deny
from platform_common.permissions import Permission, has_permission

from . import uploads

PARSE = "imports.parse"


def _upload_id(ctx: jobs.JobContext) -> uuid.UUID:
    """The upload is the job's natural key, read from the job row under RLS."""
    view = jobs.get(ctx.uow, ctx.job_id)
    if view is None or not view.natural_key:
        raise jobs.JobFailed("not_found")
    return uuid.UUID(view.natural_key)


@jobs.handler(PARSE)
def parse(ctx: jobs.JobContext) -> dict:
    upload_id = _upload_id(ctx)
    p = ctx.uow.principal
    if not has_permission(member_role(ctx.uow.tx, p.business_id, p.user_id), Permission.UPLOADS_CREATE):
        try:
            if uploads.get(ctx.uow, upload_id).status == "received":
                uploads.reject(ctx.uow, upload_id, "not_allowed")
        except (AppError, Deny):
            pass
        return {"upload_id": str(upload_id), "status": "rejected"}
    try:
        with ctx.uow.tx.begin_nested():
            done = uploads.process(ctx.uow, upload_id)
    except (AppError, Deny) as exc:
        # A file we cannot use is settled here, so the screen sees one status. A JobFailed
        # would roll this transaction back and leave the upload "received".
        code = getattr(exc, "code", None) or "read_failed"
        _settle(ctx, upload_id, "read_failed")
        return {"upload_id": str(upload_id), "status": "rejected", "error": str(code)}
    except Exception:
        if ctx.attempt >= jobs.MAX_ATTEMPTS:
            _settle(ctx, upload_id, "read_failed")
            return {"upload_id": str(upload_id), "status": "rejected", "error": "read_failed"}
        raise  # rolled back, retried
    return {"upload_id": str(upload_id), "status": done.status}


def _settle(ctx: jobs.JobContext, upload_id: uuid.UUID, reason: str) -> None:
    try:
        if uploads.get(ctx.uow, upload_id).status == "received":
            uploads.reject(ctx.uow, upload_id, reason)
    except (AppError, Deny):
        pass
