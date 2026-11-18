"""Stock routes (R2-M3) under /api/v1/b/{business_id}, on business_uow.

The stock list, a product's movements, a count correction (adjustment) and a reversal.
Quantities travel as decimal strings with 3 decimals; dates as YYYY-MM-DD. POSTs take an
Idempotency-Key. Every route first checks the business has chosen its type (R2 rule): 409
business_type_required otherwise. Setting the selling price per 1 qty is the existing
PATCH /products/{id} (sale_rate, If-Match). Nothing here ever blocks a sale: "no stock" is
information, not a refusal.
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi import status as http
from pydantic import BaseModel, ConfigDict, Field

from app.modules.business.interface import require_business_type
from platform_common.clock import Clock, get_clock
from platform_common.idempotency import run_once
from platform_common.paging import PageParams, page_params
from platform_common.permissions import Permission, require
from platform_common.uow import BusinessUoW, parse_id

from . import inventory

router = APIRouter(tags=["stock"])
VIEW = [Depends(require(Permission.CATALOG_VIEW))]
EDIT = [Depends(require(Permission.CATALOG_EDIT))]


class StockItemOut(BaseModel):
    product_id: str
    code: str
    name: str
    uqc: str
    status: str
    sale_rate: str  # per 1 qty, excluding GST
    price_needed: bool
    on_hand: str  # 3 decimals; may be negative
    no_stock: bool  # on hand is zero or less; a sale is still allowed


class StockPageOut(BaseModel):
    items: list[StockItemOut]
    has_more: bool


class MovementOut(BaseModel):
    id: str
    product_id: str
    kind: Literal["purchase_in", "sale_out", "adjustment", "reversal"]
    quantity: str  # signed, 3 decimals
    occurred_on: date
    source_type: Literal["purchase_invoice", "sales_invoice"] | None
    source_id: str | None
    source_line_id: str | None
    unit_cost: str | None
    is_practice: bool  # a sale_out from a practice-numbered invoice
    reverses_id: str | None
    reversed_by_id: str | None
    reason: str | None
    created_at: str
    created_by: str


class MovementPageOut(BaseModel):
    items: list[MovementOut]
    has_more: bool


class AdjustmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: Annotated[str, Field(max_length=24)]  # signed decimal string, not zero
    reason: Annotated[str, Field(max_length=300)]
    occurred_on: date


class ReversalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[str, Field(max_length=300)]


def _qty(value) -> str:
    return f"{value:.3f}"


def _item(r: inventory.StockRow) -> dict:
    return {"product_id": str(r.product_id), "code": r.code, "name": r.name, "uqc": r.uqc, "status": r.status,
            "sale_rate": f"{r.sale_rate:.2f}", "price_needed": r.price_needed, "on_hand": _qty(r.on_hand),
            "no_stock": r.no_stock}


def _movement(m: inventory.Movement) -> dict:
    def s(v):
        return None if v is None else str(v)

    return {"id": str(m.id), "product_id": str(m.product_id), "kind": m.kind, "quantity": _qty(m.quantity),
            "occurred_on": m.occurred_on, "source_type": m.source_type, "source_id": s(m.source_id),
            "source_line_id": s(m.source_line_id), "unit_cost": None if m.unit_cost is None else f"{m.unit_cost:.2f}", "is_practice": m.is_practice,
            "reverses_id": s(m.reverses_id), "reversed_by_id": s(m.reversed_by_id), "reason": m.reason,
            "created_at": m.created_at.isoformat(), "created_by": str(m.created_by)}


def _once(request: Request, uow, key: str | None, payload: dict, operation):
    return run_once(uow.tx, uow.principal.business_id, key, method=request.method,
                    route=request.scope["route"].path, payload=payload, operation=operation)


@router.get("/b/{business_id}/stock", response_model=StockPageOut, dependencies=VIEW)
def list_stock(
    uow: BusinessUoW,
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "archived", "all"] = "active",
    only: Literal["no_stock", "price_needed"] | None = None,
):
    require_business_type(uow.tx)
    rows, more = inventory.stock_page(uow, q=q, status=status, only=only, limit=page.limit, offset=page.offset)
    return {"items": [_item(r) for r in rows], "has_more": more}


@router.get("/b/{business_id}/products/{product_id}/stock-movements", response_model=MovementPageOut,
            dependencies=VIEW)
def list_movements(product_id: str, uow: BusinessUoW, page: Annotated[PageParams, Depends(page_params)],
                   practice: bool | None = None):
    require_business_type(uow.tx)
    rows, more = inventory.movements(uow, parse_id(product_id), limit=page.limit, offset=page.offset,
                                     practice=practice)
    return {"items": [_movement(m) for m in rows], "has_more": more}


@router.post("/b/{business_id}/products/{product_id}/stock-adjustments", status_code=http.HTTP_201_CREATED,
             response_model=MovementOut, dependencies=EDIT)
def adjust_stock(
    product_id: str,
    body: AdjustmentIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    require_business_type(uow.tx)
    pid = parse_id(product_id)

    def adjust():
        movement_id = inventory.adjust(uow, pid, body.quantity, body.reason, body.occurred_on, today=clock.today())
        return _movement(_one(uow, movement_id))

    return _once(request, uow, idempotency_key, {"product_id": str(pid), **body.model_dump(mode="json")}, adjust)


@router.post("/b/{business_id}/stock-movements/{movement_id}/reversals", status_code=http.HTTP_201_CREATED,
             response_model=MovementOut, dependencies=EDIT)
def reverse_movement(
    movement_id: str,
    body: ReversalIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    require_business_type(uow.tx)
    mid = parse_id(movement_id)

    def reverse():
        return _movement(_one(uow, inventory.reverse(uow, mid, body.reason, today=clock.today())))

    return _once(request, uow, idempotency_key, {"movement_id": str(mid), **body.model_dump(mode="json")}, reverse)


def _one(uow, movement_id) -> inventory.Movement:
    return inventory.get_movement(uow, movement_id)
