"""The seller's own sales invoices read from PDF (R1-M6 slice 2b). The PDF reader (`imports/pdf`) turns each PDF into
a table with the Excel template's headers plus one more column, `Unclear fields`, naming the fields it could not read.
This reader is the Excel reader's profile and hold rules for that table, with one more hold first: a row whose detail
could not be read is `pdf_unclear`, never guessed. It is registered for its own section and its own report type, so
the same document in the Excel and in a PDF are two runs that the cross-check (slice 3) compares, not one document
that "changed".

Verified false until the owner has run the local checker on his own PDFs (refdata `imports.profile.own_invoices_pdf_v1`).
"""

import dataclasses

from ..models import StagedRowStatus
from ..parsing import FieldSpec, MappingProfile
from ..pdf.table import SHEET, UNCLEAR_HEADER
from .own_excel import COLUMNS, DEDUP, OwnExcelReader


class OwnPdfReader(OwnExcelReader):
    id = "own_invoices_pdf_v1"
    section = "own_invoices_pdf"
    report_type = "invoices_pdf"

    def __init__(self):
        super().__init__()
        self.sheet = SHEET  # the table the PDF reader makes is named for its source

    def profile(self) -> MappingProfile:
        base = super().profile()
        return dataclasses.replace(
            base, report_type=self.report_type, version="1",
            fields=tuple(c.spec for c in COLUMNS) + (FieldSpec("pdf_unclear", (UNCLEAR_HEADER,), required=False),),
            dedup_key=DEDUP,
            notes="Own sales invoices read from PDF (R1-M6); one row per invoice line.")

    def classify(self, row, context=None):
        if (row.normalized or {}).get("pdf_unclear"):
            return StagedRowStatus.held, "pdf_unclear"
        return super().classify(row, context)
