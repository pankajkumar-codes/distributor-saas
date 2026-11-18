"""The free OCR reader for scans and photos saved as PDF (R1-M6 S4b). Local and CI only for now.

Pages are rasterised with poppler (`pdftoppm`) and read with Tesseract, both run as separate programs with an
empty environment, a scratch directory, a time limit and a bounded answer. Each recognised word becomes a cell on
a row, exactly the shape the text-layer reader builds from a PDF's own text, so the same field rules, hold rules,
review screen and Excel cross-check apply unchanged. A word with a digit that the engine is not sure of is dropped, never kept
as a guess, so the field it would have filled stays blank and is named in `unclear`; the seller types it in.

Nothing here is deployed: the Lambda package has no room for these programs (docs/IMPORTS.md), so in R1 a scan is
held as `pdf_unclear` and nothing selects this reader in production. It never logs a value it read.
"""

import csv
import io
import os
import re
import shutil
import subprocess
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from .extract import assemble, read_page
from .interface import Limits, PdfRefused, ReadResult
from .layout import CELL_GAP, LINE_TOLERANCE, Cell, Row

LONG_SIDE_PIXELS = 2400  # a page is scaled so its longer side is this many pixels, whatever its paper size
MIN_CONFIDENCE = 60  # float-ok: Tesseract's 0 to 100 word confidence; a word with a digit below it is dropped, not guessed
MIN_LABEL_CONFIDENCE = 30  # float-ok: a word with no digit is a label or a name, which cannot put a wrong figure in a field
MAX_TSV_BYTES = 2_000_000
WORD_LEVEL = "5"  # in Tesseract's TSV, level 5 is a word
GAP_SCALE = 1.4  # float-ok: a word's pixel height is a little under its font size, so the cell gap rule is widened to match


class OcrUnavailable(RuntimeError):
    """pdftoppm or tesseract is not installed here. Not a refusal of the file: the job is retried elsewhere."""


class OcrReader:
    id = "pdf_ocr_v1"

    def __init__(self, hsn_pattern: re.Pattern):
        self._hsn = hsn_pattern
        self._pdftoppm = shutil.which("pdftoppm")
        self._tesseract = shutil.which("tesseract")

    @property
    def available(self) -> bool:
        return bool(self._pdftoppm and self._tesseract)

    def read(self, pdf: bytes, limits: Limits) -> ReadResult:
        if not self.available:
            raise OcrUnavailable("pdftoppm and tesseract are needed")
        if not pdf.lstrip(b"\x00 \r\n\t")[:5] == b"%PDF-":
            raise PdfRefused("not_a_pdf")
        deadline = time.monotonic() + limits.max_seconds
        with tempfile.TemporaryDirectory() as scratch:
            src = Path(scratch, "in.pdf")
            src.write_bytes(pdf)
            self._run([self._pdftoppm, "-gray", "-png", "-scale-to", str(LONG_SIDE_PIXELS), "-l",
                       str(limits.max_pages + 1), str(src), str(Path(scratch, "p"))], scratch, deadline)
            images = sorted(Path(scratch).glob("p-*.png"))
            if not images:
                raise PdfRefused("unreadable")
            if len(images) > limits.max_pages:
                raise PdfRefused("too_many_pages")
            pages: list[list[Row] | None] = []
            for image in images:
                tsv = self._run([self._tesseract, str(image), "stdout", "--psm", "6", "tsv"], scratch, deadline)
                pages.append(_rows(tsv, limits.max_chars_per_page))
        facts = [read_page(n, rows, self._hsn) for n, rows in enumerate(pages, start=1) if rows is not None]
        unreadable = tuple(n for n, rows in enumerate(pages, start=1) if rows is None)
        return ReadResult(tuple(assemble(facts, limits.max_documents)), unreadable)

    def _run(self, argv: list[str], scratch: str, deadline: float) -> bytes:  # float-ok: a clock time in seconds
        left = deadline - time.monotonic()
        if left <= 0:
            raise PdfRefused("too_slow")
        try:
            done = subprocess.run(
                argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=scratch, timeout=left, check=False,
                # No secret reaches these programs; Tesseract is kept to one thread so the child stays small.
                env={"PATH": os.path.dirname(argv[0]), "OMP_THREAD_LIMIT": "1", "LC_ALL": "C"},
            )
        except subprocess.TimeoutExpired:
            raise PdfRefused("too_slow") from None
        except OSError:
            raise OcrUnavailable("the OCR programs could not be started") from None
        if done.returncode != 0 or len(done.stdout) > MAX_TSV_BYTES:
            raise PdfRefused("unreadable" if done.returncode else "too_complex")
        return done.stdout


def _rows(tsv: bytes, cap: int) -> list[Row] | None:
    """Words from Tesseract's TSV to rows of cells; None when the page has no word it is sure of."""
    words = []  # (mid_y, height, x0, x1, text)
    for f in csv.DictReader(io.StringIO(tsv.decode("utf-8", "replace")), delimiter="\t", quoting=csv.QUOTE_NONE):
        try:
            conf, left, top = Decimal(f["conf"]), int(f["left"]), int(f["top"])
            width, height = int(f["width"]), int(f["height"])
        except (KeyError, TypeError, ValueError, ArithmeticError):
            continue
        text = (f.get("text") or "").strip()
        floor = MIN_CONFIDENCE if any(ch.isdigit() for ch in text) else MIN_LABEL_CONFIDENCE
        if f.get("level") == WORD_LEVEL and text and conf >= floor and height > 0 and width > 0:
            words.append((top + height / 2, height, left, left + width, text))
            if len(words) > cap:
                raise PdfRefused("too_complex")
    if not words:
        return None
    words.sort(key=lambda w: (w[0], w[2]))
    lines: list[list[tuple]] = []
    for w in words:
        if lines and abs(lines[-1][0][0] - w[0]) <= LINE_TOLERANCE * max(w[1], 1):
            lines[-1].append(w)
        else:
            lines.append([w])
    rows: list[Row] = []
    for line in lines:
        line.sort(key=lambda w: w[2])
        cells: list[Cell] = []
        text, x0, x1, size = "", None, 0.0, 1.0  # float-ok: page geometry in pixels, never money
        for _, h, a, b, t in line:
            # A word's pixel height is a little under the font size, so the gap rule is scaled to match.
            if x0 is not None and a - x1 > CELL_GAP * max(size, 1) * GAP_SCALE:
                cells.append(Cell(text, x0, x1))
                text, x0 = "", None
            if x0 is None:
                x0 = a
                text = t
            else:
                text += " " + t
            x1, size = b, h
        if x0 is not None:
            cells.append(Cell(text, x0, x1))
        rows.append(cells)
    return rows
