"""The own-invoice PDF reader (R1-M6 S1): synthetic PDFs only. No database."""

import logging
import re

import pytest

from app.modules.imports.pdf import Limits, PdfRefused, TextLayerReader, to_table
from app.modules.imports.pdf.bedrock_stub import BedrockReader
from app.modules.imports.pdf.interface import InvoiceReader
from app.modules.imports.readers.own_excel import COLUMNS

from .fixtures.pdf import BUYER, SELLER, invoice_page, one_invoice, pdf

HSN = re.compile("^[0-9]{4}([0-9]{2}){0,2}$")  # the shape in refdata hsn.pattern
LIMITS = Limits(max_pages=20, max_chars_per_page=5000, max_documents=10, max_seconds=30)


def read(data, limits=LIMITS):
    return TextLayerReader(HSN).read(data, limits)


def test_a_plain_intra_state_invoice_is_read_field_by_field():
    result = read(one_invoice())
    assert result.unreadable_pages == ()
    (inv,) = result.invoices
    assert (inv.seller_gstin, inv.buyer_gstin) == (SELLER, BUYER)
    assert (inv.doc_type, inv.doc_number, inv.doc_date) == ("Invoice", "INV-1", "03-07-2026")
    assert inv.place_of_supply == "19"
    assert inv.invoice_total == "236.00"
    assert inv.unclear == frozenset()
    (line,) = inv.lines
    assert (line.hsn, line.quantity, line.unit) == ("6109", "2", "PCS")
    assert (line.taxable_value, line.gst_rate, line.cgst, line.sgst, line.igst) == (
        "200.00", "18", "18.00", "18.00", None)
    assert line.unclear == frozenset()


def test_inter_state_and_b2c_and_two_lines():
    data = one_invoice(buyer=None, place="Karnataka", total="472.00", lines=(
        ("6109", "2", "PCS", "200.00", "18", "", "", "36.00"),
        ("6110", "1", "NOS", "200.00", "18", "", "", "36.00")))
    (inv,) = read(data).invoices
    assert inv.buyer_gstin is None and "buyer_gstin" not in inv.unclear  # B2C is not "unclear"
    assert inv.place_of_supply == "Karnataka"
    assert [(ln.hsn, ln.igst, ln.cgst) for ln in inv.lines] == [("6109", "36.00", None), ("6110", "36.00", None)]


def test_amounts_with_commas_and_a_text_date_are_normalised_never_floated():
    data = one_invoice(date="3 Jul 2026", lines=(("6109", "1,000", "PCS", "1,00,000.50", "18", "9,000.05",
                                                  "9,000.05", ""),), total="1,18,000.60")
    (inv,) = read(data).invoices
    assert inv.doc_date == "03-07-2026"
    assert inv.lines[0].quantity == "1000" and inv.lines[0].taxable_value == "100000.50"
    assert inv.invoice_total == "118000.60"


def test_a_credit_note_keeps_its_original_invoice_number():
    (inv,) = read(one_invoice(title="CREDIT NOTE", number="CN-7", number_label="Credit Note No",
                              original=("INV-1", "03-07-2026"))).invoices
    assert (inv.doc_type, inv.doc_number, inv.original_number) == ("Credit note", "CN-7", "INV-1")
    assert inv.doc_date == "03-07-2026"  # the original invoice date line does not win


def test_a_credit_note_without_its_original_is_marked_unclear():
    (inv,) = read(one_invoice(title="CREDIT NOTE", number="CN-7")).invoices
    assert inv.original_number is None and "original_number" in inv.unclear


def test_missing_fields_stay_blank_and_are_named_never_guessed():
    page = [(40, 700, "Some page"), (40, 680, "with no invoice facts")]
    (inv,) = read(pdf([page])).invoices
    assert inv.doc_number is None and inv.doc_date is None and inv.lines == ()
    assert {"doc_number", "doc_date", "seller_gstin", "lines"} <= inv.unclear


def test_two_different_dates_on_one_invoice_blank_the_date():
    extra = [(330, 722, "Date: 05-07-2026")]
    (inv,) = read(pdf([invoice_page(header_extra=extra)])).invoices
    assert inv.doc_date is None and "doc_date" in inv.unclear


