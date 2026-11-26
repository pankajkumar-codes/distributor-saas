"""Purchase invoice routes (R2-M2) under /api/v1/b/{business_id}.

A file goes to the object store on a presigned POST, `complete` queues the read, the client polls the job and then
lists the file's drafts. The business confirms a draft with the values it checked, or discards it. Same permissions as
the other uploads: owner and admin upload and confirm (`uploads.create`), the CA also reads (`uploads.view`). Nothing
here reaches the catalog or stock. Refusals are 404 (LLD-0).
"""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from platform_common import jobs, storage
from platform_common.clock import Clock, get_clock
from platform_common.errors import Conflict
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from app.modules.catalog.interface import code_in_use

from . import jobs as import_jobs
from . import purchases
from .purchases import to_decimal

router = APIRouter(tags=["purchases"])
CREATE = [Depends(require(Permission.UPLOADS_CREATE))]
VIEW = [Depends(require(Permission.UPLOADS_VIEW))]
Amount = Annotated[str, Field(max_length=24)]  # a decimal string, parsed and checked by purchases.to_decimal


class PurchaseFileStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_name: Annotated[str, Field(max_length=purchases.MAX_FILE_NAME)]
    size_bytes: StrictInt


class PurchasePresignedPostOut(BaseModel):
    url: str
    fields: dict[str, str]
    expires_at: datetime


class PurchaseFileStartOut(BaseModel):
    file_id: str
    upload: PurchasePresignedPostOut


class PurchaseJobRef(BaseModel):
    job_id: str


class PurchaseFileOut(BaseModel):
    id: str
    file_name: str
    size_bytes: int
    kind: Literal["pdf", "image"]
    status: Literal["pending", "received", "read", "rejected"]
    reject_reason: str | None
    reject_message: str | None
    created_at: datetime


class PurchaseFilesOut(BaseModel):
    files: list[PurchaseFileOut]
    has_more: bool


def _file_out(f: purchases.PurchaseFile) -> PurchaseFileOut:
    return PurchaseFileOut(id=str(f.id), file_name=f.file_name, size_bytes=f.size_bytes, kind=f.kind, status=f.status,
                   reject_reason=f.reject_reason, reject_message=f.reject_message, created_at=f.created_at)


@router.post("/b/{business_id}/purchase-files", status_code=http.HTTP_201_CREATED, response_model=PurchaseFileStartOut,
             dependencies=CREATE)
def start_file(body: PurchaseFileStartIn, request: Request, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)],
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
    return PurchaseFileStartOut(file_id=str(f.id), upload=PurchasePresignedPostOut(url=post.url, fields=post.fields,
                                                                  expires_at=post.expires_at))


@router.post("/b/{business_id}/purchase-files/{file_id}/complete", status_code=http.HTTP_202_ACCEPTED,
             response_model=PurchaseJobRef, dependencies=CREATE)
