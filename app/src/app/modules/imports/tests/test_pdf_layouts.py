"""The two layouts added in R1-M6 slice 4c: tax split over two heading rows, and labels above their values.
Synthetic pages only (fixtures/pdf.py); nothing here was tried on a real invoice."""

import re

from app.modules.imports.pdf import Limits, TextLayerReader

from .fixtures.pdf import BUYER, SELLER, pdf

HSN = re.compile("^[0-9]{4,8}$")
LIMITS = Limits(max_pages=5, max_chars_per_page=5000, max_documents=10, max_seconds=30)


def read(items):
    return TextLayerReader(HSN).read(pdf([items]), LIMITS)


def two_row_tax_page():
    return [
        (40, 760, "TAX INVOICE"), (40, 746, "Demo Seller Pvt Ltd"), (40, 734, f"GSTIN: {SELLER}"),
        (330, 746, "Invoice No: INV-5"), (330, 734, "Invoice Date: 03-07-2026"),
        (40, 720, "Bill To:"), (40, 708, "Demo Buyer"), (40, 696, f"GSTIN: {BUYER}"),
        (330, 708, "Place of Supply: West Bengal (19)"),
        (40, 660, "HSN/SAC"), (120, 660, "Qty"), (170, 660, "Taxable Value"), (260, 660, "GST %"),
        (330, 660, "CGST"), (420, 660, "SGST"),
        (320, 648, "Rate"), (355, 648, "Amt"), (410, 648, "Rate"), (445, 648, "Amt"),
        (40, 634, "6109"), (120, 634, "2"), (170, 634, "200.00"), (260, 634, "18"),
        (320, 634, "9"), (355, 634, "18.00"), (410, 634, "9"), (445, 634, "18.00"),
        (330, 600, "Grand Total"), (445, 600, "236.00"),
    ]


def test_a_tax_group_over_rate_and_amt_reads_the_amount_and_not_the_rate():
    (inv,) = read(two_row_tax_page()).invoices
    (line,) = inv.lines
    assert (line.hsn, line.quantity, line.taxable_value, line.gst_rate) == ("6109", "2", "200.00", "18")
    assert (line.cgst, line.sgst, line.igst) == ("18.00", "18.00", None)  # not "9 18.00", not 9
    assert line.unclear == frozenset({"unit"}) and inv.unclear == frozenset()


def test_without_a_gst_percent_column_a_split_cgst_rate_is_not_turned_into_a_rate():
    items = [i for i in two_row_tax_page() if i[2] not in ("GST %", "18")]
    (inv,) = read(items).invoices
    assert inv.lines[0].gst_rate is None and "gst_rate" in inv.lines[0].unclear
    assert (inv.lines[0].cgst, inv.lines[0].sgst) == ("18.00", "18.00")


def test_an_igst_rate_under_the_igst_group_is_the_rate_when_there_is_no_gst_percent_column():
    items = [
        (40, 760, "TAX INVOICE"), (40, 746, f"GSTIN: {SELLER}"), (330, 746, "Invoice No: INV-6"),
        (330, 734, "Invoice Date: 03-07-2026"), (330, 708, "Place of Supply: Karnataka"),
        (40, 660, "HSN/SAC"), (170, 660, "Taxable Value"), (330, 660, "IGST"),
        (320, 648, "Rate"), (355, 648, "Amt"),
        (40, 634, "6109"), (170, 634, "200.00"), (320, 634, "18"), (355, 634, "36.00"),
        (330, 600, "Grand Total"), (355, 600, "236.00"),
    ]
    (inv,) = read(items).invoices
    assert (inv.lines[0].igst, inv.lines[0].gst_rate, inv.lines[0].cgst) == ("36.00", "18", None)


def stacked_page():
    return [
        (40, 760, "TAX INVOICE"), (40, 746, "Demo Seller Pvt Ltd"), (40, 734, f"GSTIN: {SELLER}"),
        (40, 710, "Invoice No"), (200, 710, "Invoice Date"), (360, 710, "Place of Supply"),
        (40, 696, "INV-8"), (200, 696, "03-07-2026"), (360, 696, "West Bengal (19)"),
        (40, 670, "Bill To:"), (40, 658, "Demo Buyer"), (40, 646, f"GSTIN: {BUYER}"),
        (40, 610, "HSN/SAC"), (120, 610, "Qty"), (170, 610, "Taxable Value"), (260, 610, "GST %"),
        (330, 610, "CGST"), (420, 610, "SGST"),
        (40, 596, "6109"), (120, 596, "2"), (170, 596, "200.00"), (260, 596, "18"), (330, 596, "18.00"),
        (420, 596, "18.00"),
        (330, 560, "Grand Total"), (420, 560, "236.00"),
    ]


def test_labels_above_their_values_are_read_like_label_colon_value():
    (inv,) = read(stacked_page()).invoices
    assert (inv.doc_number, inv.doc_date, inv.place_of_supply) == ("INV-8", "03-07-2026", "19")
    assert (inv.seller_gstin, inv.buyer_gstin, inv.invoice_total) == (SELLER, BUYER, "236.00")
    assert inv.unclear == frozenset()


def test_a_label_row_with_a_label_that_has_no_value_under_it_is_left_alone():
    items = [i for i in stacked_page() if i[2] != "03-07-2026"]
    (inv,) = read(items).invoices
    assert inv.doc_number is None and inv.doc_date is None  # never half-joined or guessed
    assert {"doc_number", "doc_date"} <= inv.unclear


def test_the_table_heading_row_is_never_taken_for_a_label_row():
    (inv,) = read(stacked_page()).invoices
    assert inv.lines[0].hsn == "6109" and inv.lines[0].taxable_value == "200.00"
