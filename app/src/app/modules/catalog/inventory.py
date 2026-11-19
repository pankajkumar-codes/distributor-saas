"""The stock ledger (R2-M3): what a business holds, as insert-only movements.

Every function runs in the caller's unit of work under the bound business's row-level
security, and also filters on that business explicitly, so a product or movement of another
business is simply not found (404). Nothing updates or deletes a movement (the table refuses
it); a mistake is reversed by a new row. The balance is always the sum of a product's rows.

Stock never blocks anything: a balance at or below zero is shown as "no stock" by the
screens, and a movement that takes it below zero is still recorded (Pankaj's R2 rule).
Quantities are Decimal with at most 3 decimal places (the column is numeric(15,3)).
No cost or profit is worked out here: `unit_cost` is stored as the purchase price per 1 qty
for later, and the costing policy is still undecided (CLAUDE.md approval gate).
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from platform_common import audit
from platform_common.errors import Conflict, Deny, Invalid
from platform_common.ids import uuid7
from platform_common.uow import UnitOfWork

from . import products
from .rates import parse_rate

QTY_PLACES = Decimal("0.001")
MAX_QTY = Decimal("999999999999")  # numeric(15,3): 12 digits before the point
_BIZ = "business_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


# --- Shapes ------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewCatalogItem:
    """A product the catalog does not have yet; created at the confirm step."""

    code: str
    name: str
    uqc: str
    hsn: str | None
    tax_category: Literal["taxable", "exempt", "nil_rated", "non_gst"]
    gst_rate: str | None = None  # a decimal string, required when taxable; never filled in by us
    rate_valid_from: date | None = None  # required with gst_rate
    has_cess: bool = False


@dataclass(frozen=True)
class ConfirmedPurchaseLine:
    source_id: uuid.UUID  # the purchase invoice
    source_line_id: uuid.UUID  # its line; (source_id, source_line_id) is the idempotency key
    quantity: Decimal  # > 0, at most 3 decimal places
    received_on: date
    product_id: uuid.UUID | None = None  # exactly one of product_id and new_item
    new_item: NewCatalogItem | None = None
    unit_cost: Decimal | None = None  # per 1 qty, excluding GST; stored only


@dataclass(frozen=True)
class ReceivedLine:
    product_id: uuid.UUID
    movement_id: uuid.UUID
    created_product: bool
    already_received: bool  # a retry of the same line: the same ids, no second movement
    price_needed: bool  # the selling price per 1 qty is still to be set


@dataclass(frozen=True)
class Movement:
    id: uuid.UUID
    product_id: uuid.UUID
    kind: str
    quantity: Decimal
    occurred_on: date
    source_type: str | None
    source_id: uuid.UUID | None
    source_line_id: uuid.UUID | None
    unit_cost: Decimal | None
    is_practice: bool
    reverses_id: uuid.UUID | None
    reversed_by_id: uuid.UUID | None
    reason: str | None
    created_at: object
    created_by: uuid.UUID


@dataclass(frozen=True)
class StockRow:
    product_id: uuid.UUID
    code: str
    name: str
    uqc: str
    status: str
    sale_rate: Decimal
    price_needed: bool
    on_hand: Decimal

    @property
    def no_stock(self) -> bool:
        return self.on_hand <= 0


# --- Quantities --------------------------------------------------------------------------


def parse_quantity(raw, *, field: str = "quantity", signed: bool = False) -> Decimal:
    """A decimal string (or Decimal) with at most 3 decimals, never a float, never zero.
    Positive unless `signed`."""
    if isinstance(raw, float) or isinstance(raw, bool):
        raise Invalid("quantity_invalid", "Enter the quantity as a number like 12 or 2.5", field=field)
    try:
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        raise Invalid("quantity_invalid", "Enter the quantity as a number like 12 or 2.5", field=field) from None
    if not value.is_finite() or value != value.quantize(QTY_PLACES) or abs(value) > MAX_QTY:
        raise Invalid("quantity_invalid", "Use a number with at most 3 decimals", field=field)
    if value == 0:
        raise Invalid("quantity_zero", "The quantity can't be zero", field=field)
    if value < 0 and not signed:
        raise Invalid("quantity_invalid", "The quantity must be more than zero", field=field)
    return value.quantize(QTY_PLACES)


def _reason(raw) -> str:
    value = (raw or "").strip() if isinstance(raw, str) else ""
    if not value or len(value) > 300 or not value.isprintable():
        raise Invalid("reason_required", "Give a reason of up to 300 characters", field="reason")
    return value


def _check_date(on: date, today: date, field: str) -> None:
    if on > today:
        raise Invalid("date_in_future", "That date hasn't happened yet", field=field)


# --- Reads -------------------------------------------------------------------------------

_MOVEMENT = (
    "select m.id, m.product_id, m.kind, m.quantity, m.occurred_on, m.source_type, m.source_id, m.source_line_id,"
    " m.unit_cost, m.is_practice, m.reverses_id, r.id as reversed_by_id, m.reason, m.created_at, m.created_by"
    " from catalog.stock_movements m"
    " left join catalog.stock_movements r on r.reverses_id = m.id and r.business_id = m.business_id"
)


def _movement(row) -> Movement:
    return Movement(*row)


def on_hand(uow: UnitOfWork, product_id: uuid.UUID) -> Decimal:
    """The product's balance: the sum of its movements (zero if it has none)."""
    return uow.tx.execute(
        text("select coalesce(sum(quantity), 0) from catalog.stock_movements"
             f" where product_id = :p and business_id = :b and {_BIZ}"),
        {"p": product_id, "b": uow.principal.business_id},
    ).scalar_one()