def complete_file(file_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The upload finished: check it is there, then queue the read. Calling it again returns the same job."""
    f = purchases.received(uow, parse_id(file_id), clock.today())
    return PurchaseJobRef(job_id=str(jobs.create(uow, import_jobs.PURCHASE_PARSE, natural_key=str(f.id))))


@router.get("/b/{business_id}/purchase-files", response_model=PurchaseFilesOut, dependencies=VIEW)
def list_files(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)]):
    found, more = purchases.list_files(uow, page.limit, page.offset)
    return PurchaseFilesOut(files=[_file_out(f) for f in found], has_more=more)


@router.get("/b/{business_id}/purchase-files/{file_id}", response_model=PurchaseFileOut, dependencies=VIEW)
def get_file(file_id: str, uow: BusinessUoW):
    return _file_out(purchases.get_file(uow, parse_id(file_id)))


class PurchaseDraftLineOut(BaseModel):
    id: str
    line_no: int
    page: int
    description: str | None  # the item as read, offered as the product name to check (D-106); null if not read
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


class PurchaseDraftOut(BaseModel):
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
    lines: list[PurchaseDraftLineOut]
    decision: Literal["confirmed", "discarded"] | None


class PurchaseDraftsOut(BaseModel):
    drafts: list[PurchaseDraftOut]
    has_more: bool


def _draft_out(d: purchases.Draft) -> PurchaseDraftOut:
    return PurchaseDraftOut(
        id=str(d.id), file_id=str(d.file_id), file_name=d.file_name, ordinal=d.ordinal, reader=d.reader_id,
        pages=d.pages, doc_type=d.doc_type, supplier_gstin=d.supplier_gstin, doc_number=d.doc_number,
        doc_date=d.doc_date, invoice_total=d.invoice_total, unclear=d.unclear, decision=d.decision,
        lines=[PurchaseDraftLineOut(**{**ln.__dict__, "id": str(ln.id)}) for ln in d.lines])


@router.get("/b/{business_id}/purchase-drafts", response_model=PurchaseDraftsOut, dependencies=VIEW)
def list_drafts(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)], file_id: str | None = None,
                open_only: bool = False):
    found, more = purchases.list_drafts(uow, file_id=None if file_id is None else parse_id(file_id),
                                        open_only=open_only, limit=page.limit, offset=page.offset)
    return PurchaseDraftsOut(drafts=[_draft_out(d) for d in found], has_more=more)


@router.get("/b/{business_id}/purchase-drafts/{draft_id}", response_model=PurchaseDraftOut, dependencies=VIEW)
def get_draft(draft_id: str, uow: BusinessUoW):
    return _draft_out(purchases.get_draft(uow, parse_id(draft_id)))


class PurchaseNewItemIn(BaseModel):
    """A product to create from a line. The name and HSN are the line's own; the rate is the business's to confirm."""

    model_config = ConfigDict(extra="forbid")

    code: Annotated[str, Field(max_length=40)]
    uqc: Annotated[str, Field(max_length=8)]
    tax_category: Literal["taxable", "exempt", "nil_rated", "non_gst"]
    gst_rate: Annotated[str | None, Field(max_length=24)] = None  # required when taxable
    rate_valid_from: date | None = None  # required with gst_rate
    has_cess: bool = False


class PurchaseLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_line_id: str | None = None  # the read line this one came from; null for a line typed in
    product_id: str | None = None  # an existing catalog product, or `new_item`: exactly one of the two
    new_item: PurchaseNewItemIn | None = None
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


class PurchaseConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_gstin: Annotated[str, Field(max_length=40)]
    supplier_name: Annotated[str | None, Field(max_length=120)] = None
    doc_number: Annotated[str, Field(max_length=40)]
    doc_date: date
    invoice_total: Amount | None = None
    lines: list[PurchaseLineIn]


class PurchaseReceivedOut(BaseModel):
    line_no: int
    product_id: str
    created_product: bool
    price_needed: bool  # the selling price per 1 qty is still to be set (R2-M3)


class PurchaseWarningOut(BaseModel):
    line_no: int
    code: Literal["tax_differs_from_rate", "unit_differs_from_product"]


class PurchaseConfirmedOut(BaseModel):
    review_id: str
    draft_id: str
    supplier_gstin: str
    supplier_name: str | None
    doc_number: str
    doc_date: date
    invoice_total: str | None
    line_count: int
    created_at: datetime
    received: list[PurchaseReceivedOut] = []
    warnings: list[PurchaseWarningOut] = []


class PurchaseConfirmedListOut(BaseModel):
    invoices: list[PurchaseConfirmedOut]
    has_more: bool


def _confirmed_out(c: purchases.Confirmed) -> PurchaseConfirmedOut:
    return PurchaseConfirmedOut(review_id=str(c.review_id), draft_id=str(c.draft_id), supplier_gstin=c.supplier_gstin,
                        supplier_name=c.supplier_name, doc_number=c.doc_number, doc_date=c.doc_date,
                        invoice_total=None if c.invoice_total is None else str(c.invoice_total), line_count=c.line_count,
                        created_at=c.created_at,
                        received=[PurchaseReceivedOut(line_no=n, product_id=str(p), created_product=cp, price_needed=pn)
                                  for n, p, cp, pn in c.received],
                        warnings=[PurchaseWarningOut(line_no=n, code=code) for n, code in c.warnings])


@router.post("/b/{business_id}/purchase-drafts/{draft_id}/confirm", status_code=http.HTTP_201_CREATED,
             response_model=PurchaseConfirmedOut, dependencies=CREATE)
def confirm_draft(draft_id: str, body: PurchaseConfirmIn, uow: BusinessUoW, request: Request,
                  clock: Annotated[Clock, Depends(get_clock)],
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    """The business confirms the invoice with the values it checked on the review screen. Once; a second call is a
    conflict, not a second invoice. With an Idempotency-Key, a retry of the same request returns the first answer."""
    if idempotency_key is None:
        return _confirm(uow, draft_id, body, clock)
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"draft": draft_id, **body.model_dump(mode="json")},
                    operation=lambda: _confirm(uow, draft_id, body, clock).model_dump(mode="json"))


def _confirm(uow, draft_id: str, body: PurchaseConfirmIn, clock: Clock) -> PurchaseConfirmedOut:
    lines = [purchases.LineIn(
        draft_line_id=None if ln.draft_line_id is None else parse_id(ln.draft_line_id),
        product_id=None if ln.product_id is None else parse_id(ln.product_id),
        new_item=None if ln.new_item is None else purchases.ItemIn(**ln.new_item.model_dump()), product_name=ln.product_name,
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


@router.post("/b/{business_id}/purchase-drafts/{draft_id}/discard", response_model=PurchaseDraftOut, dependencies=CREATE)
def discard_draft(draft_id: str, uow: BusinessUoW, request: Request,
                  idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None):
    if idempotency_key is None:
        return _draft_out(purchases.discard(uow, parse_id(draft_id)))
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"draft": draft_id},
                    operation=lambda: _draft_out(purchases.discard(uow, parse_id(draft_id))).model_dump(mode="json"))


@router.get("/b/{business_id}/purchase-invoices", response_model=PurchaseConfirmedListOut, dependencies=VIEW)
def list_purchase_invoices(uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)]):
    found, more = purchases.list_confirmed(uow, page.limit, page.offset)
    return PurchaseConfirmedListOut(invoices=[_confirmed_out(c) for c in found], has_more=more)


class PurchaseCodeCheckOut(BaseModel):
    code: str
    available: bool


@router.get("/b/{business_id}/purchase-code-check", response_model=PurchaseCodeCheckOut, dependencies=VIEW)
def check_item_code(code: Annotated[str, Query(max_length=40)], uow: BusinessUoW):
    """For the review screen: is this product code free? The confirm still refuses a taken code."""
    return PurchaseCodeCheckOut(code=code.strip(), available=not code_in_use(uow.tx, code))
