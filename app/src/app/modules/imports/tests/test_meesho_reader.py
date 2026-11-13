"""The Meesho readers (R1-M4 S3) on synthetic workbooks built from the spec's headers and quirks.
No database: parse and the hold rule only. The upload path is test_meesho_postgres.py."""

from decimal import Decimal

from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import RowStatus, parse, read_table

from app.modules.imports.readers.meesho import MeeshoReader

from .fixtures import meesho as fx

SALES = MeeshoReader("sales")
RETURNS = MeeshoReader("returns")


def table(content, name="tcs_sales.xlsx"):
    return read_table(content, name)


def parsed(reader, content):
    return parse(table(content), reader.profile()).rows


def verdicts(content, reader=SALES):
    return [(r.status, reader.classify(r)) for r in parsed(reader, content)]


def test_a_file_belongs_to_the_reader_of_its_kind_by_headers():
    assert SALES.detect(table(fx.sales_good())) and not RETURNS.detect(table(fx.sales_good()))
    ret = table(fx.returns_good(), "tcs_sales_return.xlsx")
    assert RETURNS.detect(ret) and not SALES.detect(ret)


def test_zip_entry_names_are_exact():
    assert SALES.accepts("tcs_sales.xlsx") and not SALES.accepts("tcs_sales_return.xlsx")
    assert RETURNS.accepts("tcs_sales_return.xlsx") and not RETURNS.accepts("tcs_sales.xlsx")


def test_the_whole_sheet_is_read_and_numbers_are_exact_decimals_with_the_text_kept():
    rows = parsed(SALES, fx.sales_good())
    assert len(rows) == 3 and all(r.status == RowStatus.valid for r in rows)
    first = rows[0]
    assert first.normalized["taxable_value"] == Decimal("170.33898305084747")
    assert first.raw["total_taxable_sale_value"] == "170.33898305084747"
    assert first.normalized["gst_rate"] == Decimal("18.00")  # percent text, kept as written


def test_the_text_null_is_a_blank_date_not_an_error():
    adj = parsed(SALES, fx.sales_good())[2]
    assert adj.status == RowStatus.valid and adj.normalized["manifest_date"] is None


def test_an_adjustment_row_is_kept_and_held_for_the_ca_not_dropped_or_counted_as_a_sale():
    v = verdicts(fx.sales_good())
    assert v[0][1] is None
    assert v[2][1] == (StagedRowStatus.held, "price_adjustment")


def test_a_quantity_zero_row_with_no_value_is_zero_value():
    content = fx.workbook([fx.sale("1", qty="0", taxable="0.0", tax="0.0", invoice="0.0")])
    assert verdicts(content)[0][1] == (StagedRowStatus.skipped_zero, None)


def test_held_reasons():
    rows = [fx.sale("1", hsn=""), fx.sale("2", qty=""), fx.sale("3", state=""), fx.sale("4", rate="180.00"),
            fx.sale("5", taxable="-5.0", invoice="-5.9"), fx.sale("6")]
    v = verdicts(fx.workbook(rows))
    assert [x[1] for x in v] == [(StagedRowStatus.held, "blank_hsn"), (StagedRowStatus.held, "blank_qty"),
                                 (StagedRowStatus.held, "unknown_state"), (StagedRowStatus.held, "sanity"),
                                 (StagedRowStatus.held, "sanity"), None]


def test_a_return_needs_its_return_date():
    content = fx.workbook([fx.sale("1")], headers=fx.RETURN_HEADERS)
    assert verdicts(content, RETURNS)[0][1] == (StagedRowStatus.held, "sanity")
    assert verdicts(fx.returns_good(), RETURNS)[0][1] is None


def test_identical_rows_in_one_file_are_separate_records_counted_in_order():
    rows = parsed(SALES, fx.workbook([fx.sale("1"), fx.sale("1"), fx.sale("2")]))
    assert [r.status for r in rows] == [RowStatus.valid] * 3
    assert [r.dedup_key[-1] for r in rows] == ["1", "2", "1"]
    assert len({r.dedup_key for r in rows}) == 3


def test_rows_with_the_same_key_but_different_other_values_are_all_conflicts_never_merged():
    rows = parsed(SALES, fx.workbook([fx.sale("1"), fx.sale("1", state="KARNATAKA"), fx.sale("2")]))
    assert [r.status for r in rows] == [RowStatus.conflict, RowStatus.conflict, RowStatus.valid]
    assert rows[0].related_rows == [3] and rows[1].related_rows == [2]


def test_the_gstin_is_read_by_header_and_a_second_seller_is_refused():
    assert SALES.gstin(table(fx.sales_good())) == fx.OWN
    mixed = fx.workbook([fx.sale("1"), fx.sale("2", gstin=fx.OTHER)])
    assert SALES.gstin(table(mixed)) == "MIXED"
    mixed_returns = fx.workbook([fx.sale("1"), fx.sale("2", gstin=fx.OTHER)], headers=fx.RETURN_HEADERS)
    assert RETURNS.gstin(table(mixed_returns, "tcs_sales_return.xlsx")) == "MIXED"


def test_personal_and_operator_columns_are_not_stored_as_personal_data():
    row = parsed(SALES, fx.sales_good())[0]
    assert "sup_name" not in row.raw and "enrollment_no" not in row.raw
    assert "Made Up Supplier" not in str(row.raw) + str(row.normalized)


def test_the_profiles_are_unverified_until_a_real_file_confirms_them():
    assert not SALES.profile().verified and not RETURNS.profile().verified
