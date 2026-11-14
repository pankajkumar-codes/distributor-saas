"""The own-invoice Excel reader (R1-M5 S1) on synthetic files. No database: parse and the hold rule only. The
upload path is test_own_excel_postgres.py."""

import re
from decimal import Decimal

from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import RowStatus, parse, read_table
from app.modules.imports.readers.own_excel import NUMBER_PATTERN_KEY, OwnExcelReader

from .fixtures import own_excel as fx

READER = OwnExcelReader()
STATES = {"west bengal", "19", "karnataka", "29"}
PATTERN = re.compile(r"^[A-Za-z0-9/-]{1,16}$")  # the refdata row's value, as a test stand-in
CONTEXT = {"states": STATES, NUMBER_PATTERN_KEY: PATTERN}
HELD = StagedRowStatus.held


def table(content, name="invoices.xlsx"):
    # The upload pipeline picks the `Invoices` sheet out of a workbook that also has a `How to fill` sheet.
    return read_table(content, name, sheet="Invoices" if name.endswith(".xlsx") else None)


def parsed(content, name="invoices.xlsx"):
    return parse(table(content, name), READER.profile()).rows


def verdict(row, context=CONTEXT):
    return READER.classify(row, context)


def one(**kw):
    rows = parsed(fx.workbook([fx.line(**kw)]))
    assert rows[0].status == RowStatus.valid, rows[0].errors
    return rows[0]


def test_a_file_is_claimed_by_its_headers_and_not_by_position():
    assert READER.detect(table(fx.good()))
    shuffled = list(reversed(fx.HEADERS))
    assert READER.detect(table(fx.workbook([fx.line()], headers=shuffled)))
    assert not READER.detect(table(fx.workbook([fx.line()], headers=fx.HEADERS[1:])))


def test_the_reader_names_no_zip_entries():
    assert not READER.accepts("Invoices.xlsx") and not READER.accepts("anything.csv")


def test_the_whole_sheet_is_read_with_exact_decimals_and_the_text_kept():
    rows = parsed(fx.good())
    assert len(rows) == 4 and all(r.status == RowStatus.valid for r in rows)
    assert rows[0].normalized["taxable_value"] == Decimal("200")
    assert rows[0].normalized["gst_rate"] == Decimal("18")
    assert rows[0].raw["GST rate %"] == "18"


def test_a_csv_with_the_same_headers_reads_the_same():
    from_csv = parsed(fx.csv_bytes([fx.line()]), "invoices.csv")
    assert from_csv[0].normalized["doc_number"] == "INV-1"
    assert READER.detect(table(fx.csv_bytes([fx.line()]), "invoices.csv"))


def test_only_the_buyer_gstin_of_the_buyers_details_is_kept_and_extra_columns_are_not_stored():
    rows = parsed(fx.workbook([fx.line(buyer="29DEMOC9999C1Z1")],
                              extra_columns=[("Customer name", "Made Up Buyer"), ("Address", "1 Made Up Lane")]))
    stored = repr(rows[0].normalized) + repr(rows[0].raw)
    assert "Made Up Buyer" not in stored and "Made Up Lane" not in stored
    assert rows[0].normalized["buyer_gstin"] == "29DEMOC9999C1Z1"
    result = parse(table(fx.workbook([fx.line()], extra_columns=[("Customer name", "x")])), READER.profile())
    assert result.unmapped_headers == ["Customer name"]


def test_a_good_invoice_row_and_an_inter_state_row_pass():
    assert verdict(one()) is None
    assert verdict(parsed(fx.workbook([fx.inter()]))[0]) is None


def test_the_gstin_comes_from_the_column_and_several_sellers_are_mixed():
    assert READER.gstin(table(fx.good())) == fx.OWN
    mixed = fx.workbook([fx.line("A"), fx.line("B", gstin=fx.OTHER)])
    assert READER.gstin(table(mixed)) == "MIXED"
    assert READER.gstin(table(fx.workbook([fx.line(gstin="")]))) is None


