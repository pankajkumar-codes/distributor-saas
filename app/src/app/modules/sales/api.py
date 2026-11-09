"""Invoice draft routes (LLD-4 §9) under /api/v1/b/{business_id}.

POST takes an Idempotency-Key (run_once); PUT saves the whole draft and DELETE removes an
open one, both under If-Match with the version the user saw. Money and quantities are
strings: a JSON number is a 422 (AC4-15). Viewing needs the view-documents permission, changing needs
the create-documents one.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from platform_common.clock import Clock, get_clock
from platform_common.etag import if_match_version, set_etag
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import drafts, preview

router = APIRouter(tags=["sales"])
VIEW = [Depends(require(Permission.DOCUMENTS_VIEW))]
EDIT = [Depends(require(Permission.DOCUMENTS_CREATE))]

Text = Annotated[str, Field(max_length=300)]
# A string only: a JSON number is refused by the type, so a float never reaches money().
Amount = Annotated[str, Field(max_length=24)]


class LineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    quantity: Amount
    unit_price: Amount | None = None  # the product's sale rate when left out
    discount_kind: Literal["amount", "percent"] | None = None
    discount_value: Amount | None = None


class ChargeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, Field(max_length=60)]
    amount: Amount


class CashBuyerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Text | None = None
    state_code: Annotated[str, Field(max_length=2)]
    address: Text | None = None


class EwayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transporter: Annotated[str, Field(max_length=100)] | None = None
    vehicle_no: Annotated[str, Field(max_length=20)] | None = None
    eway_bill_no: Annotated[str, Field(max_length=20)] | None = None


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["invoice", "credit_note"] = "invoice"
    customer_id: str | None = None  # null with no cash_buyer = not chosen yet
    cash_buyer: CashBuyerIn | None = None
    doc_date: date | None = None
    invoice_discount: Amount = "0"
    charges: Annotated[list[ChargeIn], Field(max_length=drafts.MAX_CHARGES)] = []
    eway: EwayIn | None = None
    customer_collects: StrictBool = False  # ex-works, the customer collects the goods (case D)
    lines: Annotated[list[LineIn], Field(max_length=drafts.MAX_LINES)] = []


class LineOut(BaseModel):
    id: str
    line_no: int
    product_id: str
    quantity: str
    unit_price: str
    discount_kind: str | None
    discount_value: str | None


class DraftOut(BaseModel):
    id: str
    kind: str
    version: int
    customer_id: str | None
    cash_buyer: dict | None
    bill_to: dict | None
    ship_to: dict | None
    doc_date: date | None
    invoice_discount: str
    charges: list[dict]
    eway: dict | None
    customer_collects: bool
    lines: list[LineOut]
    created_at: str
    updated_at: str


class DraftPageOut(BaseModel):
    items: list[DraftOut]  # without lines
    has_more: bool


def _s(v) -> str | None:
    return None if v is None else str(v)


def _out(d: dict) -> dict:
    return {
        "id": str(d["id"]), "kind": d["kind"], "version": d["version"], "customer_id": _s(d["customer_id"]),
        "cash_buyer": d["cash_buyer"], "bill_to": d["bill_to"], "ship_to": d["ship_to"], "doc_date": d["doc_date"],
        "invoice_discount": str(d["invoice_discount"]), "charges": d["charges"], "eway": d["eway"],
        "customer_collects": d["customer_collects"],
        "lines": [{**ln, "id": str(ln["id"]), "product_id": str(ln["product_id"]), "quantity": str(ln["quantity"]),
                   "unit_price": str(ln["unit_price"]), "discount_value": _s(ln["discount_value"])} for ln in d["lines"]],
        "created_at": d["created_at"].isoformat(), "updated_at": d["updated_at"].isoformat(),
    }


def _etag(response: Response, d: dict) -> dict:
    """The version is the entity tag (platform_common.etag): send it back as If-Match on
    PUT and DELETE."""
    set_etag(response, d["version"])
    return d


@router.get("/b/{business_id}/drafts", response_model=DraftPageOut, dependencies=VIEW)
def list_drafts(
    uow: BusinessUoW,
    page: Annotated[PageParams, Depends(page_params)],
    kind: Literal["invoice", "credit_note"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    items, more = drafts.search(uow, kind=kind, q=q, limit=page.limit, offset=page.offset)
    return {"items": [_out(d) for d in items], "has_more": more}


@router.post("/b/{business_id}/drafts", status_code=http.HTTP_201_CREATED, response_model=DraftOut, dependencies=EDIT)
def create_draft(
    body: DraftIn,
    request: Request,
    response: Response,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    def create():
        return _out(drafts.get(uow, drafts.create(uow, body.model_dump(mode="json"), clock.today())))

    return _etag(response, run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                                    route=request.scope["route"].path, payload=body.model_dump(mode="json"),
                                    operation=create))


@router.get("/b/{business_id}/drafts/{draft_id}", response_model=DraftOut, dependencies=VIEW)
def get_draft(draft_id: str, uow: BusinessUoW, response: Response):
    return _etag(response, _out(drafts.get(uow, parse_id(draft_id))))


@router.put("/b/{business_id}/drafts/{draft_id}", response_model=DraftOut, dependencies=EDIT)
def save_draft(
    draft_id: str,
    body: DraftIn,
    response: Response,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    did = parse_id(draft_id)
    drafts.replace(uow, did, body.model_dump(mode="json"), if_match_version(if_match), clock.today())
    return _etag(response, _out(drafts.get(uow, did)))


@router.delete("/b/{business_id}/drafts/{draft_id}", status_code=http.HTTP_204_NO_CONTENT, dependencies=EDIT)
def delete_draft(draft_id: str, uow: BusinessUoW, if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    drafts.delete(uow, parse_id(draft_id), if_match_version(if_match))
    return Response(status_code=http.HTTP_204_NO_CONTENT)


class PreviewRef(BaseModel):
    job_id: str
    draft_version: int


class PreviewOut(BaseModel):
    status: Literal["queued", "rendering", "ready", "failed"]
    url: str | None = None  # when ready: a link good for 60 seconds
    error_code: str | None = None  # when failed: render_failed, draft_changed, draft_not_found, not_allowed, ...


@router.post("/b/{business_id}/drafts/{draft_id}/preview", status_code=http.HTTP_202_ACCEPTED,
             response_model=PreviewRef, dependencies=VIEW)
def preview_draft(draft_id: str, uow: BusinessUoW):
    """Queues a PDF preview of the draft as saved now ("Draft, not a tax invoice"). The
    same version always gives the same job; poll GET .../preview/{job_id}."""
    job_id, version = preview.queue(uow, parse_id(draft_id))
    return {"job_id": str(job_id), "draft_version": version}


@router.get("/b/{business_id}/drafts/{draft_id}/preview/{job_id}", response_model=PreviewOut, dependencies=VIEW)
def preview_status(draft_id: str, job_id: str, uow: BusinessUoW):
    return preview.status(uow, parse_id(draft_id), parse_id(job_id))
