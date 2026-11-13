"""Flipkart's monthly workbook readers (R1-M4 S2; platform-reader-spec section 3): `Sales Report - <range>.xlsx`
with a `Sales Report` sheet and a `Cash Back Report` sheet (a `Help` sheet is not read), alone or in a zip.

Written from the spec's header list, not yet from a checked sample: both profiles ship unverified and
refdata `imports.profile.<id>.verified` is false, so every run carries the "layout unchecked" note. Only
headers the spec names exactly are read as required; the tax rate and amount pair names are the spec's
description of them and are the first thing a real file must confirm. Personal columns (names, addresses,
pincodes) are never mapped, so never stored. Flipkart writes numbers as text and rates as percent
numbers (18.0), so rates are kept as written; the whole sheet is read whatever size it declares.

What a row means is the build's job (R1-M7). Sales rows are read as written (signed amounts) and held
when something can't be placed: an unknown event type, a missing HSN, quantity or delivery state, a rate
outside 0 to 100, a row that charges both IGST and CGST or SGST, a cancellation carrying value. A
cancellation with no value is shown as zero-value and left out of the return. Every Cash Back row is held
as `cashback_adjustment`: how those notes enter GSTR-1 is a CA question (spec section 5, item 2).
"""

from decimal import Decimal

from ..models import StagedRowStatus
from ..parsing import FieldKind, FieldSpec, MappingProfile
from .base import HeaderReader

PERCENT = Decimal(100)
DATETIME = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S")

SALE_EVENTS = ("Sale", "Return")
SALE_SUBTYPES = ("Sale", "Cancellation", "Return", "Return Cancellation")
CANCELLATIONS = ("Cancellation", "Return Cancellation")

SALES_SHEET = "Sales Report"
CASHBACK_SHEET = "Cash Back Report"
TAXABLE = "Taxable Value (Final Invoice Amount -Taxes)"


def _text(name, *headers, **kw):
    return FieldSpec(name, headers, **kw)


def _money(name, *headers):
    return FieldSpec(name, headers, FieldKind.decimal, required=False)


def _stamp(name, *headers):
    return FieldSpec(name, headers, FieldKind.datetime, required=False, formats=DATETIME)


TAX = (
    _money("igst_rate", "IGST Rate"),
    _money("igst_tax", "IGST Amount"),
    _money("cgst_rate", "CGST Rate"),
    _money("cgst_tax", "CGST Amount"),
    _money("sgst_rate", "SGST (or UTGST) Rate"),
    _money("sgst_tax", "SGST (or UTGST) Amount"),
)

SALES_FIELDS = (
    _text("seller_gstin", "Seller GSTIN"),
    _text("order_id", "Order ID", required=False),
    _text("order_item_id", "Order Item ID"),
    _text("sku", "SKU", required=False),
    _text("hsn", "HSN Code", required=False),
    _text("event_type", "Event Type"),
    _text("event_subtype", "Event Sub Type"),
    _stamp("order_date", "Order Date"),
    _stamp("order_approval_date", "Order Approval Date"),
    FieldSpec("quantity", ("Item Quantity",), FieldKind.decimal, required=False),
    _text("ship_from_state", "Order Shipped From (State)", required=False),
    _text("ship_to_state", "Customer's Delivery State", required=False),
    _money("shipping_charges", "Shipping Charges"),
    _money("taxable_value", TAXABLE),
    _money("invoice_amount", "Buyer Invoice Amount"),
    _text("buyer_invoice_id", "Buyer Invoice ID", required=False),
    _stamp("buyer_invoice_date", "Buyer Invoice Date"),
    _money("tcs_total", "Total TCS Deducted"),
    *TAX,
)
# One sale item is one row per event: the same item may be sold, cancelled, returned.
SALES_DEDUP = ("seller_gstin", "order_item_id", "event_type", "event_subtype")