def get_movement(uow: UnitOfWork, movement_id: uuid.UUID) -> Movement:
    row = uow.tx.execute(
        text(f"{_MOVEMENT} where m.id = :m and m.business_id = :b"),
        {"m": movement_id, "b": uow.principal.business_id},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    return _movement(row)


def stock_page(uow: UnitOfWork, *, q: str | None, status: str, only: str | None, limit: int,
               offset: int) -> tuple[list[StockRow], bool]:
    """Products with what is on hand, by code. `only` narrows to no_stock (balance at or
    below zero) or price_needed."""
    where = ["p.business_id = :b", "p.status <> 'deleted'"]
    params: dict = {"b": uow.principal.business_id, "limit": limit + 1, "offset": offset}
    if status in ("active", "archived"):
        where.append("p.status = :status")
        params["status"] = status
    if q and q.strip():
        needle = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(p.name ilike :frag or lower(p.code) like :prefix)")
        params.update(frag=f"%{needle}%", prefix=f"{needle}%")
    if only == "price_needed":
        where.append("p.price_needed")
    having = "having coalesce(sum(m.quantity), 0) <= 0" if only == "no_stock" else ""
    rows = uow.tx.execute(
        text(
            "select p.id, p.code, p.name, p.uqc, p.status, p.sale_rate, p.price_needed,"
            " coalesce(sum(m.quantity), 0) as on_hand"
            " from catalog.products p left join catalog.stock_movements m"
            "   on m.product_id = p.id and m.business_id = p.business_id"
            f" where {' and '.join(where)} group by p.id {having}"
            " order by lower(p.code), p.id limit :limit offset :offset"
        ),
        params,
    ).all()
    return [StockRow(*r) for r in rows[:limit]], len(rows) > limit


def movements(uow: UnitOfWork, product_id: uuid.UUID, *, limit: int, offset: int,
              practice: bool | None = None) -> tuple[list[Movement], bool]:
    products._get(uow, product_id)  # 404 for an unknown, deleted or another business's product
    rows = uow.tx.execute(
        text(f"{_MOVEMENT} where m.product_id = :p and m.business_id = :b"
             + ("" if practice is None else " and m.is_practice = :practice")
             + " order by m.created_at desc, m.id desc limit :limit offset :offset"),
        {"p": product_id, "b": uow.principal.business_id, "limit": limit + 1, "offset": offset,
         **({} if practice is None else {"practice": practice})},
    ).all()
    return [_movement(r) for r in rows[:limit]], len(rows) > limit


# --- Writes ------------------------------------------------------------------------------

_INSERT = text(
    "insert into catalog.stock_movements (id, business_id, product_id, kind, quantity, occurred_on, source_type,"
    " source_id, source_line_id, unit_cost, reverses_id, reason, is_practice, created_by)"
    " values (:id, :b, :p, :kind, :qty, :on, :stype, :sid, :slid, :cost, :rev, :reason, :practice, :me)"
)


def _post(uow: UnitOfWork, product_id: uuid.UUID, kind: str, quantity: Decimal, on: date, *, source_type=None,
          source_id=None, source_line_id=None, unit_cost=None, reverses_id=None, reason=None,
          practice: bool = False) -> uuid.UUID:
    movement_id = uuid7()
    uow.tx.execute(
        _INSERT,
        {"id": movement_id, "b": uow.principal.business_id, "p": product_id, "kind": kind, "qty": quantity, "on": on,
         "stype": source_type, "sid": source_id, "slid": source_line_id, "cost": unit_cost, "rev": reverses_id,
         "reason": reason, "practice": practice, "me": uow.principal.user_id},
    )
    return movement_id


def _existing_receipt(uow: UnitOfWork, source_id: uuid.UUID, source_line_id: uuid.UUID):
    return uow.tx.execute(
        text("select id, product_id from catalog.stock_movements where business_id = :b and kind = 'purchase_in'"
             " and source_type = 'purchase_invoice' and source_id = :s and source_line_id = :l"),
        {"b": uow.principal.business_id, "s": source_id, "l": source_line_id},
    ).one_or_none()


def _price_needed(uow: UnitOfWork, product_id: uuid.UUID) -> bool:
    return uow.tx.execute(
        text("select price_needed from catalog.products where id = :p and business_id = :b"),
        {"p": product_id, "b": uow.principal.business_id},
    ).scalar_one()


def receive_confirmed_purchase_line(uow: UnitOfWork, line: ConfirmedPurchaseLine, *, today: date) -> ReceivedLine:
    """A purchase line the business confirmed becomes stock: the catalog item (an existing
    one, or a new one created here) and one stock-in movement, in the caller's transaction,
    so a failure rolls the caller's confirm back with it. Once per (source_id,
    source_line_id): a retry returns the same ids with `already_received`. Call it only from
    the confirm step; nothing is received from a line the business has not confirmed.
    """
    if (line.product_id is None) == (line.new_item is None):
        raise Invalid("product_or_new_item", "Give either an existing product or a new one, not both and not neither",
                      field="product_id")
    quantity = parse_quantity(line.quantity)
    _check_date(line.received_on, today, "received_on")
    unit_cost = None
    if line.unit_cost is not None:
        if not isinstance(line.unit_cost, Decimal) or line.unit_cost < 0 or line.unit_cost != line.unit_cost.quantize(
                Decimal("0.01")):
            raise Invalid("unit_cost_invalid", "Use a price with at most 2 decimals", field="unit_cost")
        unit_cost = line.unit_cost
    done = _existing_receipt(uow, line.source_id, line.source_line_id)
    if done is not None:
        if line.product_id is not None and line.product_id != done.product_id:
            raise Conflict("source_line_conflict", "That purchase line was already received into another product")
        return ReceivedLine(done.product_id, done.id, False, True, _price_needed(uow, done.product_id))

    created = False
    if line.new_item is not None:
        product_id = _create_item(uow, line.new_item, today)
        created = True
    else:
        product_id = line.product_id
        products._get(uow, product_id)  # 404 for an unknown, deleted or another business's product
    try:
        with uow.tx.begin_nested():
            movement_id = _post(uow, product_id, "purchase_in", quantity, line.received_on,
                                source_type="purchase_invoice", source_id=line.source_id,
                                source_line_id=line.source_line_id, unit_cost=unit_cost)
    except IntegrityError as exc:
        if "stock_movements_source_uq" not in str(exc.orig):
            raise
        done = _existing_receipt(uow, line.source_id, line.source_line_id)  # a concurrent retry won
        return ReceivedLine(done.product_id, done.id, False, True, _price_needed(uow, done.product_id))
    code = uow.tx.execute(text("select code from catalog.products where id = :p and business_id = :b"),
                          {"p": product_id, "b": uow.principal.business_id}).scalar_one()
    audit.record(uow, "stock.received", "product", product_id, data={"code": code, "quantity": f"{quantity:f}"})
    return ReceivedLine(product_id, movement_id, created, False, _price_needed(uow, product_id))


def _create_item(uow: UnitOfWork, item: NewCatalogItem, today: date) -> uuid.UUID:
    rate = None
    if item.gst_rate is not None or item.rate_valid_from is not None:
        if item.gst_rate is None or item.rate_valid_from is None:
            raise Invalid("rate_required", "Give the GST rate together with the date it applies from", field="gst_rate")
        parse_rate(item.gst_rate)
        rate = {"rate": item.gst_rate, "valid_from": item.rate_valid_from}
    product_id = products.create(
        uow,
        {"code": item.code, "name": item.name, "hsn": item.hsn, "uqc": item.uqc, "sale_rate": "0.00",
         "barcode": None, "tax_category": item.tax_category, "has_cess": item.has_cess, "rate": rate},
        today,
    )
    # The selling price per 1 qty is for the business to name; until it does, the flag stays on.
    uow.tx.execute(
        text("update catalog.products set price_needed = true where id = :p and business_id = :b"),
        {"p": product_id, "b": uow.principal.business_id},
    )
    return product_id


def adjust(uow: UnitOfWork, product_id: uuid.UUID, quantity, reason, on: date, *, today: date) -> uuid.UUID:
    """A count correction: a signed, non-zero quantity with a reason. May take the balance
    below zero (stock never blocks)."""
    qty = parse_quantity(quantity, signed=True)
    why = _reason(reason)
    _check_date(on, today, "occurred_on")
    p = products._get(uow, product_id)
    movement_id = _post(uow, product_id, "adjustment", qty, on, reason=why)
    audit.record(uow, "stock.adjusted", "product", product_id, reason=why,
                 data={"code": p.code, "quantity": f"{qty:f}"})
    return movement_id


def reverse(uow: UnitOfWork, movement_id: uuid.UUID, reason, *, today: date) -> uuid.UUID:
    """Cancel one earlier movement with a new row of the opposite sign. The original stays.
    A movement is reversed once, and a reversal itself is not reversed (post the movement again)."""
    why = _reason(reason)
    row = uow.tx.execute(
        text("select id, product_id, kind, quantity, is_practice from catalog.stock_movements"
             " where id = :m and business_id = :b"),
        {"m": movement_id, "b": uow.principal.business_id},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    if row.kind == "reversal":
        raise Conflict("cannot_reverse_a_reversal", "A reversal can't be reversed",
                       fix="Record the movement again instead")
    already = uow.tx.execute(
        text("select 1 from catalog.stock_movements where reverses_id = :m and business_id = :b"),
        {"m": movement_id, "b": uow.principal.business_id},
    ).first()
    if already is not None:
        raise Conflict("already_reversed", "That movement has already been reversed")
    p = products._get(uow, row.product_id)
    try:
        with uow.tx.begin_nested():
            new_id = _post(uow, row.product_id, "reversal", -row.quantity, today, reverses_id=movement_id, reason=why,
                            practice=row.is_practice)  # a reversal keeps its original's practice tag
    except IntegrityError as exc:
        if "stock_movements_reverses_uq" not in str(exc.orig):
            raise
        raise Conflict("already_reversed", "That movement has already been reversed") from None
    audit.record(uow, "stock.reversed", "product", row.product_id, reason=why,
                 data={"code": p.code, "quantity": f"{-row.quantity:f}"})
    return new_id


def record_sale_out(uow: UnitOfWork, *, product_id: uuid.UUID, quantity: Decimal, document_id: uuid.UUID,
                    document_line_id: uuid.UUID, sold_on: date, practice: bool = False) -> uuid.UUID:
    """A finalized invoice line takes stock out: one negative movement, once per
    (document_id, document_line_id), in the caller's unit of work so it commits or rolls back
    with the invoice. It NEVER refuses for lack of stock: the balance may go to or below zero
    (Pankaj's R2 rule), and the screens show "no stock". Called only by sales' finalize.
    A retry returns the movement already written. `practice` is true for a practice-numbered
    invoice: it takes stock out like any other (CEO decision) and is tagged so it can be
    filtered or reversed later.
    """
    qty = parse_quantity(quantity)
    row = uow.tx.execute(
        text("select id from catalog.stock_movements where business_id = :b and kind = 'sale_out'"
             " and source_type = 'sales_invoice' and source_id = :s and source_line_id = :l"),
        {"b": uow.principal.business_id, "s": document_id, "l": document_line_id},
    ).one_or_none()
    if row is not None:
        return row.id
    return _post(uow, product_id, "sale_out", -qty, sold_on, source_type="sales_invoice", source_id=document_id,
                 source_line_id=document_line_id, practice=practice)
