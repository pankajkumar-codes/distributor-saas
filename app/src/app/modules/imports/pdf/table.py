"""An extraction as the Excel template's table (R1-M6 S1), so the staging and review pipeline reads a PDF's
invoices exactly as it reads the seller's Excel. One row per line; an invoice with no readable line yields one
row with its document fields only, so the seller sees it and fixes it instead of it vanishing."""

import hashlib

from ..parsing import SourceTable
from ..readers.own_excel import COLUMNS
from .interface import ExtractedInvoice

SHEET = "PDF"
UNCLEAR_HEADER = "Unclear fields"  # names only (never values): the fields the reader could not read
_HEADERS = [c.header for c in COLUMNS] + [UNCLEAR_HEADER]


def to_table(invoices: tuple[ExtractedInvoice, ...], *, filename: str, pdf: bytes) -> SourceTable:
    rows = [list(_HEADERS)]
    for inv in invoices:
        for line in inv.lines or (None,):
            cells = {
                "Seller GSTIN": inv.seller_gstin, "Document type": inv.doc_type, "Document number": inv.doc_number,
                "Document date": inv.doc_date, "Original invoice number": inv.original_number,
                "Buyer GSTIN": inv.buyer_gstin, "Place of supply": inv.place_of_supply,
                "Invoice total": inv.invoice_total,
            }
            unclear = set(inv.unclear) | (set(line.unclear) if line is not None else set())
            cells[UNCLEAR_HEADER] = ", ".join(sorted(unclear))
            if line is not None:
                cells.update({"HSN": line.hsn, "Quantity": line.quantity, "Unit": line.unit,
                              "Taxable value": line.taxable_value, "GST rate %": line.gst_rate, "IGST": line.igst,
                              "CGST": line.cgst, "SGST/UTGST": line.sgst, "Cess": line.cess})
            rows.append([cells.get(h) or "" for h in _HEADERS])
    return SourceTable(filename=filename, checksum_sha256=hashlib.sha256(pdf).hexdigest(), sheet=SHEET, rows=rows)
