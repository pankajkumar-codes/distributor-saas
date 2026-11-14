"""The seller's own sales invoices, typed into our Excel template (R1-M5; BRD GF-14).

The layout is ours: one row per invoice line on a sheet named `Invoices` (or a CSV with the same
headers). `COLUMNS` below is the single list both this reader and the template download are built from,
so the two cannot drift. It still ships unverified (refdata `imports.profile.own_invoices_excel_v1.verified`
is false) until the owner has filled one real month and run the local checker.

What the reader does: reads each row as typed (signed amounts, the rate as the number typed, never
inferred or checked against a rate table), keeps only the buyer's GSTIN of the buyer's details (the
template has no name or address column, and any column a seller adds is not stored), and holds what it
cannot place: an unknown document type, a document number that does not fit the usual shape, a credit or
debit note with no original invoice number, a blank HSN, quantity, unit or place of supply, a place of
supply that is not a state code or name in refdata, and a row whose tax columns contradict each other
(IGST together with CGST or SGST; CGST and SGST that differ). A rate of 0 is kept as typed.

What it does not do (R1-M7 does, see the plan's conditions): check that taxable value times rate equals
the tax, check intra- against inter-state from the place of supply, check an HSN's length for the
seller's turnover, or decide a period. Exports, SEZ supplies, reverse charge, advances, nil-rated or
exempt marking and an e-commerce operator's GSTIN have no column: they are not supported yet.

Row identity (D-053): seller GSTIN, document type, document number and the line's position within that
document in the file. The same document in a later file with other values, lines in another order, or
the same number reused in another financial year all show as `changed` for the seller to accept or skip,
never as a silent second copy.
"""

from dataclasses import dataclass
from decimal import Decimal

from ..models import StagedRowStatus
from ..parsing import FieldKind, FieldSpec, MappingProfile
from .base import HeaderReader

SHEET = "Invoices"
PERCENT = Decimal(100)
DATES = ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S")  # typed text, or a real Excel date cell
DOC_TYPES = {"invoice": "Invoice", "credit note": "Credit note", "debit note": "Debit note"}
NOTES = ("credit note", "debit note")
NUMBER_PATTERN_KEY = "imports.own_invoices.document_number_pattern"


@dataclass(frozen=True)
class Column:
    """One template column: its header, the field it fills, and the one-line help the template shows."""

    header: str
    spec: FieldSpec
    help: str


def _text(name, header, *, required=False, **kw):
    return FieldSpec(name, (header,), required=required, **kw)


def _money(name, header, *, required=False):
    return FieldSpec(name, (header,), FieldKind.decimal, required=required)


def _date(name, header, *, required=False):
    return FieldSpec(name, (header,), FieldKind.date, required=required, formats=DATES)


