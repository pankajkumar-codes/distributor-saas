"""Upload routes (LLD-7 §8, R1-M3) under /api/v1/b/{business_id}.

The file goes straight to the object store on a presigned POST (H-4); `complete` queues
the parse job, and the client polls GET /jobs/{job_id} and then the upload. Owner and
admin upload (`uploads.create`); owner, admin and the CA read (`uploads.view`). Refusals
are 404 (LLD-0). Nothing here reaches a return.
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from platform_common import jobs, storage
from platform_common.clock import Clock, get_clock
from platform_common.errors import Conflict
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import jobs as import_jobs
from . import confirm, coverage, runs, sections, template, uploads

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
    run_id: str | None  # the first run (a zip makes one per file)
    run_ids: list[str]  # every run this upload made, in file order
    created_at: datetime
    raw_available: bool  # false once the raw file has been purged


class UploadsOut(BaseModel):
    uploads: list[UploadOut]
    has_more: bool


def _out(up: uploads.Upload, run_ids: list | None = None) -> UploadOut:
    return UploadOut(
        run_ids=[str(r) for r in run_ids or []],
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
        return {"upload_id": str(up.id)}  # the signed post is not stored: it would expire inside the replay

    done = run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload=body.model_dump(mode="json"), operation=start)
    # Signed afresh on every call, so a retry with the same key gets a live post for the same upload.
    up = uploads.get(uow, parse_id(done["upload_id"]))
    if up.status != "pending":
        raise Conflict("upload_already_started", "This upload has already moved on. Start a new one")
    post = storage.get_store().presign_post(uow.principal.business_id, up.s3_key, max_bytes=up.size_bytes,
                                           content_type=uploads.content_type_for(up.file_name))
    return UploadStartOut(upload_id=str(up.id), upload=PresignedPostOut(
        url=post.url, fields=post.fields, expires_at=post.expires_at))


@router.post("/b/{business_id}/uploads/{upload_id}/complete", status_code=http.HTTP_202_ACCEPTED,
             response_model=JobRef, dependencies=CREATE)
def complete_upload(upload_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The upload finished: check it is there, then queue the parse. Calling it again
    returns the same job."""
    up = uploads.received(uow, parse_id(upload_id), clock.today())
    return JobRef(job_id=str(jobs.create(uow, import_jobs.PARSE, natural_key=str(up.id))))


@router.get("/b/{business_id}/uploads", response_model=UploadsOut, dependencies=VIEW)
def list_uploads(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)], section: Section | None = None,
                 from_: Annotated[date | None, Query(alias="from")] = None, to: date | None = None):
    found, more = uploads.list_uploads(uow, section, page.limit, page.offset, uploads.month_range(from_, to))
    ids = runs.run_ids_for(uow, [u.id for u in found])
    return UploadsOut(uploads=[_out(u, ids[u.id]) for u in found], has_more=more)


@router.get("/b/{business_id}/uploads/own-invoices-template", dependencies=VIEW, response_class=Response,
            responses={http.HTTP_200_OK: {"content": {template.CONTENT_TYPE: {}}}})
def own_invoices_template():
    """The Excel template for the own-invoices section: an `Invoices` sheet with the header row and a `How to
    fill` sheet. No values. Declared before the upload id route so the name is not read as an id."""
    return Response(template.build(), media_type=template.CONTENT_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="{template.FILE_NAME}"'})


@router.get("/b/{business_id}/uploads/{upload_id}", response_model=UploadOut, dependencies=VIEW)
def get_upload(upload_id: str, uow: BusinessUoW):
    up = uploads.get(uow, parse_id(upload_id))
    return _out(up, runs.run_ids_for(uow, [up.id])[up.id])


class RunOut(BaseModel):
    months: list[str]
    already_uploaded_of: str | None
    id: str
    upload_id: str | None
    section: Section | None
    reader: str  # the profile id the file was read with
    profile_verified: bool
    gstin: str | None
    status: Literal["staged", "confirmed", "discarded"]
    counts: dict[str, int]  # new, already_imported, changed, duplicate, conflict, invalid, held, skipped_zero
    held_by_reason: dict[str, int]
    warnings: list[dict[str, str]]
    columns_not_stored: list[str]


ACTIONS = Literal["set_aside", "accept", "enter_hsn", "pick_state"]


class ActionOut(BaseModel):
    action: ACTIONS
    label: str
    effect_note: str


class ResolutionOut(BaseModel):
    action: ACTIONS
    note: str
    at: datetime
    value: str | None = None  # what the user entered or picked, for a fix


class RowOut(BaseModel):
    row_id: str
    run_id: str
    file_name: str
    row_number: int
    status: Literal["new", "already_imported", "changed", "duplicate", "conflict", "invalid", "held", "skipped_zero"]
    hold_reason: str | None  # a code, for tests and logs
    reason_label: str | None  # plain words for the screen
    values: dict[str, str]  # the cells as read: non-personal mapped cells only
    errors: list[dict[str, str | None]]
    needs_ca_check: bool
    ca_check_note: str | None
    allowed_actions: list[ActionOut]
    resolution: ResolutionOut | None


class RowsOut(BaseModel):
    rows: list[RowOut]
    has_more: bool


EMPTY = {"code": "no_rows", "message": "This report had no rows."}
UNVERIFIED = {"code": "layout_unchecked",
              "message": "We can read this report but haven't checked its layout yet."}


def _run_out(run: runs.Run) -> RunOut:
    return RunOut(
        id=str(run.id), upload_id=None if run.upload_id is None else str(run.upload_id), section=run.section,
        reader=run.profile_id, profile_verified=run.profile_verified, gstin=run.gstin, status=run.status,
        counts=runs.counts(run), held_by_reason=run.held_by_reason,
        months=list(run.summary.get("months", [])), already_uploaded_of=run.summary.get("already_uploaded_of"),
        warnings=([] if run.profile_verified else [UNVERIFIED]) + ([] if run.summary.get("total", 1) else [EMPTY]),
        columns_not_stored=list(run.summary.get("columns_not_stored", [])),
    )


@router.get("/b/{business_id}/runs/{run_id}", response_model=RunOut, dependencies=VIEW)
def get_run(run_id: str, uow: BusinessUoW):
    return _run_out(runs.get_run(uow, parse_id(run_id)))


@router.get("/b/{business_id}/runs/{run_id}/rows", response_model=RowsOut, dependencies=VIEW)
def list_rows(run_id: str, uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)],
              clock: Annotated[Clock, Depends(get_clock)], status: str | None = None):
    found, more = runs.list_rows(uow, parse_id(run_id), status, page.limit, page.offset, clock.today())
    return RowsOut(has_more=more, rows=[_row_out(r) for r in found])


