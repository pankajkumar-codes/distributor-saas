"""Amazon's Merchant Tax Report readers (R1-M4 S1; platform-reader-spec section 2): the monthly
`MTR_B2C-...csv` and `MTR_B2B-...csv` files, usually inside a zip, UTF-8 with a BOM.

Written from the spec's header list, not yet from a checked sample: the profiles ship unverified and
refdata `imports.profile.<id>.verified` is false, so every run carries the "layout unchecked" note
until a real file confirms the headers. Only headers the spec names exactly are read; the shipping,
gift-wrap and TCS columns are not (their exact names are not in the spec, and the shipping value basis
is open with the CA).

What a row means is the build's job (R1-M7). This reader reads each row as written (signed amounts, a
rate written as a fraction stored as a percent), keeps the file's own invoice and credit note numbers,
and holds what it can't place: an unknown transaction type, a missing HSN, quantity or ship-to state, a
refund with no credit note number, a row that charges both IGST and CGST or SGST. A row with no value at
all (a cancel, a free replacement) is shown as zero-value and left out of the return, never dropped.
"""

from decimal import Decimal

from ..models import StagedRowStatus
from ..parsing import FieldKind, FieldSpec, MappingProfile
from .base import HeaderReader

PERCENT = Decimal(100)
DATETIME = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

# The transaction types the spec saw (Amazon documents more; the reader holds any other).
KNOWN_TYPES = ("Shipment", "Cancel", "Refund", "FreeReplacement")
CORE = ("Seller Gstin", "Transaction Type", "Shipment Item Id", "Hsn/sac", "Tax Exclusive Gross", "Invoice Amount")
B2B_ONLY = ("Customer Bill To Gstid",)


def _text(name, *headers, **kw):
    return FieldSpec(name, headers, **kw)


def _money(name, *headers):
    return FieldSpec(name, headers, FieldKind.decimal, required=False)


def _rate(name, *headers):
    return FieldSpec(name, headers, FieldKind.decimal, required=False, scale=PERCENT)  # 0.18 -> 18.00


def _stamp(name, *headers):
    return FieldSpec(name, headers, FieldKind.datetime, required=False, formats=DATETIME)


COMMON = (
    _text("seller_gstin", "Seller Gstin"),
    _text("invoice_number", "Invoice Number", required=False),
    _stamp("invoice_date", "Invoice Date"),
    _text("txn_type", "Transaction Type"),
    _text("order_id", "Order Id", required=False),
    _text("shipment_id", "Shipment Id", required=False),
    _text("shipment_item_id", "Shipment Item Id"),
    _stamp("shipment_date", "Shipment Date"),
    _stamp("order_date", "Order Date"),
    FieldSpec("quantity", ("Quantity",), FieldKind.decimal, required=False),
    _text("hsn", "Hsn/sac", required=False),
    _text("ship_to_state", "Ship To State", required=False),
    _text("ship_from_state", "Ship From State", required=False),
    _money("invoice_amount", "Invoice Amount"),
    _money("taxable_value", "Tax Exclusive Gross"),
    _money("total_tax", "Total Tax Amount"),
    _rate("cgst_rate", "Cgst Rate"),
    _rate("sgst_rate", "Sgst Rate"),
    _rate("utgst_rate", "Utgst Rate"),
    _rate("igst_rate", "Igst Rate"),
    _rate("cess_rate", "Compensatory Cess Rate"),
    _money("cgst_tax", "Cgst Tax"),
    _money("sgst_tax", "Sgst Tax"),
    _money("utgst_tax", "Utgst Tax"),
    _money("igst_tax", "Igst Tax"),
    _money("cess_tax", "Compensatory Cess Tax", "Compensatory Cess Tax Amount"),  # the spelling drifted once
    _money("shipping_amount", "Shipping Amount"),
    _money("gift_wrap_amount", "Gift Wrap Amount"),
    _money("item_promo_discount", "Item Promo Discount"),
    _text("fulfillment_channel", "Fulfillment Channel", required=False),
    _text("payment_method", "Payment Method Code", required=False),
    _text("credit_note_no", "Credit Note No", required=False, key_blank_ok=True),
    _stamp("credit_note_date", "Credit Note Date"),
)
B2B_FIELDS = (
    _text("buyer_gstin", "Customer Bill To Gstid", required=False),
    _text("ship_to_gstin", "Customer Ship To Gstid", required=False),
    _text("irn", "Irn Number", required=False),
    _text("irn_status", "Irn Filing Status", required=False),
    _stamp("irn_date", "Irn Date"),
    _text("irn_error", "Irn Error Code", required=False),
)
# One sale item is one row; a refund of it has the same Shipment Item Id with a credit note number.
DEDUP = ("seller_gstin", "shipment_item_id", "txn_type", "credit_note_no")


def _zero(*values) -> bool:
    return all(v is None or v == 0 for v in values)


class AmazonReader(HeaderReader):
    section = "amazon"

    def __init__(self, kind: str):
        self.kind = kind  # "b2c" or "b2b"
        self.id = f"amazon_mtr_{kind}_v1"
        self.report_type = f"mtr_{kind}"
        super().__init__(
            entry=rf"MTR_{kind.upper()}-.+\.csv",
            markers=CORE + (B2B_ONLY if kind == "b2b" else ()),
            excluded=B2B_ONLY if kind == "b2c" else (),
            gstin_header="Seller Gstin",
        )

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace="amazon",
            report_type=self.report_type,
            version="1",
            fields=COMMON + (B2B_FIELDS if self.kind == "b2b" else ()),
            dedup_key=DEDUP,
            verified=False,  # written from the spec; a real file must confirm the headers
            notes="Merchant Tax Report; headers from platform-reader-spec section 2, unchecked against a real file.",
        )

    def classify(self, row):
        n = row.normalized or {}
        kind = n.get("txn_type")
        if kind not in KNOWN_TYPES:
            return StagedRowStatus.held, "unknown_txn_type"
        amounts = (n.get("invoice_amount"), n.get("taxable_value"), n.get("total_tax"))
        if kind in ("Cancel", "FreeReplacement") and _zero(*amounts):
            return StagedRowStatus.skipped_zero, None
        if kind == "Cancel":
            return StagedRowStatus.held, "sanity"  # a cancel that carries value is not something we place
        if not n.get("hsn"):
            return StagedRowStatus.held, "blank_hsn"
        if n.get("quantity") is None:
            return StagedRowStatus.held, "blank_qty"
        if not n.get("ship_to_state"):
            return StagedRowStatus.held, "unknown_state"
        rates = [n.get(k) for k in ("cgst_rate", "sgst_rate", "utgst_rate", "igst_rate", "cess_rate")]
        if any(r is not None and (r > PERCENT or r < 0) for r in rates):
            return StagedRowStatus.held, "sanity"  # a rate over 100% or below 0: the scaling guess was wrong
        igst = not _zero(n.get("igst_rate"), n.get("igst_tax"))
        local = not _zero(n.get("cgst_rate"), n.get("sgst_rate"), n.get("utgst_rate"), n.get("cgst_tax"),
                          n.get("sgst_tax"), n.get("utgst_tax"))
        if igst and local:
            return StagedRowStatus.held, "sanity"  # inter-state and intra-state tax on one row
        if kind == "Refund" and not n.get("credit_note_no"):
            return StagedRowStatus.held, "sanity"  # a refund is a credit note: it must carry its number
        return None
