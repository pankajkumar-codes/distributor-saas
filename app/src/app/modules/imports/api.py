"""Upload routes (LLD-7 §8, R1-M3) under /api/v1/b/{business_id}.

The file goes straight to the object store on a presigned POST (H-4); `complete` queues
the parse job, and the client polls GET /jobs/{job_id} and then the upload. Owner and
admin upload (`uploads.create`); owner, admin and the CA read (`uploads.view`). Refusals
are 404 (LLD-0). Nothing here reaches a return.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from platform_common import jobs, storage
from platform_common.clock import Clock, get_clock
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import jobs as import_jobs
from . import uploads

router = APIRouter(tags=["imports"])
CREATE = [Depends(require(Permission.UPLOADS_CREATE))]
VIEW = [Depends(require(Permission.UPLOADS_VIEW))]
Section = Literal["amazon", "flipkart", "meesho", "own_invoices_excel", "own_invoices_pdf"]


class UploadStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Section
    file_name: Annotated[str, Field(max_length=uploads.MAX_FILE_NAME)]
    size_bytes: StrictInt


class PresignedPostOut(BaseModel):
    url: str
    fields: dict[str, str]
    expires_at: datetime


class UploadStartOut(BaseModel):
    upload_id: str
    upload: PresignedPostOut


class JobRef(BaseModel):
    job_id: str


class UploadOut(BaseModel):
    id: str
    section: Section
    file_name: str
    size_bytes: int
    status: Literal["pending", "received", "parsing", "parsed", "stored", "rejected", "expired"]
    reject_reason: str | None  # a code, for tests and logs
    reject_message: str | None  # plain words for the screen
    run_id: str | None
    created_at: datetime
    raw_available: bool  # false once the raw file has been purged


class UploadsOut(BaseModel):
    uploads: list[UploadOut]
    has_more: bool


def _out(up: uploads.Upload) -> UploadOut:
    return UploadOut(
        id=str(up.id), section=up.section, file_name=up.file_name, size_bytes=up.size_bytes, status=up.status,
        reject_reason=up.reject_reason, reject_message=up.reject_message,
        run_id=None if up.run_id is None else str(up.run_id), created_at=up.created_at,
        raw_available=up.raw_deleted_at is None,
    )


@router.post("/b/{business_id}/uploads", status_code=http.HTTP_201_CREATED, response_model=UploadStartOut,
             dependencies=CREATE)
def start_upload(
    body: UploadStartIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """An upload and a presigned POST for exactly its key, type and declared size."""
    today = clock.today()

    def start():
        up = uploads.start(uow, body.section, body.file_name, body.size_bytes, today)
        post = storage.get_store().presign_post(uow.principal.business_id, up.s3_key, max_bytes=body.size_bytes,
                                               content_type=uploads.content_type_for(up.file_name))
        return UploadStartOut(upload_id=str(up.id), upload=PresignedPostOut(
            url=post.url, fields=post.fields, expires_at=post.expires_at)).model_dump(mode="json")

    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload=body.model_dump(mode="json"), operation=start)


@router.post("/b/{business_id}/uploads/{upload_id}/complete", status_code=http.HTTP_202_ACCEPTED,
             response_model=JobRef, dependencies=CREATE)
def complete_upload(upload_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The upload finished: check it is there, then queue the parse. Calling it again
    returns the same job."""
    up = uploads.received(uow, parse_id(upload_id), clock.today())
    return JobRef(job_id=str(jobs.create(uow, import_jobs.PARSE, natural_key=str(up.id))))


@router.get("/b/{business_id}/uploads", response_model=UploadsOut, dependencies=VIEW)
def list_uploads(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)], section: Section | None = None):
    found, more = uploads.list_uploads(uow, section, page.limit, page.offset)
    return UploadsOut(uploads=[_out(u) for u in found], has_more=more)


@router.get("/b/{business_id}/uploads/{upload_id}", response_model=UploadOut, dependencies=VIEW)
def get_upload(upload_id: str, uow: BusinessUoW):
    return _out(uploads.get(uow, parse_id(upload_id)))