def _row_out(r: runs.Row) -> RowOut:
    return RowOut(row_id=str(r.id), run_id=str(r.run_id), file_name=r.file_name, row_number=r.row_number,
                  status=r.status, hold_reason=r.hold_reason, reason_label=r.reason_label, values=r.values,
                  errors=r.errors, needs_ca_check=r.needs_ca_check, ca_check_note=r.ca_check_note,
                  allowed_actions=[ActionOut(**a) for a in r.allowed_actions],
                  resolution=None if r.resolution is None else ResolutionOut(**r.resolution))


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ACTIONS
    note: str
    value: str | None = None  # the HSN or the state code, for `enter_hsn` and `pick_state`


@router.post("/b/{business_id}/rows/{row_id}/resolve", response_model=RowOut, dependencies=CREATE)
def resolve_row(row_id: str, body: ResolveIn, request: Request, uow: BusinessUoW,
                clock: Annotated[Clock, Depends(get_clock)],
                idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    """Decide a held row: leave it out (with a note), or, where allowed, use it as the file
    states it. The decision is kept and audited; the preview and the section update at once."""
    today = clock.today()
    rid = parse_id(row_id)

    def decide():
        return _row_out(runs.resolve(uow, rid, body.action, body.note, today, body.value)).model_dump(mode="json")

    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"row": row_id, **body.model_dump(mode="json")},
                    operation=decide)


class BlockerOut(BaseModel):
    code: str
    label: str
    count: int
    rows: list[int]  # row numbers, the first 20


class NoteOut(BaseModel):
    code: str
    label: str


class ConfirmCheckOut(BaseModel):
    run_id: str
    can_confirm: bool
    included: int
    changed: int
    left_out: dict[str, int]  # set_aside, already_imported, duplicate, skipped_zero
    blockers: list[BlockerOut]
    notes: list[NoteOut]


@router.get("/b/{business_id}/runs/{run_id}/confirm-check", response_model=ConfirmCheckOut, dependencies=VIEW)
def confirm_check(run_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """What stops this staged run being confirmed, with counts and row numbers (never cell values). Read-only."""
    out = confirm.check(uow, parse_id(run_id), clock.today())
    return ConfirmCheckOut(
        run_id=str(out.run_id), can_confirm=out.can_confirm, included=out.included, changed=out.changed,
        left_out=out.left_out, blockers=[BlockerOut(**b.__dict__ | {"rows": list(b.rows)}) for b in out.blockers],
        notes=[NoteOut(code=n.code, label=n.label) for n in out.notes])


@router.post("/b/{business_id}/runs/{run_id}/discard", response_model=RunOut, dependencies=CREATE)
def discard_run(run_id: str, uow: BusinessUoW):
    """Set a staged preview aside. The same file can be uploaded again."""
    return _run_out(runs.discard_run(uow, parse_id(run_id)))


class SectionOut(BaseModel):
    section: Section
    enabled: bool
    status: Literal["not uploaded", "processing", "ready", "rows held"]
    uploads: list[UploadOut]
    held_rows: int
    needs_ca_check: bool
    requirement_note: str | None


class SectionsOut(BaseModel):
    sections: list[SectionOut]


@router.get("/b/{business_id}/upload-sections", response_model=SectionsOut, dependencies=VIEW)
def list_sections(uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)],
                  from_: Annotated[date | None, Query(alias="from")] = None, to: date | None = None):
    found = sections.sections(uow, clock.today(), uploads.month_range(from_, to))
    ids = runs.run_ids_for(uow, [u.id for s in found for u in s.uploads])
    return SectionsOut(sections=[
        SectionOut(section=s.section, enabled=s.enabled, status=s.status, held_rows=s.held_rows,
                   needs_ca_check=s.needs_ca_check, requirement_note=s.requirement_note,
                   uploads=[_out(u, ids[u.id]) for u in s.uploads])
        for s in found])



class PlatformMonthOut(BaseModel):
    marketplace: Literal["amazon", "flipkart", "meesho"]
    required: list[str]
    received: list[str]
    complete: bool
    held_rows: int


class MonthCoverageOut(BaseModel):
    month: str
    marketplaces: list[PlatformMonthOut]


class CoverageOut(BaseModel):
    months: list[MonthCoverageOut]


@router.get("/b/{business_id}/marketplace-coverage", response_model=CoverageOut, dependencies=VIEW)
def marketplace_coverage(uow: BusinessUoW, from_: Annotated[date | None, Query(alias="from")] = None,
                         to: date | None = None):
    """Which marketplace files are in, per month any live preview covers. Read-only."""
    return CoverageOut(months=[
        MonthCoverageOut(month=m.month, marketplaces=[PlatformMonthOut(**vars(p)) for p in m.marketplaces])
        for m in coverage.coverage(uow, from_, to)])
