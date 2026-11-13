"""The Flipkart readers (R1-M4 S2) on synthetic workbooks built from the spec's headers and quirks.
No database: parse and the hold rule only. The upload path is test_flipkart_postgres.py."""

from decimal import Decimal

from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import RowStatus, parse, read_table
from app.modules.imports.readers.flipkart import FlipkartCashbackReader, FlipkartSalesReader

from .fixtures import flipkart as fx

SALES = FlipkartSalesReader()
CASH = FlipkartCashbackReader()


def sheet(content, name):
    return read_table(content, "Sales Report - Jul 2026.xlsx", sheet=name)


def verdicts(content, key="order_item_id"):
    table = sheet(content, "Sales Report")
    return {r.normalized[key]: (r.status, SALES.classify(r)) for r in parse(table, SALES.profile()).rows if r.normalized}


def test_each_sheet_belongs_to_its_reader_by_headers():
    good = fx.good()
    assert SALES.detect(sheet(good, "Sales Report")) and not CASH.detect(sheet(good, "Sales Report"))
    assert CASH.detect(sheet(good, "Cash Back Report")) and not SALES.detect(sheet(good, "Cash Back Report"))
    assert not SALES.detect(sheet(good, "Help")) and not CASH.detect(sheet(good, "Help"))


def test_a_sheet_that_declares_one_row_is_read_to_the_end():
    table = sheet(fx.good(), "Sales Report")
    assert len(table.rows) == 5  # header and four sales rows, whatever the sheet claims


def test_every_row_parses_and_the_text_numbers_are_exact_decimals():
    result = parse(sheet(fx.good(), "Sales Report"), SALES.profile())
    assert all(r.status == RowStatus.valid for r in result.rows)
    first = result.rows[0]
    assert first.normalized["taxable_value"] == Decimal("100.0") and isinstance(first.normalized["taxable_value"], Decimal)
    assert first.normalized["cgst_rate"] == Decimal("9.0")  # percent as written, not scaled
    assert first.raw["Taxable Value (Final Invoice Amount -Taxes)"] == "100.0"


def test_money_stays_signed_and_a_return_is_not_a_duplicate_of_its_sale():
    rows = parse(sheet(fx.good(), "Sales Report"), SALES.profile()).rows
    assert rows[2].normalized["taxable_value"] == Decimal("-100.0")
    assert rows[2].status == RowStatus.valid  # same item id as row 1, different event


def test_the_gstin_is_read_by_header_and_a_second_seller_is_refused():
    assert SALES.gstin(sheet(fx.good(), "Sales Report")) == fx.OWN
    assert CASH.gstin(sheet(fx.good(), "Cash Back Report")) == fx.OWN
    mixed = fx.workbook([fx.sale("1"), fx.sale("2", gstin=fx.OTHER)])
    assert SALES.gstin(sheet(mixed, "Sales Report")) == "MIXED"
    mixed_notes = fx.workbook([], [fx.note("CN-1"), fx.note("CN-2", gstin=fx.OTHER)])
    assert CASH.gstin(sheet(mixed_notes, "Cash Back Report")) == "MIXED"


def test_held_reasons():
    v = verdicts(fx.held())
    assert v["OI-10"][1] == (StagedRowStatus.held, "blank_hsn")
    assert v["OI-11"][1] == (StagedRowStatus.held, "blank_qty")
    assert v["OI-12"][1] == (StagedRowStatus.held, "unknown_state")
    assert v["OI-13"][1] == (StagedRowStatus.held, "unknown_txn_type")
    assert v["OI-14"][1] == (StagedRowStatus.held, "sanity")  # a rate over 100
    assert v["OI-15"][1] == (StagedRowStatus.held, "sanity")  # a cancellation carrying value
    assert v["OI-16"][1] == (StagedRowStatus.held, "sanity")  # IGST and CGST on one row
    assert v["OI-17"][1] is None


def test_a_zero_value_cancellation_is_shown_and_left_out_not_dropped():
    v = verdicts(fx.good())
    assert v["OI-3"][1] == (StagedRowStatus.skipped_zero, None)


def test_every_cash_back_row_is_held_for_the_ca():
    rows = parse(sheet(fx.good(), "Cash Back Report"), CASH.profile()).rows
    assert len(rows) == 2 and all(r.status == RowStatus.valid for r in rows)
    assert {CASH.classify(r) for r in rows} == {(StagedRowStatus.held, "cashback_adjustment")}


def test_personal_columns_are_not_stored():
    row = parse(sheet(fx.good(), "Sales Report"), SALES.profile()).rows[0]
    assert "Customer Name" not in row.raw and "Customer's Delivery Address" not in row.raw
    assert "Made Up Buyer" not in str(row.normalized) + str(row.raw)


def test_the_profiles_are_unverified_until_a_real_file_confirms_them():
    assert not SALES.profile().verified and not CASH.profile().verified


def test_a_lower_case_gstin_is_the_same_seller_as_its_upper_case_form():
    content = fx.workbook([fx.sale("1"), fx.sale("2", gstin=fx.OWN.lower())])
    assert SALES.gstin(sheet(content, "Sales Report")) == fx.OWN


def test_a_header_only_sheet_has_no_rows():
    content = fx.workbook([fx.sale("1")], [])
    assert SALES.has_rows(sheet(content, "Sales Report")) and not CASH.has_rows(sheet(content, "Cash Back Report"))
