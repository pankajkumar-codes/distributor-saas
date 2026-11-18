"""The OCR reader on synthetic scans: a page of a made-up invoice is drawn to pixels and wrapped in a PDF that has
no text layer. Skipped where pdftoppm or tesseract is not installed (CI installs them)."""

import os
import re
import shutil
import subprocess
import tempfile
import zlib
from pathlib import Path

import pytest

from app.modules.imports.pdf import Limits, PdfRefused, TextLayerReader, to_table
from app.modules.imports.pdf import ocr_reader
from app.modules.imports.pdf.extract import assemble, read_page
from app.modules.imports.pdf.ocr_reader import OcrReader, OcrUnavailable, _rows

from .fixtures.pdf import BUYER, SELLER, one_invoice

# Skipped on a machine without the two programs, but never in CI: there a missing program fails the tests.
pytestmark = pytest.mark.skipif(not (shutil.which("pdftoppm") and shutil.which("tesseract")) and not os.environ.get("CI"),
                                reason="pdftoppm and tesseract are not installed")
HSN = re.compile("^[0-9]{4,8}$")
LIMITS = Limits(max_pages=5, max_chars_per_page=5000, max_documents=10, max_seconds=60)


def _pgm(raw: bytes) -> tuple[int, int, bytes]:
    magic, w, h, _maxval, body = re.match(rb"(P5)\s+(\d+)\s+(\d+)\s+(\d+)\s(.*)", raw, re.S).groups()
    return int(w), int(h), body


def image_pdf(w: int, h: int, gray: bytes) -> bytes:
    """A one-page PDF holding only a grey picture and no text: what a scanner makes."""
    data = zlib.compress(gray)
    draw = b"q %d 0 0 %d 0 0 cm /Im Do Q" % (w, h)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R /Resources "
            b"<< /XObject << /Im 5 0 R >> >> >>" % (w, h),
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(draw), draw),
            b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 "
            b"/Filter /FlateDecode /Length %d >>\nstream\n" % (w, h, len(data)) + data + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def scan(data: bytes) -> bytes:
    """Rasterise a text PDF at 200 dpi and wrap the picture in a PDF with no text layer."""
    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.pdf").write_bytes(data)
        subprocess.run(["pdftoppm", "-r", "200", "-gray", "-f", "1", "-l", "1", str(Path(d, "a.pdf")),
                        str(Path(d, "s"))], check=True)
        w, h, gray = _pgm(next(Path(d).glob("s-*.pgm")).read_bytes())
    return image_pdf(w, h, gray)


def ocr(data):
    return OcrReader(HSN).read(data, LIMITS)


def test_a_scanned_invoice_reads_like_the_same_invoice_with_a_text_layer():
    original = one_invoice()
    assert TextLayerReader(HSN).read(scan(original), LIMITS).unreadable_pages == (1,)  # no text layer at all
    result = ocr(scan(original))
    assert result.unreadable_pages == ()
    (got,) = result.invoices
    (want,) = TextLayerReader(HSN).read(original, LIMITS).invoices
    assert (got.seller_gstin, got.buyer_gstin) == (SELLER, BUYER)
    for name in ("doc_type", "doc_number", "doc_date", "place_of_supply", "invoice_total"):
        assert getattr(got, name) == getattr(want, name), name
    assert got.lines[0].taxable_value == want.lines[0].taxable_value == "200.00"
    assert (got.lines[0].hsn, got.lines[0].gst_rate) == (want.lines[0].hsn, want.lines[0].gst_rate)


def test_a_blank_page_is_reported_unreadable_not_guessed():
    result = ocr(image_pdf(1200, 1600, b"\xff" * (1200 * 1600)))
    assert result.invoices == () and result.unreadable_pages == (1,)


def test_the_same_scan_read_twice_gives_the_same_result():
    data = scan(one_invoice())
    assert ocr(data) == ocr(data)


def test_a_word_the_engine_is_unsure_of_is_dropped_so_the_field_is_blank_and_unclear():
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    row = "5\t1\t1\t1\t1\t1\t%d\t%d\t%d\t%d\t%d\t%s"
    tsv = head.encode() + "\n".join([
        row % (10, 10, 60, 20, 95, "Invoice"), row % (80, 10, 60, 20, 95, "No:"), row % (150, 10, 60, 20, 20, "INV-9"),
    ]).encode()
    (cells,) = _rows(tsv, 100)
    assert [c.text for c in cells] == ["Invoice No:"]  # the 20-confidence word is gone, not guessed
    low_label = (row % (10, 10, 60, 20, 40, "Qty")).encode()  # a label with no digit is kept at 40
    assert [c.text for c in _rows(head.encode() + low_label, 100)[0]] == ["Qty"]
    assert _rows(head.encode() + (row % (1, 1, 5, 5, 10, "x")).encode(), 100) is None


