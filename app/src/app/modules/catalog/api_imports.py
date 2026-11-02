"""Product CSV import routes (LLD-3 §6.3, §7) under /api/v1/b/{business_id}.

The file goes straight to the object store on a presigned POST (H-4); `complete` queues
the parse job, `confirm` the apply job, and the client polls GET /jobs/{job_id} and then
the import. Nothing is saved to products before confirm.

Mounted before the product routes, so /products/import-template isn't read as a product ID.
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from app.modules.refdata import value_on
from platform_common import jobs, storage
from platform_common.clock import Clock, get_clock
from platform_common.paging import PageParams, page_params
from platform_common.uow import BusinessUoW, parse_id

from . import import_jobs
from . import product_import as imp
from .api_products import EDIT, VIEW, _once

router = APIRouter(tags=["catalog"])
RowStatus = Literal["new", "changed", "unchanged", "invalid", "conflict"]


class ImportStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: Annotated[str, Field(max_length=imp.MAX_FILE_NAME)]
    size_bytes: StrictInt


class UploadOut(BaseModel):
    url: str
    fields: dict[str, str]
    expires_at: datetime


class ImportStartOut(BaseModel):
    import_id: str
    upload: UploadOut


class JobRef(BaseModel):
    job_id: str


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apply_changes: StrictBool  # false: only new products are created


class ImportRowOut(BaseModel):
    row_number: int  # the file's row, counting the header as row 1
    status: RowStatus
    values: dict[str, str | bool | None]
    product_id: str | None
    diff: list[dict[str, str | None]] | None
    errors: list[dict[str, str]] | None
    outcome: Literal["applied", "stale", "skipped"] | None


class ImportOut(BaseModel):
    id: str
    file_name: str
    status: Literal["awaiting_upload", "parsing", "preview", "applying", "applied", "discarded", "failed"]
    counts: dict[str, int] | None
    error_code: str | None
    error_message: str | None
    duplicate_of: str | None  # the run that already imported this file
    superseded_by: str | None  # the later upload of this file that replaced this preview
    apply_changes: bool | None
    created_at: datetime
    rows: list[ImportRowOut]
    has_more: bool


def _str(value) -> str | None:
    return None if value is None else str(value)


def _out(run: imp.Run, rows: list[dict] = (), has_more: bool = False) -> ImportOut:
    return ImportOut(
        id=str(run.id), file_name=run.file_name, status=run.status, counts=run.counts, error_code=run.error_code,
        error_message=run.error_message, duplicate_of=_str(run.duplicate_of), superseded_by=_str(run.superseded_by),
        apply_changes=run.apply_changes, created_at=run.created_at, has_more=has_more,
        rows=[ImportRowOut(row_number=r["row_number"], status=r["status"], values=r["parsed"],
                           product_id=_str(r["product_id"]), diff=r["diff"], errors=r["errors"], outcome=r["outcome"])
              for r in rows],
    )


@router.get("/b/{business_id}/products/import-template", dependencies=VIEW,
            response_class=Response, responses={http.HTTP_200_OK: {"content": {"text/csv": {}}}})
def import_template():
    """The header row of the product file (§7.1). Column names are matched exactly."""
    return Response(imp.template_csv(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="products-template.csv"'})


@router.post("/b/{business_id}/product-imports", status_code=http.HTTP_201_CREATED, response_model=ImportStartOut,
             dependencies=EDIT)
def start_import(
    body: ImportStartIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """A run and a presigned POST for exactly its key, at most catalog.import.max_bytes."""
    today = clock.today()

    def start():
        run = imp.start(uow, body.file_name, body.size_bytes, today)
        most = int(value_on(uow.tx, "catalog.import.max_bytes", today))
        post = storage.get_store().presign_post(uow.principal.business_id, run.s3_key, max_bytes=most)
        return ImportStartOut(import_id=str(run.id), upload=UploadOut(
            url=post.url, fields=post.fields, expires_at=post.expires_at)).model_dump(mode="json")

    return _once(request, uow, idempotency_key, body.model_dump(mode="json"), start)


@router.post("/b/{business_id}/product-imports/{import_id}/complete", status_code=http.HTTP_202_ACCEPTED,
             response_model=JobRef, dependencies=EDIT)
def complete_import(import_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The upload finished: check it is there, then queue the parse. Calling it again
    returns the same job."""
    run = imp.uploaded(uow, parse_id(import_id), clock.today())
    return JobRef(job_id=str(jobs.create(uow, import_jobs.PARSE, natural_key=str(run.id))))


@router.get("/b/{business_id}/product-imports/{import_id}", response_model=ImportOut, dependencies=VIEW)
def get_import(import_id: str, uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)],
               rows: RowStatus | None = None):
    """The run and its preview rows of one status (or all), in file order."""
    run_id = parse_id(import_id)
    found, more = imp.rows(uow, run_id, rows, page.limit, page.offset)
    return _out(imp.get_run(uow, run_id), found, more)


@router.post("/b/{business_id}/product-imports/{import_id}/confirm", status_code=http.HTTP_202_ACCEPTED,
             response_model=JobRef, dependencies=EDIT)
def confirm_import(import_id: str, body: ConfirmIn, uow: BusinessUoW):
    """Queue the apply (AC3-13). The same confirm again, while it is queued, returns the same job."""
    run = imp.request_apply(uow, parse_id(import_id), body.apply_changes)
    return JobRef(job_id=str(jobs.create(uow, import_jobs.APPLY, natural_key=str(run.id))))


@router.post("/b/{business_id}/product-imports/{import_id}/discard", response_model=ImportOut, dependencies=EDIT)
def discard_import(import_id: str, uow: BusinessUoW):
    return _out(imp.discard(uow, parse_id(import_id)))
