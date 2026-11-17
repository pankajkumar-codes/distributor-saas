"""What an own-invoice PDF reader is, and what it hands back (R1-M6 S1).

The interface is the plug-in point for the free readers (text layer now, OCR in S4) and for a paid one
later (Bedrock, not built and not switched on: Pankaj's decision D2). A reader takes the bytes of one PDF
and returns the invoices it found, as the same fields the Excel template has, so staging, hold rules, the
review screen and the Excel cross-check need nothing of their own. A reader never touches the database or the
object store, never calls the network or any paid service, and never logs a value it read.

Principle: a field the reader is not sure of is left blank and named in `unclear`; it is never guessed. The
seller types it in on the review screen.
"""

from dataclasses import dataclass, field
from typing import Protocol


class PdfRefused(Exception):
    """The file cannot be used. `code` is what the upload keeps as its reject reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Limits:
    """Caps on untrusted input. The values are refdata (wired in S2), never literals in the reader."""

    max_pages: int
    max_chars_per_page: int
    max_documents: int
    max_seconds: int  # checked between pages: one page cannot be interrupted, so the page caps matter too


@dataclass(frozen=True)
class ExtractedLine:
    """One invoice line. Amounts and the quantity are plain decimal text as printed (commas removed)."""

    page: int
    hsn: str | None = None
    quantity: str | None = None
    unit: str | None = None
    taxable_value: str | None = None
    gst_rate: str | None = None
    igst: str | None = None
    cgst: str | None = None
    sgst: str | None = None
    cess: str | None = None
    unclear: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ExtractedInvoice:
    pages: tuple[int, ...]
    seller_gstin: str | None = None
    doc_type: str | None = None  # "Invoice", "Credit note" or "Debit note"
    doc_number: str | None = None
    doc_date: str | None = None  # DD-MM-YYYY
    original_number: str | None = None
    buyer_gstin: str | None = None
    place_of_supply: str | None = None
    invoice_total: str | None = None
    lines: tuple[ExtractedLine, ...] = ()
    unclear: frozenset[str] = frozenset()  # document fields not found or contradicting themselves


@dataclass(frozen=True)
class ReadResult:
    invoices: tuple[ExtractedInvoice, ...] = ()
    unreadable_pages: tuple[int, ...] = field(default=())  # pages with no text layer (a scan): OCR's job, S4


class InvoiceReader(Protocol):
    id: str

    def read(self, pdf: bytes, limits: Limits) -> ReadResult:
        """Raises PdfRefused for a file that must not be read (not a PDF, encrypted, over a cap, an
        ambiguous document split)."""
