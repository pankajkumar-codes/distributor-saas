"""What other modules may call in catalog (LLD-3 §8). Sales (LLD-4) reads products for
invoice lines and marks them used at finalize; Home reads the setup counts.

Every function takes the caller's transaction (uow.tx) and runs under its business's
row-level security, so another business's product or customer is simply not found.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.modules.refdata import value_on
from platform_common.errors import Conflict, Deny

from ..rates import RateRow, rate_on

__all__ = [
    "Address",
    "CustomerSnapshot",
    "ProductForLine",
    "SetupCounts",
    "customer_snapshot",
    "mark_used",
    "product_for_line",
    "products_for_lines",
    "setup_counts",
]


@dataclass(frozen=True)
class ProductForLine:
    product_id: uuid.UUID
    code: str
    name: str
    hsn: str | None
    uqc: str
    sale_rate: Decimal  # per unit, excluding GST [RM43-3]
    tax_category: str
    has_cess: bool
    status: str  # active or archived; LLD-4 decides what an archived product may do
    rate: Decimal | None
    rate_id: uuid.UUID | None
    rate_valid_from: date | None
    rate_confirmed: bool
    rate_changed_within_warning_window: bool


@dataclass(frozen=True)
class Address:
    line1: str | None
    line2: str | None
    city: str | None
    pin: str | None
    state_code: str


@dataclass(frozen=True)
class CustomerSnapshot:
    customer_id: uuid.UUID
    name: str
    gstin: str | None
    gstin_state_code: str | None
    billing: Address
    delivery: Address  # the billing address again when delivery_same_as_billing
    delivery_same_as_billing: bool
    credit_days: int
    status: str  # active or archived; LLD-4 decides what an archived customer may do


@dataclass(frozen=True)
class SetupCounts:
    active_products: int
    products_missing_hsn: int
    products_unconfirmed_rate: int
    active_customers: int


def products_for_lines(tx: Session, product_ids: list[uuid.UUID], on: date) -> dict[uuid.UUID, ProductForLine]:
    """One query for a draft's products. Deleted or unknown IDs are left out; the caller
    compares with what it asked for (product_for_line raises instead)."""
    ids = list(dict.fromkeys(product_ids))
    if not ids:
        return {}
    days = int(value_on(tx, "catalog.rate_change_warning_days", on))
    products = tx.execute(
        text(
            "select id, code, name, hsn, uqc, sale_rate, tax_category, has_cess, status from catalog.products"
            " where id in :ids and status <> 'deleted'"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).all()
    rows: dict[uuid.UUID, list[RateRow]] = {p.id: [] for p in products}
    if not rows:
        return {}
    for product_id, *rate in tx.execute(
        text(
            "select r.product_id, r.id, r.rate, r.valid_from,"
            " exists (select 1 from catalog.product_rate_voids v where v.rate_id = r.id),"
            " coalesce((select c.action = 'confirm' from catalog.product_rate_confirmations c"
            "           where c.rate_id = r.id order by c.created_at desc, c.id desc limit 1), false)"
            " from catalog.product_rates r where r.product_id in :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(rows)},
    ):
        rows[product_id].append(RateRow(*rate))
    out = {}
    for p in products:
        found = rate_on(rows[p.id], on, days) if p.tax_category == "taxable" else None
        out[p.id] = ProductForLine(
            p.id, p.code, p.name, p.hsn, p.uqc, p.sale_rate, p.tax_category, p.has_cess, p.status,
            found.row.rate if found else None,
            found.row.id if found else None,
            found.row.valid_from if found else None,
            found.row.confirmed if found else False,
            found.changed_within_warning_window if found else False,
        )
    return out


def product_for_line(tx: Session, product_id: uuid.UUID, on: date) -> ProductForLine:
    """Deny("not_found") for an unknown, another business's or deleted product. A taxable
    product with no rate on `on` comes back with rate None; LLD-4 refuses the line
    (no_rate_on_date)."""
    found = products_for_lines(tx, [product_id], on).get(product_id)
    if found is None:
        raise Deny("not_found")
    return found


def customer_snapshot(tx: Session, customer_id: uuid.UUID) -> CustomerSnapshot:
    """What sales copies onto a draft (§8.1). Deny("not_found") for an unknown, another
    business's or deleted customer."""
    row = tx.execute(
        text(
            "select id, name, gstin, gstin_state_code, billing_line1, billing_line2, billing_city, billing_pin,"
            " billing_state_code, delivery_same_as_billing, delivery_line1, delivery_line2, delivery_city,"
            " delivery_pin, delivery_state_code, credit_days, status"
            " from catalog.customers where id = :c and status <> 'deleted'"
        ),
        {"c": customer_id},
    ).one_or_none()
    if row is None:
        raise Deny("not_found")
    billing = Address(row.billing_line1, row.billing_line2, row.billing_city, row.billing_pin, row.billing_state_code)
    delivery = billing if row.delivery_same_as_billing else Address(
        row.delivery_line1, row.delivery_line2, row.delivery_city, row.delivery_pin, row.delivery_state_code
    )
    return CustomerSnapshot(row.id, row.name, row.gstin, row.gstin_state_code, billing, delivery,
                            row.delivery_same_as_billing, row.credit_days, row.status)


def _mark(tx: Session, table: str, ids: list[uuid.UUID]) -> int:
    return len(tx.execute(
        text(
            f"update catalog.{table} set first_used_at = coalesce(first_used_at, now())"
            " where id in :ids and status <> 'deleted' returning id"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    ).all())


def mark_used(tx: Session, product_ids: list[uuid.UUID], customer_id: uuid.UUID | None = None) -> None:
    """Inside sales' finalize transaction (L3-6, [RM43-4]): sets first_used_at once, and
    raises Conflict("product_deleted") or Conflict("customer_deleted") if one was deleted
    meanwhile, so the finalize rolls back. One product on two lines counts once (RM-4.3
    row 14). It takes the same row lock as delete and doesn't bump version."""
    ids = list(dict.fromkeys(product_ids))
    if ids and _mark(tx, "products", ids) != len(ids):
        raise Conflict("product_deleted", "A product on this invoice was deleted", fix="Remove the line and add it again")
    if customer_id is not None and _mark(tx, "customers", [customer_id]) != 1:
        raise Conflict("customer_deleted", "This invoice's customer was deleted", fix="Choose the customer again")


def setup_counts(tx: Session, on: date) -> SetupCounts:
    """For M3's products tile and the ON-6 checklist (§8.2)."""
    row = tx.execute(
        text(
            "select count(*) filter (where p.status = 'active'),"
            " count(*) filter (where p.status = 'active' and p.hsn is null),"
            " count(*) filter (where p.status = 'active' and p.tax_category = 'taxable'"
            "                  and not coalesce(cr.confirmed, false)),"
            " (select count(*) from catalog.customers c where c.status = 'active')"
            " from catalog.products p left join catalog.current_rates(:on) cr on cr.product_id = p.id"
            " where p.status <> 'deleted'"
        ),
        {"on": on},
    ).one()
    return SetupCounts(*row)
