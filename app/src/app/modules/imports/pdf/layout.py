"""PDF to visual rows of text cells, with the caps for untrusted input (R1-M6 S1).

Uses pdfminer.six (MIT) on the page's text layer only. It never follows a link, an embedded file, a script
or an external reference: pdfminer does not execute anything, and annotations and attachments are never read.
An encrypted PDF is refused, however it was encrypted. Per page the characters are counted before anything is
kept, and the clock is checked between pages.
"""

import io
import logging
import time
from dataclasses import dataclass

from pdfminer.layout import LAParams, LTChar, LTContainer
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.converter import PDFPageAggregator

from .interface import Limits, PdfRefused

# pdfminer logs the raw tokens it parses at DEBUG; a value from an invoice must never reach a log.
logging.getLogger("pdfminer").setLevel(logging.ERROR)

CELL_GAP = 0.6  # float-ok: page geometry in points, never money. A gap wider than this many font sizes starts a cell
LINE_TOLERANCE = 0.45  # float-ok: page geometry. Characters whose vertical centres are within this many font sizes share a line


@dataclass(frozen=True)
class Cell:
    text: str
    x0: float  # float-ok: page geometry in points, never money
    x1: float  # float-ok: page geometry in points, never money


Row = list[Cell]


def read_rows(pdf: bytes, limits: Limits) -> list[list[Row] | None]:
    """One entry per page: its rows top to bottom, or None for a page with no text at all."""
    if not pdf.lstrip(b"\x00 \r\n\t")[:5] == b"%PDF-":
        raise PdfRefused("not_a_pdf")
    deadline = time.monotonic() + limits.max_seconds
    try:
        doc = PDFDocument(PDFParser(io.BytesIO(pdf)))
        if doc.encryption is not None:
            raise PdfRefused("encrypted")
        rsrc = PDFResourceManager()
        agg = PDFPageAggregator(rsrc, laparams=LAParams())
        interp = PDFPageInterpreter(rsrc, agg)
        pages: list[list[Row] | None] = []
        for number, page in enumerate(PDFPage.create_pages(doc), start=1):
            if number > limits.max_pages:
                raise PdfRefused("too_many_pages")
            if time.monotonic() > deadline:
                raise PdfRefused("too_slow")
            interp.process_page(page)
            pages.append(_rows(agg.get_result(), limits.max_chars_per_page))
    except PdfRefused:
        raise
    except RecursionError:
        raise PdfRefused("unreadable") from None
    except Exception:  # pdfminer raises many kinds for broken files; none of them may carry file text out
        raise PdfRefused("unreadable") from None
    if not pages:
        raise PdfRefused("unreadable")
    return pages


def _chars(layout, cap: int) -> list[LTChar]:
    found: list[LTChar] = []
    stack = [layout]
    while stack:
        item = stack.pop()
        if isinstance(item, LTChar):
            found.append(item)
            if len(found) > cap:
                raise PdfRefused("too_complex")
        elif isinstance(item, LTContainer):
            stack.extend(item)
    return found


def _rows(layout, cap: int) -> list[Row] | None:
    chars = [c for c in _chars(layout, cap) if c.get_text().strip() or c.get_text() == " "]
    if not any(c.get_text().strip() for c in chars):
        return None
    chars.sort(key=lambda c: (-(c.y0 + c.y1) / 2, c.x0))
    lines: list[list[LTChar]] = []
    for c in chars:
        mid = (c.y0 + c.y1) / 2
        if lines and abs(_mid(lines[-1][0]) - mid) <= LINE_TOLERANCE * max(c.size, 1):
            lines[-1].append(c)
        else:
            lines.append([c])
    rows = []
    for line in lines:
        line.sort(key=lambda c: c.x0)
        cells: list[Cell] = []
        text, x0, x1, size = "", None, 0.0, 1.0  # float-ok: page geometry in points, never money
        for c in line:
            ch = c.get_text()
            if x0 is not None and c.x0 - x1 > CELL_GAP * max(size, 1):
                cells.append(Cell(text.strip(), x0, x1))
                text, x0 = "", None
            if x0 is None:
                x0 = c.x0
            text += ch
            x1, size = c.x1, c.size
        if x0 is not None and text.strip():
            cells.append(Cell(text.strip(), x0, x1))
        cells = [c for c in cells if c.text]
        if cells:
            rows.append(cells)
    return rows


def _mid(c: LTChar) -> float:  # float-ok: page geometry in points, never money
    return (c.y0 + c.y1) / 2
