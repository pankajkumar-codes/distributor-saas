"""Purchase invoice routes (R2-M2) under /api/v1/b/{business_id}.

A file goes to the object store on a presigned POST, `complete` queues the read, the client polls the job and then
lists the file's drafts. The business confirms a draft with the values it checked, or discards it. Same permissions as
the other uploads: owner and admin upload and confirm (`uploads.create`), the CA also reads (`uploads.view`). Nothing
here reaches the catalog or stock. Refusals are 404 (LLD-0).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Request
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
from . import purchases
from .purchases import to_decimal

router = APIRouter(tags=["purchases"])
CREATE = [Depends(require(Permission.UPLOADS_CREATE))]
VIEW = [Depends(require(Permission.UPLOADS_VIEW))]
Amount = Annotated[str, Field(max_length=24)]  # a decimal string, parsed and checked by purchases.to_decimal


class FileStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: Annotated[str, Field(max_length=purchases.MAX_FILE_NAME)]
    size_bytes: StrictInt


class PresignedPostOut(BaseModel):
    url: str
    fields: dict[str, str]
    expires_at: datetime


class FileStartOut(BaseModel):
    file_id: str
    upload: PresignedPostOut


class JobRef(BaseModel):
    job_id: str


class FileOut(BaseModel):
    id: str
    file_name: str
    size_bytes: int
    kind: Literal["pdf", "image"]
    status: Literal["pending", "received", "read", "rejected"]
    reject_reason: str | None
    reject_message: str | None
    created_at: datetime


class FilesOut(BaseModel):
    files: list[FileOut]
    has_more: bool


def _file_out(f: purchases.PurchaseFile) -> FileOut:
    return FileOut(id=str(f.id), file_name=f.file_name, size_bytes=f.size_bytes, kind=f.kind, status=f.status,
                   reject_reason=f.reject_reason, reject_message=f.reject_message, created_at=f.created_at)


@router.post("/b/{business_id}/purchase-files", status_code=http.HTTP_201_CREATED, response_model=FileStartOut,
             dependencies=CREATE)
def start_file(body: FileStartIn, request: Request, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)],
               idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    """A purchase file and a presigned POST for exactly its key, type and declared size."""
    today = clock.today()

    def start():
        return {"file_id": str(purchases.start(uow, body.file_name, body.size_bytes, today).id)}

    done = run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload=body.model_dump(mode="json"), operation=start)
    f = purchases.get_file(uow, parse_id(done["file_id"]))
    if f.status != "pending":
        raise Conflict("upload_already_started", "This upload has already moved on. Start a new one")
    post = storage.get_store().presign_post(uow.principal.business_id, f.s3_key, max_bytes=f.size_bytes,
                                           content_type=purchases.content_type_for(f.file_name))
    return FileStartOut(file_id=str(f.id), upload=PresignedPostOut(url=post.url, fields=post.fields,
                                                                  expires_at=post.expires_at))


@router.post("/b/{business_id}/purchase-files/{file_id}/complete", status_code=http.HTTP_202_ACCEPTED,
             response_model=JobRef, dependencies=CREATE)
def complete_file(file_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The upload finished: check it is there, then queue the read. Calling it again returns the same job."""
    f = purchases.received(uow, parse_id(file_id), clock.today())
    return JobRef(job_id=str(jobs.create(uow, import_jobs.PURCHASE_PARSE, natural_key=str(f.id))))


@router.get("/b/{business_id}/purchase-files", response_model=FilesOut, dependencies=VIEW)
def list_files(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)]):
    found, more = purchases.list_files(uow, page.limit, page.offset)
    return FilesOut(files=[_file_out(f) for f in found], has_more=more)


@router.get("/b/{business_id}/purchase-files/{file_id}", response_model=FileOut, dependencies=VIEW)
def get_file(file_id: str, uow: BusinessUoW):
    return _file_out(purchases.get_file(uow, parse_id(file_id)))


class DraftLineOut(BaseModel):
    id: str
    line_no: int
    page: int
    hsn: str | None
    quantity: str | None
    unit: str | None
    taxable_value: str | None
    gst_rate: str | None
    igst: str | None
    cgst: str | None
    sgst: str | None
    cess: str | None
    unclear: list[str]  # field names only, so the screen marks what to check


class DraftOut(BaseModel):
    id: str
    file_id: str
    file_name: str
    ordinal: int
    reader: str  # "pdf_text_v1", or "none" when nothing could be read and the business types it in
    pages: list[int]
    doc_type: str | None
    supplier_gstin: str | None
    doc_number: str | None
    doc_date: str | None  # as read, DD-MM-YYYY
    invoice_total: str | None
    unclear: list[str]
    lines: list[DraftLineOut]
    decision: Literal["confirmed", "discarded"] | None


class DraftsOut(BaseModel):
    drafts: list[DraftOut]
    has_more: bool


