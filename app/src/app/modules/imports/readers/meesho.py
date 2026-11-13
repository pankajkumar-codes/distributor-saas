"""Meesho's monthly TCS reports (R1-M4 S3; platform-reader-spec section 4): `tcs_sales.xlsx` and
`tcs_sales_return.xlsx`, usually together in a zip, each with one sheet named after the supplier id.

Written from the spec's header list, not yet from a checked sample: both profiles ship unverified and
refdata `imports.profile.<id>.verified` is false, so every run carries the "layout unchecked" note.
Personal columns are not mapped. The file's own name tells a sale from a return (`transaction_type` is
empty in the samples); the return file has `cancel_return_date` and the sales file does not.

Meesho has no stable row id, so the dedupe key is the spec's composite (seller GSTIN, sub order number,
order date, quantity, taxable value, invoice value) plus a counter for identical rows in one file; the
report type (orders or returns) is the file kind. Rows with the same key and different values are never
merged or dropped: they are all flagged as conflicts. The cost is that a re-issued file with a corrected
value looks like new rows (D-051).

A row with quantity 0 and a value is a price adjustment, not a sale: it is kept and held as
`price_adjustment` for the CA. Missing dates are the text `null`. Rates are percent text (18.00) and are
kept as written; a rate outside 0 to 100 holds the row. Nothing here splits tax into CGST/SGST/IGST: the
file has one `tax_amount`, and the build derives the split from place of supply.
"""

from decimal import Decimal

from ..models import StagedRowStatus
from ..parsing import FieldKind, FieldSpec, MappingProfile
from .base import HeaderReader

PERCENT = Decimal(100)
DATETIME = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S")
NULL = ("null",)

CORE = ("gstin", "sub_order_num", "hsn_code", "quantity", "total_taxable_sale_value", "total_invoice_value")


def _text(name, *headers, **kw):
    return FieldSpec(name, headers, blank_tokens=NULL, **kw)


def _money(name, *headers, **kw):
    return FieldSpec(name, headers, FieldKind.decimal, required=False, blank_tokens=NULL, **kw)


def _stamp(name, *headers, **kw):
    return FieldSpec(name, headers, FieldKind.datetime, required=False, formats=DATETIME, blank_tokens=NULL, **kw)


COMMON = (
    _text("gstin", "gstin"),
    _text("sub_order_num", "sub_order_num"),
    _stamp("order_date", "order_date", key_blank_ok=True),
    _text("hsn", "hsn_code", required=False),
    FieldSpec("quantity", ("quantity",), FieldKind.decimal, required=False, key_blank_ok=True, blank_tokens=NULL),
    _money("gst_rate", "gst_rate"),
    FieldSpec("taxable_value", ("total_taxable_sale_value",), FieldKind.decimal, required=False, key_blank_ok=True,
              blank_tokens=NULL),
    _money("tax_amount", "tax_amount"),
    FieldSpec("invoice_value", ("total_invoice_value",), FieldKind.decimal, required=False, key_blank_ok=True,
              blank_tokens=NULL),
    _money("taxable_shipping", "taxable_shipping"),
    _text("ship_to_state", "end_customer_state_new", required=False),
    _stamp("manifest_date", "manifest_date"),
    _text("transaction_type", "transaction_type", required=False),
    _text("eco_gstin", "eco_tcs_gstin", required=False),
    _text("financial_year", "financial_year", required=False),
    _text("month_number", "month_number", required=False),
    _text("supplier_id", "supplier_id", required=False),
)
RETURN_ONLY = (_stamp("cancel_return_date", "cancel_return_date"),)

# The spec's composite key, then the counter. The file kind is the run's report type.
DEDUP = ("gstin", "sub_order_num", "order_date", "quantity", "taxable_value", "invoice_value", "occurrence")


def _zero(*values) -> bool:
    return all(v is None or v == 0 for v in values)


class MeeshoReader(HeaderReader):
    section = "meesho"

    def __init__(self, kind: str):
        self.kind = kind  # "sales" or "returns"
        self.id = f"meesho_{kind}_v1"
        self.report_type = "orders" if kind == "sales" else "returns"
        is_return = kind == "returns"
        super().__init__(
            entry=r"tcs_sales_return\.xlsx" if is_return else r"tcs_sales\.xlsx",
            markers=CORE + (("cancel_return_date",) if is_return else ()),
            excluded=() if is_return else ("cancel_return_date",),
            gstin_header="gstin",
        )

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace="meesho",
            report_type=self.report_type,
            version="1",
            fields=COMMON + (RETURN_ONLY if self.kind == "returns" else ()),
            dedup_key=DEDUP,
            occurrence_field="occurrence",
            verified=False,
            notes="Meesho TCS report; headers from platform-reader-spec section 4, unchecked against a real file.",
        )

    def classify(self, row):
        n = row.normalized or {}
        if n.get("quantity") is None:
            return StagedRowStatus.held, "blank_qty"
        if n["quantity"] == 0:
            # No units: a price adjustment when it carries a value, nothing at all when it carries none.
            if _zero(n.get("taxable_value"), n.get("tax_amount"), n.get("invoice_value")):
                return StagedRowStatus.skipped_zero, None
            return StagedRowStatus.held, "price_adjustment"
        if not n.get("hsn"):
            return StagedRowStatus.held, "blank_hsn"
        if not n.get("ship_to_state"):
            return StagedRowStatus.held, "unknown_state"
        rate = n.get("gst_rate")
        if rate is not None and (rate < 0 or rate > PERCENT):
            return StagedRowStatus.held, "sanity"
        if any(v is not None and v < 0 for v in (n.get("taxable_value"), n.get("invoice_value"))):
            return StagedRowStatus.held, "sanity"  # units but a negative value: not a sale or a return we place
        if self.kind == "returns" and n.get("cancel_return_date") is None:
            return StagedRowStatus.held, "sanity"  # a return with no return date cannot be placed in a month
        return None
