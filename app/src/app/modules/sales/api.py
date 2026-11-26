"""Invoice draft routes (LLD-4 §9) under /api/v1/b/{business_id}.

POST takes an Idempotency-Key (run_once); PUT saves the whole draft and DELETE removes an
open one, both under If-Match with the version the user saw. Money and quantities are
strings: a JSON number is a 422 (AC4-15). Drafts are unfinished work: listing, reading,
previewing and changing them all need the create-documents permission (LLD-4 §9), so a CA
sees invoices only once they are finalized.
"""

import base64
import uuid
from datetime import date, datetime
from decimal import Context, Decimal, InvalidOperation, Inexact
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.modules.catalog.interface import movements_for_document
from app.modules.filing import interface as filing
from platform_common.clock import Clock, get_clock
from platform_common.etag import if_match_version, set_etag
from platform_common.idempotency import run_once
from platform_common.errors import Deny, Invalid
from platform_common.paging import DEFAULT_LIMIT, MAX_LIMIT, PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import cancel, document_pdf, drafts, finalize, notes, preview
from .compute import Computation

router = APIRouter(tags=["sales"])


# The permission check runs first, so a role without it still gets the plain 404.
EDIT = [Depends(require(Permission.DOCUMENTS_CREATE))]
VIEW = [Depends(require(Permission.DOCUMENTS_VIEW))]

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


