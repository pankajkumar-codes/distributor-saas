"""Product routes (LLD-3 §6.1) under /api/v1/b/{business_id}, on business_uow.

Money and rates travel as decimal strings, dates as YYYY-MM-DD. POSTs that create
something take an Idempotency-Key (run_once); PATCH and DELETE take If-Match with the
version the user saw (L3-9). The CSV import routes come with S3-c.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field

from app.modules.refdata import uqc_codes
from platform_common.clock import Clock, get_clock
from platform_common.errors import Invalid
from platform_common.etag import if_match_version, set_etag
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import checks, products
from .interface import rate_from_mrp
from .rates import valid_until

router = APIRouter(tags=["catalog"])
VIEW = [Depends(require(Permission.CATALOG_VIEW))]
EDIT = [Depends(require(Permission.CATALOG_EDIT))]

Text = Annotated[str, Field(max_length=300)]
# A name (customer or product): the limit is checks.name's 200, which answers in plain words, so the published schema
# says 200 (#470; the law sets no length, and the database column is varchar(200)). The framework guard stays at 1000
# only to stop absurd input, so a name of 201 to 1000 characters gets the plain message instead of a framework one.
Name = Annotated[str, Field(max_length=1000, json_schema_extra={"maxLength": checks.NAME_MAX})]
Decimalish = Annotated[str, Field(max_length=24, pattern=r"^\s*[0-9]+(\.[0-9]+)?\s*$")]
# A string only (a JSON number is refused); checks.sale_rate gives the field its own error.
Money = Annotated[str, Field(max_length=24)]


class RateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rate: Decimalish
    valid_from: date


class ProductIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Text
    name: Name
    hsn: Text | None = None
    uqc: Text
    sale_rate: Money
    mrp: Money | None = None  # required (D-107): per unit, GST included; refused when missing or blank
    barcode: Text | None = None
    tax_category: Literal["taxable", "exempt", "nil_rated", "non_gst"]
    has_cess: bool = False
    rate: RateIn | None = None


class ProductPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: Text | None = None
    name: Name | None = None
    hsn: Text | None = None
    uqc: Text | None = None
    sale_rate: Money | None = None
    mrp: Money | None = None  # required (D-107): may change, never be cleared
    barcode: Text | None = None
    tax_category: Literal["taxable", "exempt", "nil_rated", "non_gst"] | None = None
    has_cess: bool | None = None
    # Only with tax_category "taxable" on a product that wasn't, and isn't on an invoice yet.
    rate: RateIn | None = None


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Annotated[str, Field(max_length=600)] | None = None


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: Annotated[str, Field(max_length=600)] | None = None


class Warning(BaseModel):
    code: str
    field: str | None
    message: str


class RateOnOut(BaseModel):
    rate: str
    rate_id: str
    valid_from: date
    confirmed: bool


class ProductOut(BaseModel):
    id: str
    code: str
    name: str
    hsn: str | None
    uqc: str
    sale_rate: str
    mrp: str | None  # per 1 qty, GST included, 2 decimals; None only on a product saved before D-107
    rate_from_mrp: str | None  # MRP / (1 + GST%/100) on the day asked, the invoice line's default rate (D-107)
    barcode: str | None
    tax_category: str
    has_cess: bool
    status: str
    version: int
    price_needed: bool  # R2-M3: set the selling price per 1 qty to clear it
    in_use: bool
    rate_on: RateOnOut | None
    warnings: list[Warning]


class Confirmation(BaseModel):
    state: Literal["confirmed", "unconfirmed"]
    by: str
    at: str
    note: str | None


class RateOut(BaseModel):
    id: str
    rate: str
    valid_from: date
    valid_until: date | None  # the next live rate's valid_from (exclusive); computed (L3-1)
    voided: bool
    confirmation: Confirmation | None


class ProductDetailOut(ProductOut):
    rate_changed_within_warning_window: bool
    rates: list[RateOut]


class ProductPageOut(BaseModel):
    items: list[ProductOut]
    has_more: bool


class UnitOut(BaseModel):
    code: str
    name: str


def _str_or_none(value) -> str | None:
    return None if value is None else f"{value:.2f}"


def _mrp_required(value) -> None:
    """D-107: a product typed in by a person always has its MRP. Imports and purchase items may still arrive
    without one; the invoice then blocks the line (mrp_missing) until it is added."""
    if value is None or not str(value).strip():
        raise Invalid("mrp_required", "Enter the MRP, the price per unit with GST included", field="mrp",
                      fix="Enter the MRP, the price per unit with GST included")


def _rate_str(value) -> str:
    return f"{value.normalize():f}"


def _out(p: products.Product, rate: dict | None) -> dict:
    confirmed = rate["confirmed"] if rate else None
    return {
        "id": str(p.id),
        "code": p.code,
        "name": p.name,
        "hsn": p.hsn,
        "uqc": p.uqc,
        "sale_rate": f"{p.sale_rate:.2f}",
        "mrp": None if p.mrp is None else f"{p.mrp:.2f}",
        "rate_from_mrp": _str_or_none(rate_from_mrp(p.mrp, p.tax_category, rate["rate"] if rate else None, p.has_cess)),
        "barcode": p.barcode,
        "tax_category": p.tax_category,
        "has_cess": p.has_cess,
        "status": p.status,
        "version": p.version,
        "price_needed": p.price_needed,
        "in_use": p.in_use,
        "rate_on": None if rate is None else {
            "rate": _rate_str(rate["rate"]), "rate_id": str(rate["rate_id"]), "valid_from": rate["valid_from"],
            "confirmed": confirmed,
        },
        "warnings": products.warnings(p, confirmed),
    }


def _detail(uow, product_id, on: date) -> dict:
    p, rows, confirmations = products.get(uow, product_id)
    found = products.current(uow, product_id, on) if p.tax_category == "taxable" else None
    rate = None if found is None else {
        "rate": found.row.rate, "rate_id": found.row.id, "valid_from": found.row.valid_from,
        "confirmed": found.row.confirmed,
    }
    ends = valid_until(rows)
    out = _out(p, rate)
    out["rate_changed_within_warning_window"] = bool(found and found.changed_within_warning_window)
    out["rates"] = [
        {
            "id": str(r.id),
            "rate": _rate_str(r.rate),
            "valid_from": r.valid_from,
            "valid_until": ends.get(r.id),
            "voided": r.voided,
            "confirmation": None if r.id not in confirmations else {
                **confirmations[r.id], "by": str(confirmations[r.id]["by"]),
                "at": confirmations[r.id]["at"].isoformat(),
            },
        }
        for r in rows
    ]
    return out


def _once(request: Request, uow, key: str | None, payload: dict, operation):
    return run_once(uow.tx, uow.principal.business_id, key, method=request.method,
                    route=request.scope["route"].path, payload=payload, operation=operation)


@router.get("/b/{business_id}/units", response_model=list[UnitOut], dependencies=VIEW)
def list_units(uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    """The UQC picker (refdata.uqc_codes)."""
    return [{"code": c, "name": n} for c, n in uqc_codes(uow.tx, clock.today()).items()]


@router.get("/b/{business_id}/products", response_model=ProductPageOut, dependencies=VIEW)
def list_products(
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "archived", "all"] = "active",
    filter: Literal["no_hsn", "rate_unconfirmed"] | None = None,  # noqa: A002 (the API's name)
    on: date | None = None,
):
    items, more = products.search(uow, q=q, status=status, filter_=filter, on=on or clock.today(),
                                  limit=page.limit, offset=page.offset)
    return {"items": [_out(p, rate) for p, rate in items], "has_more": more}


@router.post("/b/{business_id}/products", status_code=http.HTTP_201_CREATED, response_model=ProductDetailOut, dependencies=EDIT)
def create_product(
    body: ProductIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    today = clock.today()

    def create():
        _mrp_required(body.mrp)
        return _detail(uow, products.create(uow, body.model_dump(), today), today)

    return _once(request, uow, idempotency_key, body.model_dump(mode="json"), create)


@router.get("/b/{business_id}/products/{product_id}", response_model=ProductDetailOut, dependencies=VIEW)
def get_product(product_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)], response: Response,
                on: date | None = None):
    out = _detail(uow, parse_id(product_id), on or clock.today())
    set_etag(response, out["version"])
    return out


@router.patch("/b/{business_id}/products/{product_id}", response_model=ProductDetailOut, dependencies=EDIT)
def update_product(
    product_id: str,
    body: ProductPatch,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    response: Response,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    pid = parse_id(product_id)
    today = clock.today()
    changes = body.model_dump(exclude_unset=True)
    if "mrp" in changes:
        _mrp_required(changes["mrp"])
    products.update(uow, pid, changes, if_match_version(if_match), today)
    out = _detail(uow, pid, today)
    set_etag(response, out["version"])
    return out


@router.post("/b/{business_id}/products/{product_id}/archive", response_model=ProductDetailOut, dependencies=EDIT)
def archive_product(product_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    pid = parse_id(product_id)
    products.set_archived(uow, pid, True)
    return _detail(uow, pid, clock.today())


@router.post("/b/{business_id}/products/{product_id}/unarchive", response_model=ProductDetailOut,
             dependencies=EDIT)
def unarchive_product(product_id: str, uow: BusinessUoW, clock: Annotated[Clock, Depends(get_clock)]):
    pid = parse_id(product_id)
    products.set_archived(uow, pid, False)
    return _detail(uow, pid, clock.today())


@router.delete("/b/{business_id}/products/{product_id}", status_code=http.HTTP_204_NO_CONTENT, dependencies=EDIT)
def delete_product(product_id: str, uow: BusinessUoW,
                   if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    products.delete(uow, parse_id(product_id), if_match_version(if_match))
    return Response(status_code=http.HTTP_204_NO_CONTENT)


@router.post("/b/{business_id}/products/{product_id}/rates", status_code=http.HTTP_201_CREATED, response_model=ProductDetailOut,
             dependencies=EDIT)
def add_rate(
    product_id: str,
    body: RateIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    pid = parse_id(product_id)
    today = clock.today()

    def add():
        products.add_rate(uow, pid, body.rate, body.valid_from, today)
        return _detail(uow, pid, today)

    return _once(request, uow, idempotency_key, body.model_dump(mode="json"), add)


@router.post("/b/{business_id}/products/{product_id}/rates/{rate_id}/void", status_code=http.HTTP_201_CREATED,
             response_model=ProductDetailOut, dependencies=EDIT)
def void_rate(product_id: str, rate_id: str, body: ReasonIn, uow: BusinessUoW,
              clock: Annotated[Clock, Depends(get_clock)]):
    pid = parse_id(product_id)
    products.void_rate(uow, pid, parse_id(rate_id), body.reason)
    return _detail(uow, pid, clock.today())


@router.post("/b/{business_id}/products/{product_id}/rates/{rate_id}/confirm", status_code=http.HTTP_201_CREATED,
             response_model=ProductDetailOut, dependencies=EDIT)
def confirm_rate(product_id: str, rate_id: str, body: NoteIn, uow: BusinessUoW,
                 clock: Annotated[Clock, Depends(get_clock)]):
    pid = parse_id(product_id)
    products.set_confirmed(uow, pid, parse_id(rate_id), True, body.note)
    return _detail(uow, pid, clock.today())


@router.post("/b/{business_id}/products/{product_id}/rates/{rate_id}/unconfirm", status_code=http.HTTP_201_CREATED,
             response_model=ProductDetailOut, dependencies=EDIT)
def unconfirm_rate(product_id: str, rate_id: str, body: ReasonIn, uow: BusinessUoW,
                   clock: Annotated[Clock, Depends(get_clock)]):
    pid = parse_id(product_id)
    products.set_confirmed(uow, pid, parse_id(rate_id), False, body.reason)
    return _detail(uow, pid, clock.today())
