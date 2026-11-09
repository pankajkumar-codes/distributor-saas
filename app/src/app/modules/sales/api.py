"""Invoice draft routes (LLD-4 §9) under /api/v1/b/{business_id}.

POST takes an Idempotency-Key (run_once); PUT saves the whole draft and DELETE removes an
open one, both under If-Match with the version the user saw. Money and quantities are
strings: a JSON number is a 422 (AC4-15). Drafts are unfinished work: listing, reading and
changing them all need the create-documents permission (LLD-4 §9), so a CA sees invoices only
once they are finalized.
"""

import base64
import uuid
from datetime import date, datetime
from decimal import Context, Decimal, InvalidOperation, Inexact
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from platform_common.clock import Clock, get_clock
from platform_common.etag import if_match_version, set_etag
from platform_common.idempotency import run_once
from platform_common.errors import Invalid
from platform_common.paging import DEFAULT_LIMIT, MAX_LIMIT
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import drafts, preview
from .compute import Computation

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


class ShipToIn(BaseModel):
    """Where the goods go, when it isn't the customer's own delivery address (LLD-4 §3.1)."""

    model_config = ConfigDict(extra="forbid")

    name: Text | None = None  # the consignee, when goods go to someone else (case B)
    line1: Text | None = None
    line2: Text | None = None
    city: Text | None = None
    pin: Text | None = None  # checked against refdata address.pin_pattern
    state_code: Annotated[str, Field(max_length=2)]


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
    ship_to: ShipToIn | None = None  # null: the customer's delivery address (or none for a cash sale)
    ship_to_third_party: StrictBool = False  # case B: goods go to another person on the customer's direction
    pos_override: Annotated[str, Field(max_length=2)] | None = None  # G16: a state code replacing the computed PoS
    pos_override_reason: Annotated[str, Field(max_length=500)] | None = None
    lines: Annotated[list[LineIn], Field(max_length=drafts.MAX_LINES)] = []


class LineOut(BaseModel):
    id: str
    line_no: int
    product_id: str
    quantity: str
    unit_price: str
    discount_kind: str | None
    discount_value: str | None


class TaxOut(BaseModel):
    component: str
    rate: str
    amount: str


class ComputedLineOut(BaseModel):
    line_no: int
    gross: str
    line_discount: str
    base: str
    discount_share: str
    charge_share: str
    taxable: str
    rate: str | None
    taxes: list[TaxOut]
    total: str


class IssueOut(BaseModel):
    code: str
    fix: str
    field: str | None
    line_no: int | None


class ComputationOut(BaseModel):
    """What the draft would be as an invoice today (LLD-4 §3). `blocks` stop a finalize,
    `warnings` never do; neither stops a draft from being saved."""

    computed_pos: str | None
    pos_state_code: str | None
    is_inter_state: bool | None
    supply_class: str | None
    lines: list[ComputedLineOut]
    gross_total: str
    line_discount_total: str
    invoice_discount: str
    charges_total: str
    taxable_total: str
    cgst_total: str
    sgst_total: str  # carries UTGST when utgst
    utgst: bool
    igst_total: str
    round_off: str
    doc_total: str
    amount_in_words: str
    rounding_mode: str
    method_version: str
    blocks: list[IssueOut]
    warnings: list[IssueOut]


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
    ship_to_third_party: bool
    pos_override: str | None
    pos_override_reason: str | None
    lines: list[LineOut]
    computation: ComputationOut | None = None  # on create and save; not on read or list
    # As of the last save, for the list (never authoritative: finalize recomputes). Null for a
    # draft saved before these were kept.
    total: str | None
    ready: bool | None  # no blocks at the last save
    computed_at: str | None
    created_at: str
    updated_at: str


class DraftPageOut(BaseModel):
    items: list[DraftOut]  # without lines
    has_more: bool
    next_cursor: str | None  # pass as `cursor` for the next page; null on the last


def _s(v) -> str | None:
    return None if v is None else str(v)


_PAISE = Decimal("0.01")
_EXACT = Context(traps=[Inexact, InvalidOperation])  # 28 digits cover any amount here


def _m(x: Decimal) -> str:
    """An amount as a 2-place decimal string. compute's amounts are already whole paise, so
    this only fixes the scale; one that is not raises Inexact rather than rounding silently."""
    return str(x.quantize(_PAISE, context=_EXACT))


def _issues(items) -> list[dict]:
    return [{"code": i.code, "fix": i.fix, "field": i.field, "line_no": i.line_no} for i in items]