def _draft_out(d: purchases.Draft) -> DraftOut:
    return DraftOut(
        id=str(d.id), file_id=str(d.file_id), file_name=d.file_name, ordinal=d.ordinal, reader=d.reader_id,
        pages=d.pages, doc_type=d.doc_type, supplier_gstin=d.supplier_gstin, doc_number=d.doc_number,
        doc_date=d.doc_date, invoice_total=d.invoice_total, unclear=d.unclear, decision=d.decision,
        lines=[DraftLineOut(**{**ln.__dict__, "id": str(ln.id)}) for ln in d.lines])


@router.get("/b/{business_id}/purchase-drafts", response_model=DraftsOut, dependencies=VIEW)
def list_drafts(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)], file_id: str | None = None,
                open_only: bool = False):
    found, more = purchases.list_drafts(uow, file_id=None if file_id is None else parse_id(file_id),
                                        open_only=open_only, limit=page.limit, offset=page.offset)
    return DraftsOut(drafts=[_draft_out(d) for d in found], has_more=more)


@router.get("/b/{business_id}/purchase-drafts/{draft_id}", response_model=DraftOut, dependencies=VIEW)
def get_draft(draft_id: str, uow: BusinessUoW):
    return _draft_out(purchases.get_draft(uow, parse_id(draft_id)))


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_line_id: str | None = None  # the read line this one came from; null for a line typed in
    product_name: Annotated[str, Field(max_length=120)]
    hsn: Annotated[str, Field(max_length=8)]
    quantity: Amount
    unit: Annotated[str | None, Field(max_length=40)] = None
    taxable_value: Amount
    gst_rate: Amount
    igst: Amount = "0"
    cgst: Amount = "0"
    sgst: Amount = "0"
    cess: Amount = "0"


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_gstin: Annotated[str, Field(max_length=40)]
    supplier_name: Annotated[str | None, Field(max_length=120)] = None
    doc_number: Annotated[str, Field(max_length=40)]
    doc_date: date
    invoice_total: Amount | None = None
    lines: list[LineIn]


class ConfirmedOut(BaseModel):
    review_id: str
    draft_id: str
    supplier_gstin: str
    supplier_name: str | None
    doc_number: str
    doc_date: date
    invoice_total: str | None
    line_count: int
    created_at: datetime


class ConfirmedListOut(BaseModel):
    invoices: list[ConfirmedOut]
    has_more: bool


def _confirmed_out(c: purchases.Confirmed) -> ConfirmedOut:
    return ConfirmedOut(review_id=str(c.review_id), draft_id=str(c.draft_id), supplier_gstin=c.supplier_gstin,
                        supplier_name=c.supplier_name, doc_number=c.doc_number, doc_date=c.doc_date,
                        invoice_total=None if c.invoice_total is None else str(c.invoice_total), line_count=c.line_count, created_at=c.created_at)


@router.post("/b/{business_id}/purchase-drafts/{draft_id}/confirm", status_code=http.HTTP_201_CREATED,
             response_model=ConfirmedOut, dependencies=CREATE)
def confirm_draft(draft_id: str, body: ConfirmIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The business confirms the invoice with the values it checked on the review screen. Once; a second call is a
    conflict, not a second invoice."""
    lines = [purchases.LineIn(
        draft_line_id=None if ln.draft_line_id is None else parse_id(ln.draft_line_id), product_name=ln.product_name,
        hsn=ln.hsn, quantity=to_decimal(ln.quantity, f"lines.{i}.quantity"),
        unit=ln.unit, taxable_value=to_decimal(ln.taxable_value, f"lines.{i}.taxable_value"),
        gst_rate=to_decimal(ln.gst_rate, f"lines.{i}.gst_rate"), igst=to_decimal(ln.igst, f"lines.{i}.igst"),
        cgst=to_decimal(ln.cgst, f"lines.{i}.cgst"), sgst=to_decimal(ln.sgst, f"lines.{i}.sgst"),
        cess=to_decimal(ln.cess, f"lines.{i}.cess")) for i, ln in enumerate(body.lines)]
    done = purchases.confirm(uow, parse_id(draft_id), supplier_gstin=body.supplier_gstin,
                             supplier_name=body.supplier_name, doc_number=body.doc_number, doc_date=body.doc_date,
                             invoice_total=None if body.invoice_total is None else to_decimal(body.invoice_total, "invoice_total"),
                             lines=lines, today=clock.today())
    return _confirmed_out(done)


@router.post("/b/{business_id}/purchase-drafts/{draft_id}/discard", response_model=DraftOut, dependencies=CREATE)
def discard_draft(draft_id: str, uow: BusinessUoW):
    return _draft_out(purchases.discard(uow, parse_id(draft_id)))


@router.get("/b/{business_id}/purchase-invoices", response_model=ConfirmedListOut, dependencies=VIEW)
def list_purchase_invoices(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)]):
    found, more = purchases.list_confirmed(uow, page.limit, page.offset)
    return ConfirmedListOut(invoices=[_confirmed_out(c) for c in found], has_more=more)
