"""Job status routes (LLD-0 §3.7): every role of a business can poll its own jobs.

    GET /api/v1/b/{business_id}/jobs/{job_id}
    GET /api/v1/b/{business_id}/jobs?recent=1

A job of another business, or an ID that isn't a job, is the same 404 as an unknown
business: row-level security hides it, and the filter on business_id says so twice.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from . import jobs
from .errors import Deny
from .permissions import Permission, require
from .uow import BusinessUoW, parse_id

router = APIRouter(tags=["jobs"])


class ProgressOut(BaseModel):
    done: int
    out_of: int | None  # "of N" when the handler knows N


class JobOut(BaseModel):
    id: str
    type: str
    status: Literal["queued", "running", "done", "failed", "failed_retryable"]
    attempt: int
    progress: ProgressOut | None
    result: dict | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class JobsOut(BaseModel):
    items: list[JobOut]


def _out(j: jobs.JobView) -> JobOut:
    progress = None if j.progress_done is None else ProgressOut(done=j.progress_done, out_of=j.progress_total)
    return JobOut(id=str(j.id), type=j.type, status=j.status, attempt=j.attempt, progress=progress,
                  result=j.result, error_code=j.error_code, created_at=j.created_at, updated_at=j.updated_at)


@router.get("/b/{business_id}/jobs/{job_id}", response_model=JobOut,
            dependencies=[Depends(require(Permission.JOBS_VIEW))])
def get_job(job_id: str, uow: BusinessUoW):
    job = jobs.get(uow, parse_id(job_id))
    if job is None:
        raise Deny("not_found")
    return _out(job)


@router.get("/b/{business_id}/jobs", response_model=JobsOut,
            dependencies=[Depends(require(Permission.JOBS_VIEW))])
def recent_jobs(uow: BusinessUoW, recent: bool = True):  # noqa: ARG001 (only ?recent=1 exists today)
    return JobsOut(items=[_out(j) for j in jobs.recent(uow)])