def _computed(c: Computation) -> dict:
    return {
        "computed_pos": c.computed_pos, "pos_state_code": c.pos_state_code, "is_inter_state": c.is_inter_state,
        "supply_class": c.supply_class, "utgst": c.utgst,
        "lines": [{
            "line_no": ln.line_no, "gross": _m(ln.gross), "line_discount": _m(ln.line_discount),
            "base": _m(ln.base), "discount_share": _m(ln.discount_share), "charge_share": _m(ln.charge_share),
            "taxable": _m(ln.taxable), "rate": None if ln.rate is None else str(ln.rate), "total": _m(ln.total),
            "taxes": [{"component": t.component, "rate": str(t.rate), "amount": _m(t.amount)} for t in ln.taxes],
        } for ln in c.lines],
        "gross_total": _m(c.gross_total), "line_discount_total": _m(c.line_discount_total),
        "invoice_discount": _m(c.invoice_discount), "charges_total": _m(c.charges_total),
        "taxable_total": _m(c.taxable_total), "cgst_total": _m(c.cgst_total), "sgst_total": _m(c.sgst_total),
        "igst_total": _m(c.igst_total), "round_off": _m(c.round_off), "doc_total": _m(c.doc_total),
        "amount_in_words": c.amount_in_words, "rounding_mode": c.rounding_mode, "method_version": c.method_version,
        "blocks": _issues(c.blocks), "warnings": _issues(c.warnings),
    }


def _out(d: dict, computation: Computation | None = None) -> dict:
    return {
        "computation": None if computation is None else _computed(computation),
        "id": str(d["id"]), "kind": d["kind"], "version": d["version"], "customer_id": _s(d["customer_id"]),
        "cash_buyer": d["cash_buyer"], "bill_to": d["bill_to"], "ship_to": d["ship_to"], "doc_date": d["doc_date"],
        "invoice_discount": str(d["invoice_discount"]), "charges": d["charges"], "eway": d["eway"],
        "customer_collects": d["customer_collects"], "ship_to_third_party": d["ship_to_third_party"],
        "pos_override": d["pos_override"], "pos_override_reason": d["pos_override_reason"],
        "lines": [{**ln, "id": str(ln["id"]), "product_id": str(ln["product_id"]), "quantity": str(ln["quantity"]),
                   "unit_price": str(ln["unit_price"]), "discount_value": _s(ln["discount_value"])} for ln in d["lines"]],
        "total": None if d["total"] is None else _m(d["total"]),
        "ready": None if d["block_count"] is None else d["block_count"] == 0,
        "computed_at": None if d["computed_at"] is None else d["computed_at"].isoformat(),
        "created_at": d["created_at"].isoformat(), "updated_at": d["updated_at"].isoformat(),
    }


def _encode_cursor(at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{at.isoformat()}|{row_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        at, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        parsed = datetime.fromisoformat(at)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, uuid.UUID(row_id)
    except (ValueError, UnicodeDecodeError):
        raise Invalid("cursor_invalid", "This page link is not valid; start from the first page",
                      field="cursor") from None


def _computed_and_stored(uow, d: dict, today: date) -> tuple[dict, Computation]:
    """The draft's computation, also kept on the draft for the list; `d` re-read with it."""
    c = drafts.computation(uow, d, today=today)
    drafts.store_computation(uow, d["id"], c)
    return drafts.get(uow, d["id"]), c


def _etag(response: Response, d: dict) -> dict:
    """The version is the entity tag (platform_common.etag): send it back as If-Match on
    PUT and DELETE."""
    set_etag(response, d["version"])
    return d


@router.get("/b/{business_id}/drafts", response_model=DraftPageOut, dependencies=EDIT)
def list_drafts(
    uow: BusinessUoW,
    kind: Literal["invoice", "credit_note"] | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    ready: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
):
    """Open drafts, most recently saved first, with each one's total and readiness as of
    its last save. A cursor, not an offset: saving a draft moves it to the top, and an offset
    would then show a row twice or skip one."""
    after = None if cursor is None else _decode_cursor(cursor)
    items, more = drafts.search(uow, kind=kind, q=q, ready=ready, limit=limit, after=after)
    last = items[-1] if items else None
    return {"items": [_out(d) for d in items], "has_more": more,
            "next_cursor": _encode_cursor(last["updated_at"], last["id"]) if more and last else None}


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
        d = drafts.get(uow, drafts.create(uow, body.model_dump(mode="json"), clock.today()))
        return _out(*_computed_and_stored(uow, d, clock.today()))

    return _etag(response, run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                                    route=request.scope["route"].path, payload=body.model_dump(mode="json"),
                                    operation=create))


@router.get("/b/{business_id}/drafts/{draft_id}", response_model=DraftOut, dependencies=EDIT)
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
    return _etag(response, _out(*_computed_and_stored(uow, drafts.get(uow, did), clock.today())))


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