@router.post("/b/{business_id}/drafts/estimate", response_model=ComputationOut, dependencies=EDIT)
def estimate_draft(body: DraftIn, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The tax computation for a draft as typed, without saving it (#411): the same checks and computation as a
    save, nothing stored. New invoice calls it as the seller types so the totals and the paper move with them.
    Not a record: Save draft keeps the draft, and finalize computes again."""
    return _computed(drafts.estimate(uow, body.model_dump(mode="json"), clock.today()))


@router.get("/b/{business_id}/drafts/{draft_id}", response_model=DraftOut, dependencies=EDIT)
def get_draft(draft_id: str, uow: BusinessUoW, response: Response, clock: Annotated[Clock, Depends(get_clock)]):
    """Reading a draft checks it again as of today, so a fixed product, or a business setting changed
    meanwhile, shows at once. Not a user edit: the version is unchanged. A draft that cannot be
    computed (its customer was deleted) is returned as stored, so the page can open it and the buyer be changed."""
    d = drafts.get(uow, parse_id(draft_id), lock=True)  # one version for the read, the check and the store
    try:
        return _etag(response, _out(*_computed_and_stored(uow, d, clock.today())))
    except Invalid:
        return _etag(response, _out(d))


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
             response_model=PreviewRef, dependencies=EDIT)
def preview_draft(draft_id: str, uow: BusinessUoW):
    """Queues a PDF preview of the draft as saved now ("Draft, not a tax invoice"). The
    same version always gives the same job; poll GET .../preview/{job_id}."""
    job_id, version = preview.queue(uow, parse_id(draft_id))
    return {"job_id": str(job_id), "draft_version": version}


@router.get("/b/{business_id}/drafts/{draft_id}/preview/{job_id}", response_model=PreviewOut, dependencies=EDIT)
def preview_status(draft_id: str, job_id: str, uow: BusinessUoW):
    return preview.status(uow, parse_id(draft_id), parse_id(job_id))


class DocumentOut(BaseModel):
    """The finalized document (LLD-4 §2.3), as stored: it never changes after this."""

    id: str
    draft_id: str
    kind: str
    is_practice: bool  # a practice document: never in a return, never in a live series (BH-5)
    doc_number: str
    doc_date: date
    original_document_id: str | None  # a credit or debit note's invoice
    # A note's reason: goods_returned, value_too_high or deficient (credit); value_too_low or more_goods (debit)
    reason_code: str | None
    fy: str
    gstin: str
    supply_class: str
    pos_state_code: str
    is_inter_state: bool
    customer_id: str | None
    counterparty_name: str | None
    due_date: date | None
    taxable_total: str
    cgst_total: str
    sgst_total: str  # carries UTGST when utgst
    utgst: bool
    igst_total: str
    round_off: str
    doc_total: str
    finalized_at: str
    # #456: set when the invoice is cancelled (raised_in_error, duplicate or did_not_happen); the row never changes
    cancel_reason: str | None = None


def _document(doc: dict) -> dict:
    money_cols = ("taxable_total", "cgst_total", "sgst_total", "igst_total", "round_off", "doc_total")
    return {**doc, **{k: _m(doc[k]) for k in money_cols}, "id": str(doc["id"]), "draft_id": str(doc["draft_id"]),
            "customer_id": _s(doc["customer_id"]), "original_document_id": _s(doc["original_document_id"]),
            "finalized_at": doc["finalized_at"].isoformat()}


@router.post("/b/{business_id}/drafts/{draft_id}/finalize", response_model=DocumentOut, dependencies=EDIT)
def finalize_draft(
    draft_id: str,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    """Issues the draft as a document with the next number (LLD-4 §4). Off until refdata
    `sales.finalize.enabled` is true: while it is off this route is a 404 like an unknown
    draft, and no number is taken. The same draft finalized twice gives one document."""
    if not finalize.enabled(uow, clock.today()):
        raise Deny("not_found")
    did = parse_id(draft_id)
    version = if_match_version(if_match)
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"draft_id": str(did), "if_match": version},
                    operation=lambda: _document(finalize.finalize(uow, did, version, clock.today())))


class DocumentPdfRef(BaseModel):
    job_id: str
    attempt: int  # 1, or higher after an earlier attempt failed


@router.post("/b/{business_id}/documents/{document_id}/pdf", status_code=http.HTTP_202_ACCEPTED,
             response_model=DocumentPdfRef, dependencies=VIEW)
def document_pdf_request(document_id: str, uow: BusinessUoW):
    """Queues the PDF of a finalized document, made from what was stored at finalize. While live
    numbering is off every document is a practice one and the PDF says it is not a tax invoice.
    Asking again gives the same job unless the last attempt failed; poll GET .../pdf/{job_id}."""
    job_id, attempt = document_pdf.queue(uow, parse_id(document_id))
    return {"job_id": str(job_id), "attempt": attempt}


@router.get("/b/{business_id}/documents/{document_id}/pdf/{job_id}", response_model=PreviewOut, dependencies=VIEW)
def document_pdf_status(document_id: str, job_id: str, uow: BusinessUoW):
    return document_pdf.status(uow, parse_id(document_id), parse_id(job_id))


class InvoicingPlanOut(BaseModel):
    name: str
    monthly_rupees: int
    quarterly_rupees: int
    gst_note: str
    free_for_now: bool  # true while payments are a placeholder: nothing is charged
    free_invoices: int
    used: int  # finalized invoices, practice ones included (D-086), counted on the server
    remaining_free: int
    needs_plan: bool  # the next invoice would be refused (402 invoice_plan_required)


@router.get("/b/{business_id}/invoicing-plan", response_model=InvoicingPlanOut, dependencies=VIEW)
def get_invoicing_plan(uow: BusinessUoW):
    """The invoicing plan, its prices, how many free invoices are used, and whether the next one needs the plan. Read-only."""
    used = finalize.invoices_used(uow)
    free = filing.FREE_INVOICES
    return {
        "name": "Invoicing and GST", "monthly_rupees": filing.INVOICING["monthly"],
        "quarterly_rupees": filing.INVOICING["quarterly"], "gst_note": filing.GST_NOTE,
        "free_for_now": filing.free_for_now(), "free_invoices": free, "used": used,
        "remaining_free": max(free - used, 0),
        "needs_plan": used >= free and not filing.invoicing_allowed(uow.tx, uow.principal.business_id),
    }


class PlanChangeOut(BaseModel):
    current_price: str
    unused_credit: str
    new_price: str
    amount_due: str  # rupees before GST on our fee; display only, nothing is charged
    credit_left_over: str
    gst_note: str
    free_for_now: bool


@router.get("/b/{business_id}/plan-change-preview", response_model=PlanChangeOut, dependencies=VIEW)
def plan_change_preview(
    uow: BusinessUoW,  # noqa: ARG001 (the tenant is checked by the route's dependencies; the figures are the price list)
    from_plan: Literal["gst_filing", "invoicing"],
    from_frequency: Literal["monthly", "quarterly"],
    to_plan: Literal["gst_filing", "invoicing"],
    to_frequency: Literal["monthly", "quarterly"],
    days_left: int,
    period_days: int,
):
    """What a plan change would show: the unused part of the current period credited, the new plan's full price from now.
    Display only (D-086); the figures are the price list, never a charge."""
    try:
        out = filing.prorated_change(from_plan, from_frequency, to_plan, to_frequency,
                                     days_left=days_left, period_days=period_days)
    except ValueError as e:
        raise Invalid("plan_change_invalid", "Check the days left in the current period.", field="days_left") from e
    return {**out, "gst_note": filing.GST_NOTE, "free_for_now": filing.free_for_now()}


class DocumentPdfState(BaseModel):
    status: Literal["none", "queued", "rendering", "ready", "failed"]  # none: no PDF has been asked for yet
    job_id: str | None = None
    attempt: int | None = None
    url: str | None = None  # when ready: a link good for 60 seconds
    error_code: str | None = None


class DocumentParty(BaseModel):
    name: str | None
    gstin: str | None
    address: list[str]  # lines, in order; may be empty
    state: str | None  # "West Bengal (19)"


class DocumentShipTo(BaseModel):
    address: list[str]
    state: str | None


class DocumentLineTax(BaseModel):
    component: Literal["CGST", "SGST", "UTGST", "IGST"]
    rate: str
    amount: str


class DocumentLineOut(BaseModel):
    """One stored line, as finalized: the page shows it and works out nothing."""

    no: str
    description: str
    hsn: str
    quantity: str  # a dash on a note made by amount, which moves no goods
    uqc: str | None  # None on a note made by amount (#485)
    unit_price: str | None
    gross: str
    discount: str | None
    taxable: str
    taxes: list[DocumentLineTax]
    total: str  # the line's taxable value plus its own stored tax amounts


class DocumentOriginalOut(BaseModel):
    number: str
    date: str


class DocumentDetailOut(DocumentOut):
    # A credit note (#456): the invoice it adjusts, the s.34 reason as printed, and what happened to returned goods.
    original: DocumentOriginalOut | None = None
    reason: str | None = None
    stock_treatment: Literal["restock", "write_off"] | None = None
    buyer: DocumentParty | None  # the bill-to as at finalize; null if none was recorded
    ship_to: DocumentShipTo | None
    place_of_supply: str | None
    # Why that place of supply (read back from the stored document): delivery (registered buyer, where the goods
    # go), third_party (registered buyer, goods sent to another person on its direction), customer_collects
    # (registered buyer collects), buyer_address (no GSTIN: delivery or billing address), override (with its reason).
    pos_basis: Literal["delivery", "third_party", "customer_collects", "buyer_address", "override"]
    pos_override_reason: str | None
    lines: list[DocumentLineOut]
    gross_total: str
    line_discount_total: str
    invoice_discount: str
    charges_total: str
    charges_label: str | None
    cess_total: str
    amount_in_words: str
    pdf: DocumentPdfState
    stock_movements: int  # the stock rows this document wrote (an invoice: one out per line; a credit note: returns, write-offs)


class DocumentsOut(BaseModel):
    documents: list[DocumentOut]
    has_more: bool


@router.get("/b/{business_id}/documents", response_model=DocumentsOut, dependencies=VIEW)
def list_documents(
    uow: BusinessUoW,
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    """The business's finalized documents, newest first (practice ones included, each says `is_practice`). Read-only.
    `q` narrows them to a number or buyer name containing it, or a buyer GSTIN starting with it."""
    found, more = finalize.list_documents(uow, page.limit, page.offset, q)
    return {"documents": [_document(d) for d in found], "has_more": more}


@router.get("/b/{business_id}/documents/{document_id}", response_model=DocumentDetailOut, dependencies=VIEW)
def get_document(document_id: str, uow: BusinessUoW):
    """One finalized document as stored (header, buyer, lines with their tax split), where its PDF stands and how many stock movements it wrote. Read-only: nothing
    is queued; ask for the PDF with POST .../pdf."""
    did = parse_id(document_id)
    doc = finalize.get_document(uow, did)
    return {**_document(doc), **document_pdf.view(uow.tx, uow.principal.business_id, did),
            "pdf": document_pdf.current(uow, did), "stock_movements": movements_for_document(uow.tx, did)}


# --- Credit notes (#456) ---------------------------------------------------------------------------------------------


class CreditLineOut(BaseModel):
    original_line_id: str
    line_no: int
    name: str
    hsn: str
    uqc: str
    rate: str
    quantity: str | None  # on the invoice
    remaining_quantity: str | None  # left to credit by quantity
    taxable: str  # on the invoice
    remaining_taxable: str  # left to credit
    remaining_tax: str  # left to credit, all components


class CreditNoteRef(BaseModel):
    id: str
    kind: Literal["credit_note", "debit_note"] = "credit_note"
    doc_number: str
    doc_date: date
    reason_code: str | None
    doc_total: str
    is_practice: bool


class CreditStateOut(BaseModel):
    invoice_id: str
    doc_number: str
    is_practice: bool
    cancelled: bool = False  # a cancelled invoice takes no credit note
    lines: list[CreditLineOut]
    notes: list[CreditNoteRef]
    remaining_total: str
    last_date: date  # s.34(2): 30 November after the invoice's FY; the annual-return limb is not checked
    reasons: dict[str, str]  # code -> label, the s.34(1) grounds only
    debit_reasons: dict[str, str] = {}  # code -> label, the s.34(3) grounds a debit note takes


class CreditLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_line_id: str
    quantity: str | None = None  # goods returned
    taxable: str | None = None  # value too high, deficient


class CreditNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["goods_returned", "value_too_high", "deficient"]
    stock_treatment: Literal["restock", "write_off"] | None = None
    doc_date: date | None = None
    lines: list[CreditLineIn] = Field(max_length=drafts.MAX_LINES)


class DebitLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_line_id: str
    quantity: str | None = None  # more goods sent
    taxable: str | None = None  # value charged too low


class DebitNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["value_too_low", "more_goods"]
    doc_date: date | None = None
    lines: list[DebitLineIn] = Field(max_length=drafts.MAX_LINES)


def _credit_state(s: notes.CreditState) -> dict:
    def q(v):
        return None if v is None else f"{v.normalize():f}"

    return {
        "invoice_id": str(s.invoice["id"]), "doc_number": s.invoice["doc_number"],
        "is_practice": s.invoice["is_practice"], "cancelled": s.invoice.get("cancel_reason") is not None,
        "lines": [{"original_line_id": str(ln.line_id), "line_no": ln.line_no, "name": ln.name, "hsn": ln.hsn,
                   "uqc": ln.uqc, "rate": f"{ln.rate.normalize():f}", "quantity": q(ln.quantity),
                   "remaining_quantity": q(ln.remaining_quantity), "taxable": _m(ln.taxable),
                   "remaining_taxable": _m(ln.remaining_taxable),
                   "remaining_tax": _m(sum((ln.remaining_tax(c) for c in ln.taxes), Decimal()))} for ln in s.lines],
        "notes": [{**n, "id": str(n["id"]), "doc_total": _m(n["doc_total"])} for n in s.notes],
        "remaining_total": _m(s.remaining_total), "last_date": s.last_date, "reasons": notes.REASONS,
        "debit_reasons": notes.DEBIT_REASONS,
    }


@router.get("/b/{business_id}/documents/{document_id}/credit", response_model=CreditStateOut, dependencies=VIEW)
def get_credit_state(document_id: str, uow: BusinessUoW):
    """What is left to credit on an issued invoice, line by line, the credit notes made against it, and the last date
    the law allows for one (s.34(2)). Read-only. A credit note, or another business's document, is a 404."""
    return _credit_state(notes.credit_state(uow, parse_id(document_id)))


@router.post("/b/{business_id}/documents/{document_id}/credit-notes", status_code=http.HTTP_201_CREATED,
             response_model=DocumentOut, dependencies=EDIT)
def create_credit_note(
    document_id: str,
    body: CreditNoteIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Issues a credit note against an issued invoice (#456): by quantity for goods returned (back to stock, or
    returned and written off), by amount for a value charged too high or goods deficient. A practice invoice gets a
    practice note (PR-CN-), never in GST filing. The invoice itself never changes. Off, like finalize, until
    `sales.finalize.enabled` is true (a 404). The same key and body give the same note once."""
    if not finalize.enabled(uow, clock.today()):
        raise Deny("not_found")
    did = parse_id(document_id)
    payload = body.model_dump(mode="json")
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"document_id": str(did), **payload},
                    operation=lambda: _document(notes.create(uow, did, payload, clock.today())))


@router.post("/b/{business_id}/documents/{document_id}/debit-notes", status_code=http.HTTP_201_CREATED,
             response_model=DocumentOut, dependencies=EDIT)
def create_debit_note(
    document_id: str,
    body: DebitNoteIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Issues a debit note against an issued invoice (#456 part 3, s.34(3)): by amount for a taxable value charged too
    low, by quantity for more goods sent than invoiced (they leave stock). Tax is the line's rate on the added value.
    A practice invoice gets a practice note (PR-DN-), never in GST filing. The invoice itself never changes. Off, like
    finalize, until `sales.finalize.enabled` is true (a 404). The same key and body give the same note once."""
    if not finalize.enabled(uow, clock.today()):
        raise Deny("not_found")
    did = parse_id(document_id)
    payload = body.model_dump(mode="json")
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"document_id": str(did), **payload},
                    operation=lambda: _document(notes.create(uow, did, payload, clock.today(), kind="debit_note")))


# --- Cancelling an invoice (#456) --------------------------------------------------------------------------------------


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["raised_in_error", "duplicate", "did_not_happen"]
    declared_not_delivered: StrictBool = False  # "the goods on this invoice were not dispatched or delivered"
    duplicate_of: str | None = None  # required for a duplicate: the kept invoice's number, which must exist


@router.post("/b/{business_id}/documents/{document_id}/cancel", response_model=DocumentOut, dependencies=EDIT)
def cancel_document(
    document_id: str,
    body: CancelIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Cancels an issued invoice while the return holding it is open and no credit or debit note exists for it (#456). The
    invoice row never changes: a cancellation is written beside it, its number stays used, it leaves Tables 4 to 12
    and Table 13 counts it as cancelled, and its stock comes back. "Raised by mistake" and "did not happen" need the
    declaration that the goods were not removed or delivered. Off, like finalize, until `sales.finalize.enabled`."""
    if not finalize.enabled(uow, clock.today()):
        raise Deny("not_found")
    did = parse_id(document_id)
    payload = body.model_dump(mode="json")
    return run_once(uow.tx, uow.principal.business_id, idempotency_key, method=request.method,
                    route=request.scope["route"].path, payload={"document_id": str(did), **payload},
                    operation=lambda: _document(cancel.cancel(uow, did, payload, clock.today())))
