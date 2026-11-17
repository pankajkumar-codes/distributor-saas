"""The free reader: the PDF's own text layer (R1-M6 S1). Pages with no text are reported, not guessed at;
reading them is the OCR reader's job (S4)."""

import re

from .extract import assemble, read_page
from .interface import Limits, ReadResult
from .layout import read_rows


class TextLayerReader:
    id = "pdf_text_v1"

    def __init__(self, hsn_pattern: re.Pattern):
        """`hsn_pattern`: refdata `hsn.pattern`, passed in by the caller so this reader stays free of the database."""
        self._hsn = hsn_pattern

    def read(self, pdf: bytes, limits: Limits) -> ReadResult:
        pages = read_rows(pdf, limits)
        facts = [read_page(n, rows, self._hsn) for n, rows in enumerate(pages, start=1) if rows is not None]
        unreadable = tuple(n for n, rows in enumerate(pages, start=1) if rows is None)
        return ReadResult(tuple(assemble(facts, limits.max_documents)), unreadable)