def test_files_that_must_not_be_read_are_refused():
    with pytest.raises(PdfRefused) as e:
        ocr(b"not a pdf")
    assert e.value.code == "not_a_pdf"
    with pytest.raises(PdfRefused) as e:
        OcrReader(HSN).read(scan(one_invoice()), Limits(max_pages=0, max_chars_per_page=5000, max_documents=10,
                                                       max_seconds=60))
    assert e.value.code == "too_many_pages"
    with pytest.raises(PdfRefused) as e:
        OcrReader(HSN).read(scan(one_invoice()), Limits(max_pages=5, max_chars_per_page=5000, max_documents=10,
                                                       max_seconds=0))
    assert e.value.code == "too_slow"
    with pytest.raises(PdfRefused) as e:
        ocr(b"%PDF-1.4 garbage")
    assert e.value.code in ("unreadable", "too_slow")


def test_too_much_text_on_a_page_is_refused():
    with pytest.raises(PdfRefused) as e:
        OcrReader(HSN).read(scan(one_invoice()), Limits(max_pages=5, max_chars_per_page=10, max_documents=10,
                                                       max_seconds=60))
    assert e.value.code == "too_complex"


def test_without_the_programs_it_says_so_and_does_not_refuse_the_file(monkeypatch):
    monkeypatch.setattr(ocr_reader.shutil, "which", lambda name: None)
    with pytest.raises(OcrUnavailable):
        OcrReader(HSN).read(scan(one_invoice()), LIMITS)


def test_the_programs_get_no_environment_from_this_process(monkeypatch):
    seen = {}
    real = subprocess.run

    def spy(argv, **kw):
        seen.setdefault("env", []).append(kw["env"])
        return real(argv, **kw)

    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-leak")
    data = scan(one_invoice())
    monkeypatch.setattr(ocr_reader.subprocess, "run", spy)
    ocr(data)
    assert seen["env"] and all("AWS_SECRET_ACCESS_KEY" not in e and set(e) <= {"PATH", "OMP_THREAD_LIMIT", "LC_ALL"}
                               for e in seen["env"])


def test_a_dropped_value_word_ends_up_blank_and_named_unclear_in_the_invoice():
    """From Tesseract's words to the invoice: a low-confidence taxable value is dropped, so it is blank and unclear."""
    head = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"

    def word(x, y, text, conf=95, w=60):
        return f"5\t1\t1\t1\t1\t1\t{x}\t{y}\t{w}\t20\t{conf}\t{text}"

    def page(taxable_conf):
        return head + "\n".join([
            word(100, 100, "TAX", w=40), word(150, 100, "INVOICE", w=80),
            word(100, 140, "Invoice", w=80), word(190, 140, "No:", w=40), word(240, 140, "INV-9", w=60),
            word(100, 300, "HSN/SAC", w=90), word(400, 300, "Taxable", w=80), word(490, 300, "Value", w=60),
            word(100, 340, "6109", w=60), word(400, 340, "200.00", taxable_conf, w=80),
        ])

    def invoice(tsv):
        rows = _rows(tsv.encode(), 100)
        return assemble([read_page(1, rows, HSN)], 10)[0]

    sure = invoice(page(95))
    assert sure.lines[0].taxable_value == "200.00" and "taxable_value" not in sure.lines[0].unclear
    unsure = invoice(page(20))
    assert unsure.lines[0].taxable_value is None and "taxable_value" in unsure.lines[0].unclear


def test_an_ocr_read_scan_becomes_the_same_table_rows_as_its_text_layer_original():
    """What staging, the review screen and the Excel cross-check read is the table: same rows from both readers."""
    original = one_invoice()
    scanned = scan(original)
    from_text = to_table(TextLayerReader(HSN).read(original, LIMITS).invoices, filename="a.pdf", pdf=original)
    from_scan = to_table(ocr(scanned).invoices, filename="a.pdf", pdf=scanned)
    assert from_scan.rows == from_text.rows
    assert len(from_scan.rows) == 2  # the headings and one line