def test_an_unknown_document_type_is_held():
    assert verdict(one(kind="Proforma")) == (HELD, "unknown_txn_type")
    assert verdict(one(kind="credit note", original="INV-1")) is None  # case is not a difference


def test_a_note_with_no_original_invoice_is_held_but_an_invoice_needs_none():
    assert verdict(one(kind="Credit note")) == (HELD, "missing_original_invoice")
    assert verdict(one(kind="Debit note")) == (HELD, "missing_original_invoice")
    assert verdict(one(kind="Credit note", original="INV-1", original_date="03-07-2026")) is None


def test_a_document_number_that_does_not_fit_the_pattern_is_held_by_the_refdata_pattern_not_a_literal():
    assert verdict(one(number="INV/2026-27/000000001")) == (HELD, "invoice_number_format")  # 21 characters
    assert verdict(one(number="INV 1")) == (HELD, "invoice_number_format")
    assert verdict(one(number="INV 1"), {"states": STATES}) is None  # no pattern given: nothing to check


def test_blank_hsn_quantity_unit_and_place_of_supply_are_held():
    assert verdict(one(hsn="")) == (HELD, "blank_hsn")
    assert verdict(one(qty="")) == (HELD, "blank_qty")
    assert verdict(one(unit="")) == (HELD, "blank_uqc")
    assert verdict(one(state="")) == (HELD, "unknown_state")
    assert verdict(one(state="Atlantis")) == (HELD, "unknown_state")
    assert verdict(one(state="29")) is None  # a state code is fine too


def test_a_rate_of_zero_is_kept_as_typed_and_a_rate_outside_zero_to_100_is_held():
    assert verdict(one(rate="0", cgst="0", sgst="0")) is None
    assert verdict(one(rate="101")) == (HELD, "sanity")


def test_igst_with_cgst_or_sgst_and_unequal_halves_are_held_but_arithmetic_is_not_checked_here():
    assert verdict(one(igst="36")) == (HELD, "sanity")
    assert verdict(one(cgst="18", sgst="17")) == (HELD, "sanity")
    assert verdict(one(taxable="200", rate="18", cgst="1", sgst="1")) is None  # wrong tax, not this reader's call


def test_dates_are_real_excel_dates_or_typed_text_and_a_bad_one_is_invalid():
    import datetime as dt

    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "Invoices"
    wb.active.append(fx.HEADERS)
    wb.active.append([fx.line()[h] if h != "Document date" else dt.date(2026, 7, 3) for h in fx.HEADERS])
    import io

    out = io.BytesIO()
    wb.save(out)
    assert parse(table(out.getvalue()), READER.profile()).rows[0].normalized["doc_date"] == dt.date(2026, 7, 3)
    bad = parsed(fx.workbook([fx.line(date="3rd July")]))
    assert bad[0].status == RowStatus.invalid and bad[0].errors[0].field == "doc_date"


def test_the_same_document_number_in_another_case_or_with_spaces_is_one_document_key():
    a, b = parsed(fx.workbook([fx.line("inv-1"), fx.line(" INV-1 ", hsn="6110")]))
    assert a.dedup_key[:3] == b.dedup_key[:3]


def test_lines_of_one_document_are_counted_by_position_and_never_conflict_in_one_file():
    rows = parsed(fx.workbook([fx.line("INV-1"), fx.line("INV-1", hsn="6110"), fx.line("INV-1", hsn="6111"),
                               fx.line("INV-2")]))
    assert [r.status for r in rows] == [RowStatus.valid] * 4
    assert [r.dedup_key[-1] for r in rows] == ["1", "2", "3", "1"]
    assert len({r.dedup_key for r in rows}) == 4


def test_reordered_lines_change_the_rows_under_the_same_keys_so_a_later_file_shows_them_as_changed():
    first = parsed(fx.workbook([fx.line("INV-1", hsn="6109"), fx.line("INV-1", hsn="6110")]))
    second = parsed(fx.workbook([fx.line("INV-1", hsn="6110"), fx.line("INV-1", hsn="6109")]))
    for a, b in zip(first, second, strict=True):
        assert a.dedup_key == b.dedup_key and a.content_hash != b.content_hash
