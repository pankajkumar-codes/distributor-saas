"""The reader keeps each line's item description for purchases (D-107, #429); own-invoice tables still drop it."""

import re

from app.modules.imports.pdf import Limits, TextLayerReader, to_table
from app.modules.imports.pdf.extract import DESCRIPTION_MAX, _description, _is_description
from app.modules.imports.pdf.sandbox import _result, to_json

from .fixtures.pdf import one_invoice

HSN = re.compile("^[0-9]{4}([0-9]{2}){0,2}$")
LIMITS = Limits(max_pages=20, max_chars_per_page=5000, max_documents=10, max_seconds=30)
TWO = (("3401", "10", "PCS", "450.00", "18", "40.50", "40.50", ""),
       ("1515", "5", "LTR", "900.00", "5", "22.50", "22.50", ""))


def read(data):
    return TextLayerReader(HSN).read(data, LIMITS)


def test_each_line_keeps_its_description_and_no_line_is_marked_unclear_for_it():
    (inv,) = read(one_invoice(lines=TWO, total="1453.00", descriptions=("Neem Soap 100g", "Coconut Oil 1L"))).invoices
    assert [ln.description for ln in inv.lines] == ["Neem Soap 100g", "Coconut Oil 1L"]
    assert [ln.hsn for ln in inv.lines] == ["3401", "1515"]
    assert all("description" not in ln.unclear for ln in inv.lines)


def test_a_wrapped_description_joins_the_line_above_and_makes_no_line_of_its_own():
    (inv,) = read(one_invoice(lines=TWO, total="1453.00", descriptions=("Neem Soap", "Coconut Oil 1L"),
                              wrapped={1: "100g pack of 4"})).invoices
    assert [ln.description for ln in inv.lines] == ["Neem Soap 100g pack of 4", "Coconut Oil 1L"]


def test_other_headings_for_the_item_column_are_read_too():
    for heading in ("Particulars", "Item", "Description of Goods", "Product Name"):
        (inv,) = read(one_invoice(desc_heading=heading, descriptions=("Neem Soap 100g",))).invoices
        assert inv.lines[0].description == "Neem Soap 100g", heading
    for heading in ("Item Code", "Product No", "S.No"):
        assert not _is_description(heading.casefold()), heading


def test_a_long_description_is_cut_at_a_whole_word_within_the_cap():
    long = "Premium cold pressed coconut oil " * 6
    cut = _description(long)
    assert len(cut) <= DESCRIPTION_MAX and long.startswith(cut) and not cut.endswith(" ")
    assert _description("x" * 150) == "x" * DESCRIPTION_MAX  # one long word: cut at the cap
    assert _description("   ") is None


def test_the_sandbox_round_trip_keeps_the_description():
    result = read(one_invoice(descriptions=("Neem Soap 100g",)))
    import json
    back = _result(json.loads(to_json(result)), LIMITS)
    assert back.invoices[0].lines[0].description == "Neem Soap 100g"


def test_own_invoice_tables_never_carry_the_description():
    data = one_invoice(descriptions=("Neem Soap 100g",))
    table = to_table(read(data).invoices, filename="x.pdf", pdf=data)
    assert not any("Neem Soap" in cell for row in table.rows for cell in row)