def test_a_split_layout_with_two_gstins_and_no_labels_blanks_the_seller():
    extra = [(200, 746, "GSTIN: 27DEMOB5678B1ZH")]
    (inv,) = read(pdf([invoice_page(header_extra=extra, buyer=None)])).invoices
    assert inv.seller_gstin is None and "seller_gstin" in inv.unclear


def test_a_two_page_invoice_is_one_document():
    p1 = invoice_page("INV-9", lines=(("6109", "1", "PCS", "100.00", "18", "9.00", "9.00", ""),), total=None)
    p2 = invoice_page("INV-9", lines=(("6110", "1", "PCS", "100.00", "18", "9.00", "9.00", ""),), total="236.00")
    (inv,) = read(pdf([p1, p2])).invoices
    assert inv.pages == (1, 2) and [ln.hsn for ln in inv.lines] == ["6109", "6110"]
    assert inv.invoice_total == "236.00"


def test_a_continuation_page_with_no_title_or_date_joins_the_document():
    cont = [(40, 760, "Page 2"), (40, 740, "S.No"), (190, 740, "HSN/SAC"), (335, 740, "Taxable Value"),
            (190, 726, "6110"), (335, 726, "50.00")]
    (inv,) = read(pdf([invoice_page("INV-9"), cont])).invoices
    assert inv.pages == (1, 2) and [ln.hsn for ln in inv.lines] == ["6109", "6110"]


def test_several_invoices_in_one_pdf_split_on_the_document_number():
    docs = read(pdf([invoice_page("INV-1"), invoice_page("INV-2"), invoice_page("INV-3")])).invoices
    assert [d.doc_number for d in docs] == ["INV-1", "INV-2", "INV-3"]


def test_an_ambiguous_boundary_refuses_the_whole_pdf():
    two_on_one = invoice_page("INV-1", header_extra=[(40, 560, "Invoice No: INV-2")])
    with pytest.raises(PdfRefused) as e:
        read(pdf([two_on_one]))
    assert e.value.code == "ambiguous_split"
    unnumbered_new_doc = invoice_page("INV-1"), [(40, 760, "TAX INVOICE"), (330, 746, "Invoice Date: 04-07-2026")]
    with pytest.raises(PdfRefused) as e:
        read(pdf(list(unnumbered_new_doc)))
    assert e.value.code == "ambiguous_split"


def test_the_document_cap():
    with pytest.raises(PdfRefused) as e:
        read(pdf([invoice_page(f"INV-{i}") for i in range(4)]), Limits(20, 5000, 3, 30))
    assert e.value.code == "too_many_documents"


def test_a_scan_with_no_text_layer_is_reported_not_guessed():
    empty = pdf([[]])
    result = read(empty)
    assert result.invoices == () and result.unreadable_pages == (1,)
    mixed = read(pdf([invoice_page("INV-1"), []]))
    assert len(mixed.invoices) == 1 and mixed.unreadable_pages == (2,)


@pytest.mark.parametrize("data,code", [
    (b"hello", "not_a_pdf"),
    (b"%PDF-1.4\nnot really", "unreadable"),
    (one_invoice()[:200], "unreadable"),
    (b"", "not_a_pdf"),
])
def test_files_that_are_not_readable_pdfs_are_refused(data, code):
    with pytest.raises(PdfRefused) as e:
        read(data)
    assert e.value.code == code


def test_page_and_character_caps():
    many = pdf([invoice_page(f"INV-{i}") for i in range(6)])
    with pytest.raises(PdfRefused) as e:
        read(many, Limits(5, 5000, 50, 30))
    assert e.value.code == "too_many_pages"
    with pytest.raises(PdfRefused) as e:
        read(one_invoice(), Limits(5, 50, 5, 30))
    assert e.value.code == "too_complex"


def test_the_time_cap():
    with pytest.raises(PdfRefused) as e:
        read(one_invoice(), Limits(5, 5000, 5, -1))
    assert e.value.code == "too_slow"


def test_an_encrypted_pdf_is_refused():
    data = one_invoice().replace(b"/Root 1 0 R", b"/Root 1 0 R /Encrypt 99 0 R")
    data = data.replace(b"trailer", b"99 0 obj\n<< /Filter /Standard /V 1 /R 2 /O (aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)"
                        b" /U (bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb) /P -4 >>\nendobj\ntrailer")
    with pytest.raises(PdfRefused) as e:
        read(data)
    assert e.value.code in ("encrypted", "unreadable")


