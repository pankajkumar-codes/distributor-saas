"""Customer routes (LLD-3 §6.2) under /api/v1/b/{business_id}, on business_uow.

POST takes an Idempotency-Key (run_once); PATCH and DELETE take If-Match with the
version the user saw (L3-9). Inline GSTIN checking while typing is LLD-1's
POST /gstin-checks, so there is one implementation of gstin.md.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi import status as http
from pydantic import BaseModel

from platform_common.clock import Clock, get_clock
from platform_common.paging import PageParams, page_params
from platform_common.uow import BusinessUoW, parse_id

from . import customers
from .api_products import EDIT, VIEW, Text, Warning, _once, _version

router = APIRouter(tags=["catalog"])


class AddressIn(BaseModel):
    line1: Text | None = None
    line2: Text | None = None
    city: Text | None = None
    pin: Text | None = None
    state_code: Text | None = None  # billing defaults to the GSTIN's state


class CustomerIn(BaseModel):
    name: Text
    gstin: Text | None = None
    billing: AddressIn = AddressIn()
    delivery_same_as_billing: bool = True
    delivery: AddressIn | None = None
    credit_days: int = 0


class CustomerPatch(BaseModel):
    name: Text | None = None
    gstin: Text | None = None
    billing: AddressIn | None = None
    delivery_same_as_billing: bool | None = None
    delivery: AddressIn | None = None
    credit_days: int | None = None


class AddressOut(BaseModel):
    line1: str | None
    line2: str | None
    city: str | None
    pin: str | None
    state_code: str | None


class CustomerOut(BaseModel):
    id: str
    name: str
    gstin: str | None
    gstin_state_code: str | None
    billing: AddressOut
    delivery_same_as_billing: bool
    delivery: AddressOut | None
    credit_days: int
    status: str
    version: int
    in_use: bool
    warnings: list[Warning]


class CustomerPageOut(BaseModel):
    items: list[CustomerOut]
    has_more: bool


def _out(c: customers.Customer) -> dict:
    return {
        "id": str(c.id),
        "name": c.name,
        "gstin": c.gstin,
        "gstin_state_code": c.gstin_state_code,
        "billing": c.address("billing"),
        "delivery_same_as_billing": c.delivery_same_as_billing,
        "delivery": None if c.delivery_same_as_billing else c.address("delivery"),
        "credit_days": c.credit_days,
        "status": c.status,
        "version": c.version,
        "in_use": c.in_use,
        "warnings": customers.warnings(c),
    }


@router.get("/b/{business_id}/customers", response_model=CustomerPageOut, dependencies=VIEW)
def list_customers(
    uow: BusinessUoW,
    page: Annotated[PageParams, Depends(page_params)],
    q: Annotated[str | None, Query(max_length=100)] = None,
    status: Literal["active", "archived", "all"] = "active",
):
    items, more = customers.search(uow, q=q, status=status, limit=page.limit, offset=page.offset)
    return {"items": [_out(c) for c in items], "has_more": more}


@router.post("/b/{business_id}/customers", status_code=http.HTTP_201_CREATED, response_model=CustomerOut,
             dependencies=EDIT)
def create_customer(
    body: CustomerIn,
    request: Request,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    def create():
        return _out(customers.get(uow, customers.create(uow, body.model_dump(), clock.today())))

    return _once(request, uow, idempotency_key, body.model_dump(mode="json"), create)


@router.get("/b/{business_id}/customers/{customer_id}", response_model=CustomerOut, dependencies=VIEW)
def get_customer(customer_id: str, uow: BusinessUoW):
    return _out(customers.get(uow, parse_id(customer_id)))


@router.patch("/b/{business_id}/customers/{customer_id}", response_model=CustomerOut, dependencies=EDIT)
def update_customer(
    customer_id: str,
    body: CustomerPatch,
    uow: BusinessUoW,
    clock: Annotated[Clock, Depends(get_clock)],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):
    cid = parse_id(customer_id)
    customers.update(uow, cid, body.model_dump(exclude_unset=True), _version(if_match), clock.today())
    return _out(customers.get(uow, cid))


@router.post("/b/{business_id}/customers/{customer_id}/archive", response_model=CustomerOut, dependencies=EDIT)
def archive_customer(customer_id: str, uow: BusinessUoW):
    cid = parse_id(customer_id)
    customers.set_archived(uow, cid, True)
    return _out(customers.get(uow, cid))


@router.post("/b/{business_id}/customers/{customer_id}/unarchive", response_model=CustomerOut, dependencies=EDIT)
def unarchive_customer(customer_id: str, uow: BusinessUoW):
    cid = parse_id(customer_id)
    customers.set_archived(uow, cid, False)
    return _out(customers.get(uow, cid))


@router.delete("/b/{business_id}/customers/{customer_id}", status_code=http.HTTP_204_NO_CONTENT,
               dependencies=EDIT)
def delete_customer(customer_id: str, uow: BusinessUoW,
                    if_match: Annotated[str | None, Header(alias="If-Match")] = None):
    customers.delete(uow, parse_id(customer_id), _version(if_match))
    return Response(status_code=http.HTTP_204_NO_CONTENT)