CASHBACK_FIELDS = (
    _text("seller_gstin", "Seller GSTIN"),
    _text("document_type", "Document Type"),
    _text("document_subtype", "Document Sub Type", required=False),
    _text("note_no", "Credit Note ID/ Debit Note ID"),
    _text("order_item_id", "Order Item ID", required=False, key_blank_ok=True),
    _money("invoice_amount", "Invoice Amount"),
    _stamp("invoice_date", "Invoice Date"),
    _money("taxable_value", "Taxable Value"),
    *TAX,
)
CASHBACK_DEDUP = ("seller_gstin", "note_no", "order_item_id")


def _zero(*values) -> bool:
    return all(v is None or v == 0 for v in values)


def _rate_out_of_range(n) -> bool:
    return any(n.get(k) is not None and (n[k] < 0 or n[k] > PERCENT) for k in ("igst_rate", "cgst_rate", "sgst_rate"))


class FlipkartSalesReader(HeaderReader):
    id = "flipkart_sales_v1"
    section = "flipkart"
    report_type = "orders"
    coverage_field = "order_approval_date"  # for the coverage view only; not the return period (CA item 1)

    def __init__(self):
        super().__init__(
            entry=r"Sales Report.*\.xlsx",
            markers=("Seller GSTIN", "Order Item ID", "Event Type", "Event Sub Type", "HSN Code", TAXABLE),
            gstin_header="Seller GSTIN",
            sheet=SALES_SHEET,
        )

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace="flipkart",
            report_type="orders",
            version="1",
            fields=SALES_FIELDS,
            dedup_key=SALES_DEDUP,
            verified=False,
            notes="Flipkart Sales Report sheet; headers from platform-reader-spec section 3, unchecked against a real file.",
        )

    def classify(self, row):
        n = row.normalized or {}
        if n.get("event_type") not in SALE_EVENTS or n.get("event_subtype") not in SALE_SUBTYPES:
            return StagedRowStatus.held, "unknown_txn_type"
        amounts = (n.get("invoice_amount"), n.get("taxable_value"), n.get("igst_tax"), n.get("cgst_tax"), n.get("sgst_tax"))
        if n["event_subtype"] in CANCELLATIONS:
            if _zero(*amounts):
                return StagedRowStatus.skipped_zero, None
            return StagedRowStatus.held, "sanity"  # a cancellation carrying value is not something we place
        if not n.get("hsn"):
            return StagedRowStatus.held, "blank_hsn"
        if n.get("quantity") is None:
            return StagedRowStatus.held, "blank_qty"
        if not n.get("ship_to_state"):
            return StagedRowStatus.held, "unknown_state"
        if _rate_out_of_range(n):
            return StagedRowStatus.held, "sanity"
        igst = not _zero(n.get("igst_rate"), n.get("igst_tax"))
        local = not _zero(n.get("cgst_rate"), n.get("sgst_rate"), n.get("cgst_tax"), n.get("sgst_tax"))
        if igst and local:
            return StagedRowStatus.held, "sanity"
        return None


class FlipkartCashbackReader(HeaderReader):
    id = "flipkart_cashback_v1"
    section = "flipkart"
    report_type = "cashback"
    coverage_field = "invoice_date"

    def __init__(self):
        super().__init__(
            entry=r"Sales Report.*\.xlsx",
            markers=("Seller GSTIN", "Document Type", "Credit Note ID/ Debit Note ID"),
            gstin_header="Seller GSTIN",
            sheet=CASHBACK_SHEET,
        )

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace="flipkart",
            report_type="cashback",
            version="1",
            fields=CASHBACK_FIELDS,
            dedup_key=CASHBACK_DEDUP,
            verified=False,
            notes="Flipkart Cash Back Report sheet; headers from platform-reader-spec section 3, unchecked against a real file.",
        )

    def classify(self, row):
        return StagedRowStatus.held, "cashback_adjustment"  # every row: the CA decides how these enter GSTR-1
