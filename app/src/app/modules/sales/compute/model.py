"""What the invoice computation takes and returns (LLD-4 §3; interface agreed with the
Lead in team/docs/s4c-compute-interface.md). Money and rates are Decimal throughout.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.modules.catalog.interface import ProductForLine

METHOD_VERSION = "apportion-v1"  # stored on the document with the rounding mode (L4-1)

Component = Literal["CGST", "SGST", "UTGST", "IGST"]
SupplyClass = Literal["B2B", "B2CL", "B2CS"]
EinvoiceStatus = Literal["applies", "unsure", "no"]  # LLD-1 erratum S-3


# -- What S4-b hands load_inputs: the draft as stored ----------------------------------
@dataclass(frozen=True)
class DraftLineIn:
    """One sales.draft_lines row of an invoice draft."""

    line_no: int
    product_id: uuid.UUID | None
    quantity: Decimal | None
    unit_price: Decimal | None
    discount_kind: Literal["amount", "percent"] | None = None
    discount_value: Decimal | None = None


@dataclass(frozen=True)
class DraftIn:
    """The sales.drafts fields the computation reads."""

    doc_date: date
    customer_id: uuid.UUID | None  # None = cash sale
    cash_buyer: dict | None = None  # {name?, state_code, address?}
    bill_to: dict | None = None  # each address carries state_code
    ship_to: dict | None = None
    ship_to_third_party: bool = False
    customer_collects: bool = False
    invoice_discount: Decimal = Decimal()
    charges: tuple[tuple[str, Decimal], ...] = ()  # (label, amount), parsed with to_decimal
    pos_override: str | None = None
    pos_override_reason: str | None = None
    has_eway_details: bool = False


# -- What compute takes ----------------------------------------------------------------
@dataclass(frozen=True)
class Rules:
    """Refdata in force on doc_date (LLD-4 §3, refdata-lld4.md)."""

    rounding_mode: str  # invoice.rounding_mode
    round_off_line: bool  # invoice.round_off_line
    utgst_state_codes: frozenset[str]  # gst.utgst_state_codes
    b2cl_threshold: Decimal  # gstr1.b2cl_threshold
    unregistered_address_threshold: Decimal  # invoice.unregistered_address_threshold
    eway_threshold: Decimal  # eway.consignment_value_threshold


@dataclass(frozen=True)
class Seller:
    state_code: str  # GSTIN positions 1-2 (business profile state_code)
    hsn_min_digits: int  # business.hsn_min_digits on doc_date
    einvoice_status: EinvoiceStatus  # business.einvoice_status on doc_date
    ready_missing: tuple[str, ...] = ()  # business.ready_for_documents().missing


@dataclass(frozen=True)
class Buyer:
    gstin: str | None
    gstin_state_code: str | None
    name: str | None
    bill_to_state: str | None
    ship_to_state: str | None
    has_delivery_address: bool
    ship_to_third_party: bool = False
    customer_collects: bool = False


@dataclass(frozen=True)
class LineIn:
    line_no: int
    product: ProductForLine | None  # None: unknown or deleted
    quantity: Decimal | None
    unit_price: Decimal | None
    discount_kind: Literal["amount", "percent"] | None = None
    discount_value: Decimal | None = None


@dataclass(frozen=True)
class ComputeInput:
    doc_date: date
    today: date
    seller: Seller
    buyer: Buyer
    lines: tuple[LineIn, ...]
    rules: Rules
    invoice_discount: Decimal = Decimal()
    charges: tuple[tuple[str, Decimal], ...] = ()
    pos_override: str | None = None
    pos_override_reason: str | None = None
    has_eway_details: bool = False


# -- What compute returns ----------------------------------------------------------------
@dataclass(frozen=True)
class Tax:
    component: Component
    rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class LineOut:
    line_no: int
    product: ProductForLine | None
    quantity: Decimal | None
    unit_price: Decimal | None
    gross: Decimal
    line_discount: Decimal
    base: Decimal
    discount_share: Decimal
    charge_share: Decimal
    taxable: Decimal
    rate: Decimal | None
    taxes: tuple[Tax, ...]
    total: Decimal


@dataclass(frozen=True)
class Issue:
    """A block (finalize refused) or a warning (shown, never blocks), LLD-4 §3.4."""

    code: str
    fix: str
    field: str | None = None  # a request path, e.g. lines.0.quantity
    line_no: int | None = None


@dataclass(frozen=True)
class Computation:
    computed_pos: str | None
    pos_state_code: str | None  # after the override
    is_inter_state: bool | None
    utgst: bool
    supply_class: SupplyClass | None
    lines: tuple[LineOut, ...]
    gross_total: Decimal
    line_discount_total: Decimal
    invoice_discount: Decimal
    charges_total: Decimal
    taxable_total: Decimal
    cgst_total: Decimal
    sgst_total: Decimal  # carries UTGST when `utgst`
    igst_total: Decimal
    round_off: Decimal
    doc_total: Decimal
    amount_in_words: str
    rounding_mode: str
    method_version: str = METHOD_VERSION
    blocks: tuple[Issue, ...] = field(default=())
    warnings: tuple[Issue, ...] = field(default=())