def test_a_hostile_pdf_is_read_as_text_only_and_nothing_is_followed():
    extras = (
        b"<< /Type /Action /S /JavaScript /JS (app.alert\\('x'\\)) >>",
        b"<< /Type /Action /S /Launch /F (calc.exe) >>",
        b"<< /Type /Action /S /URI /URI (http://169.254.169.254/latest/meta-data) >>",
        b"<< /Type /Filespec /F (evil.exe) /EF << /F 99 0 R >> >>",
    )
    data = pdf([invoice_page("INV-1")], extra_objects=extras,
               catalog_extra="/OpenAction 5 0 R /Names << /EmbeddedFiles << /Names [(a) 8 0 R] >> >>")
    (inv,) = read(data).invoices  # still reads the text; never opens the action, the attachment or the link
    assert inv.doc_number == "INV-1"


def test_a_page_tree_loop_does_not_hang_or_leak_text():
    data = one_invoice().replace(b"/Kids [4 0 R]", b"/Kids [2 0 R 4 0 R]")
    try:
        read(data)
    except PdfRefused as e:
        assert e.code in ("unreadable", "too_many_pages")


def test_the_table_handoff_uses_the_excel_templates_headers():
    data = pdf([invoice_page("INV-1"), [(40, 700, "unreadable page of text")]])
    table = to_table(read(data).invoices, filename="a.pdf", pdf=data)
    assert table.rows[0] == [c.header for c in COLUMNS] + ["Unclear fields"]
    row = dict(zip(table.rows[0], table.rows[1], strict=True))
    assert row["Document number"] == "INV-1" and row["HSN"] == "6109" and row["IGST"] == ""
    assert table.checksum_sha256 and len(table.rows) == 2  # a bare second page continues the first document


def test_an_invoice_with_no_readable_line_still_gets_one_row():
    page = [(40, 760, "TAX INVOICE"), (330, 746, "Invoice No: INV-5"), (330, 732, "Invoice Date: 03-07-2026")]
    table = to_table(read(pdf([page])).invoices, filename="a.pdf", pdf=b"x")
    assert len(table.rows) == 2 and table.rows[1][2] == "INV-5" and table.rows[1][8] == ""


def test_no_text_or_amount_reaches_the_logs(caplog):
    caplog.set_level(logging.DEBUG)
    read(one_invoice())
    for bad in (b"junk", one_invoice()[:150]):
        with pytest.raises(PdfRefused):
            read(bad)
    text = caplog.text
    assert "INV-1" not in text and SELLER not in text and "236" not in text


def test_a_refusal_carries_only_its_code():
    with pytest.raises(PdfRefused) as e:
        read(one_invoice()[:150])
    assert str(e.value) == e.value.code and e.value.__cause__ is None


def test_the_paid_reader_stub_fits_the_interface_and_is_not_usable():
    reader: InvoiceReader = BedrockReader()
    assert reader.id == "pdf_bedrock_v1"
    with pytest.raises(NotImplementedError):
        reader.read(b"", LIMITS)


def test_the_hsn_shape_comes_from_the_callers_pattern_not_the_reader():
    data = one_invoice(lines=(("61", "2", "PCS", "200.00", "18", "18.00", "18.00", ""),))
    (inv,) = read(data).invoices
    assert inv.lines[0].hsn is None and "hsn" in inv.lines[0].unclear  # two digits do not fit hsn.pattern
    (inv,) = TextLayerReader(re.compile("^[0-9]{2,8}$")).read(data, LIMITS).invoices
    assert inv.lines[0].hsn == "61"


def test_numeric_dates_are_day_first_and_impossible_ones_are_blank():
    assert read(one_invoice(date="03/07/2026")).invoices[0].doc_date == "03-07-2026"
    (inv,) = read(one_invoice(date="13/13/2026")).invoices
    assert inv.doc_date is None and "doc_date" in inv.unclear


def test_a_word_from_in_the_buyer_block_does_not_move_a_gstin_to_the_seller():
    extra = [(200, 700, "Goods received from: Demo Transport")]
    (inv,) = read(pdf([invoice_page(header_extra=extra)])).invoices
    assert inv.seller_gstin == SELLER and inv.buyer_gstin == BUYER