COLUMNS = (
    Column("Seller GSTIN", _text("seller_gstin", "Seller GSTIN", required=True, key_fold=True),
           "Your own GSTIN, on every row."),
    Column("Document type", _text("doc_type", "Document type", required=True, key_fold=True),
           "Invoice, Credit note or Debit note."),
    Column("Document number", _text("doc_number", "Document number", required=True, key_fold=True),
           "Exactly as printed on the document."),
    Column("Document date", _date("doc_date", "Document date", required=True), "DD-MM-YYYY."),
    Column("Original invoice number", _text("original_number", "Original invoice number"),
           "For a credit or debit note: the invoice it corrects. Leave blank on an invoice."),
    Column("Original invoice date", _date("original_date", "Original invoice date"),
           "For a credit or debit note: that invoice's date."),
    Column("Buyer GSTIN", _text("buyer_gstin", "Buyer GSTIN"),
           "Only when the buyer is GST-registered. Leave blank otherwise."),
    Column("Place of supply", _text("place_of_supply", "Place of supply"),
           "The state's name or its two-digit GST code."),
    Column("HSN", _text("hsn", "HSN"), "The HSN or SAC code, digits only."),
    Column("Quantity", FieldSpec("quantity", ("Quantity",), FieldKind.decimal, required=False), "A number."),
    Column("Unit", _text("unit", "Unit"), "The unit as on the invoice, for example PCS or NOS."),
    Column("Taxable value", _money("taxable_value", "Taxable value", required=True),
           "The line's value before tax, after discount."),
    Column("GST rate %", _money("gst_rate", "GST rate %", required=True),
           "The rate printed on your document, as a plain number without a % sign."),
    Column("IGST", _money("igst", "IGST"), "The tax amounts as on the document. Leave a column blank if not charged."),
    Column("CGST", _money("cgst", "CGST"), ""),
    Column("SGST/UTGST", _money("sgst", "SGST/UTGST"), ""),
    Column("Cess", _money("cess", "Cess"), ""),
    Column("Invoice total", _money("invoice_total", "Invoice total"),
           "The document's total, repeated on each of its lines."),
)
MARKERS = ("Seller GSTIN", "Document type", "Document number", "Document date", "Taxable value", "GST rate %")
DEDUP = ("seller_gstin", "doc_type", "doc_number", "line")


def _nonzero(value) -> bool:
    return value is not None and value != 0


class OwnExcelReader(HeaderReader):
    id = "own_invoices_excel_v1"
    section = "own_invoices_excel"
    report_type = "invoices"
    coverage_field = "doc_date"  # the month label for the coverage view only (D-052)
    any_sheet = True  # a CSV, or a workbook whose one sheet was renamed, is still read by its headers
    refdata_keys = (NUMBER_PATTERN_KEY,)  # the upload pipeline reads these and the state list for `classify`

    def __init__(self):
        super().__init__(entry=r"(?!)", markers=MARKERS, gstin_header="Seller GSTIN", sheet=SHEET)  # no zip entries

    def profile(self) -> MappingProfile:
        return MappingProfile(
            marketplace="own_invoices",
            report_type=self.report_type,
            version="1",
            fields=tuple(c.spec for c in COLUMNS),
            dedup_key=DEDUP,
            occurrence_field="line",
            occurrence_by_position=True,
            verified=False,  # our own layout, still unchecked against a month a seller really filled in
            notes="Own sales invoices template (R1-M5); one row per invoice line.",
        )

    def classify(self, row, context=None):
        n = row.normalized or {}
        context = context or {}
        kind = " ".join(str(n.get("doc_type") or "").split()).casefold()
        if kind not in DOC_TYPES:
            return StagedRowStatus.held, "unknown_txn_type"
        pattern = context.get(NUMBER_PATTERN_KEY)
        if pattern is not None and not pattern.fullmatch(str(n.get("doc_number") or "").strip()):
            return StagedRowStatus.held, "number_format"
        if kind in NOTES and not n.get("original_number"):
            return StagedRowStatus.held, "missing_original"
        if not n.get("hsn"):
            return StagedRowStatus.held, "blank_hsn"
        if n.get("quantity") is None:
            return StagedRowStatus.held, "blank_qty"
        if not n.get("unit"):
            return StagedRowStatus.held, "blank_uqc"
        place = " ".join(str(n.get("place_of_supply") or "").split()).casefold()
        states = context.get("states")
        if not place or (states is not None and place not in states):
            return StagedRowStatus.held, "unknown_state"
        rate = n.get("gst_rate")
        if rate is not None and (rate < 0 or rate > PERCENT):
            return StagedRowStatus.held, "sanity"
        if _nonzero(n.get("igst")) and (_nonzero(n.get("cgst")) or _nonzero(n.get("sgst"))):
            return StagedRowStatus.held, "sanity"  # one line is inter-state or intra-state, not both
        if (n.get("cgst") or 0) != (n.get("sgst") or 0):
            return StagedRowStatus.held, "sanity"  # the two halves of an intra-state tax are equal
        return None
