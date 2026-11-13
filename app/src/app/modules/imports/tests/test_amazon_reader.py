"""The Amazon MTR readers (R1-M4 S1), on synthetic files built from the spec's headers and quirks.
No database: parse and the hold rule only. The upload path is test_amazon_postgres.py."""

from decimal import Decimal

import pytest

from app.modules.imports import readers
from app.modules.imports.models import StagedRowStatus
from app.modules.imports.parsing import RowStatus, parse, read_table
from app.modules.imports.readers import amazon

from .fixtures import amazon as fx

B2C = amazon.AmazonReader("b2c")
B2B = amazon.AmazonReader("b2b")


def table(content, name="MTR_B2C-JULY-2026-123.csv"):
    return read_table(content, name)


def parsed(reader, content, name="MTR_B2C-JULY-2026-123.csv"):
    t = table(content, name)
    return parse(t, reader.profile())


def verdicts(reader, content):
    result = parsed(reader, content)
    return {r.normalized["shipment_item_id"]: (r.status, reader.classify(r)) for r in result.rows if r.normalized}


def test_a_b2c_file_belongs_to_the_b2c_reader_only():
    t = table(fx.b2c_good())
    assert B2C.detect(t) and not B2B.detect(t)


def test_a_b2b_file_belongs_to_the_b2b_reader_only():
    t = table(fx.b2b_good(), "MTR_B2B-JULY-2026-9.csv")
    assert B2B.detect(t) and not B2C.detect(t)


def test_the_seller_gstin_is_read_by_header_not_position():
    assert B2C.gstin(table(fx.b2c_good())) == fx.OWN
    assert B2C.gstin(table(fx.b2c_good(gstin=fx.OTHER))) == fx.OTHER
    # reorder: move the GSTIN column last; still found by its name
    headers = list(reversed(fx.B2C_HEADERS))
    rows = [fx.sale("1")]
    assert B2C.gstin(table(fx.csv_bytes(headers, rows))) == fx.OWN


def test_a_file_without_the_amazon_headers_is_not_amazons():
    other = b"Seller Gstin,Order Id,Txn Type\nX,1,Shipment\n"
    assert not B2C.detect(table(other, "x.csv")) and not B2B.detect(table(other, "x.csv"))
    assert B2C.gstin(table(other, "x.csv")) is None


@pytest.mark.parametrize("name, mine", [
    ("MTR_B2C-JULY-2026-123.csv", "b2c"), ("MTR_B2B-SEP-2026-9.csv", "b2b"), ("mtr_b2c-july-2026-1.CSV", "b2c"),
    ("GSTR1-Q2.xlsx", None), ("KA-fees.pdf", None), ("MTR_B2C-JULY.csv.exe", None), ("../MTR_B2C-1.csv", None),
])
def test_zip_entries_are_accepted_by_name(name, mine):
    assert B2C.accepts(name) == (mine == "b2c") and B2B.accepts(name) == (mine == "b2b")


def test_every_row_parses_and_two_units_of_one_invoice_are_not_duplicates():
    result = parsed(B2C, fx.b2c_good())
    assert [r.status for r in result.rows] == [RowStatus.valid] * 6
    invoices = [r.normalized["invoice_number"] for r in result.rows]
    assert invoices.count("INV-1") == 3  # two units and the refund share one invoice number


def test_rates_are_stored_as_percent_and_the_source_text_is_kept():
    first = parsed(B2C, fx.b2c_good()).rows[0]
    assert first.normalized["cgst_rate"] == Decimal("9.00") and first.normalized["igst_rate"] == Decimal("0.00")
    assert first.raw["Cgst Rate"] == "0.09"
    inter = parsed(B2C, fx.b2c_good()).rows[2]
    assert inter.normalized["igst_rate"] == Decimal("18.00") and inter.normalized["cgst_rate"] == 0


def test_money_stays_signed_and_decimal():
    refund = parsed(B2C, fx.b2c_good()).rows[3]
    assert refund.normalized["taxable_value"] == Decimal("-100.00") and refund.normalized["total_tax"] == Decimal("-18.00")
    assert refund.normalized["credit_note_no"] == "CN-1"


def test_the_good_file_is_new_but_for_the_zero_value_rows():
    v = verdicts(B2C, fx.b2c_good())
    assert v["ITEM-1"][1] is None and v["ITEM-2"][1] is None and v["ITEM-3"][1] is None
    assert v["ITEM-4"][1] == (StagedRowStatus.skipped_zero, None)  # cancel, no invoice number, no HSN
    assert v["ITEM-5"][1] == (StagedRowStatus.skipped_zero, None)  # free replacement at zero value
    assert all(status == RowStatus.valid for status, _ in v.values())


def test_a_refund_and_its_sale_share_an_item_id_but_not_a_key():
    result = parsed(B2C, fx.b2c_good())
    keys = {r.dedup_key for r in result.rows}
    assert len(keys) == 6  # nothing collapsed: the sale and the refund of ITEM-1 differ by type and credit note


def test_held_reasons():
    v = verdicts(B2C, fx.b2c_held())
    assert v["ITEM-10"][1] == (StagedRowStatus.held, "blank_hsn")
    assert v["ITEM-11"][1] == (StagedRowStatus.held, "blank_qty")
    assert v["ITEM-12"][1] == (StagedRowStatus.held, "unknown_state")
    assert v["ITEM-13"][1] == (StagedRowStatus.held, "unknown_txn_type")
    assert v["ITEM-14"][1] == (StagedRowStatus.held, "sanity")  # refund with no credit note number
    assert v["ITEM-15"][1] == (StagedRowStatus.held, "sanity")  # IGST and CGST on one row
    assert v["ITEM-16"][1] == (StagedRowStatus.held, "sanity")  # a cancel that carries value
    assert v["ITEM-17"][1] is None


def test_a_renamed_header_still_reads():
    result = parsed(B2C, fx.renamed_header(fx.b2c_good()))
    assert [r.status for r in result.rows] == [RowStatus.valid] * 6 and result.unmapped_headers == [
        "Buyer Name", "Ship To Address"]


def test_personal_columns_are_not_stored():
    result = parsed(B2C, fx.b2c_good())
    for r in result.rows:
        assert "Buyer Name" not in r.raw and "Ship To Address" not in r.raw
        assert "Made Up Buyer" not in str(r.normalized) + str(r.raw)
    assert result.summary()["columns_not_stored"] == 2


def test_b2b_keeps_the_buyer_gstin_and_irn_status():
    row = parsed(B2B, fx.b2b_good(), "MTR_B2B-JULY-2026-9.csv").rows[0]
    assert row.normalized["buyer_gstin"] == fx.OTHER and row.normalized["irn_status"] == "FILED"


def test_a_b2b_file_through_the_b2c_profile_is_not_confused_with_it():
    assert not B2C.detect(table(fx.b2b_good(), "MTR_B2B-JULY-2026-9.csv"))


def test_the_reader_registers_once_and_is_listed_by_section():
    readers.clear_for_tests()
    try:
        readers.register_platform_readers()
        readers.register_platform_readers()
        assert sorted(r.id for r in readers.readers_for("amazon")) == ["amazon_mtr_b2b_v1", "amazon_mtr_b2c_v1"]
        assert sorted(r.id for r in readers.readers_for("flipkart")) == ["flipkart_cashback_v1", "flipkart_sales_v1"]
        assert sorted(r.id for r in readers.readers_for("meesho")) == ["meesho_returns_v1", "meesho_sales_v1"]
    finally:
        readers.clear_for_tests()


def test_the_profiles_are_unverified_until_a_real_file_confirms_them():
    assert B2C.profile().verified is False and B2B.profile().verified is False


def test_a_rate_over_one_hundred_percent_is_held_not_stored_as_a_rate():
    rows = [{**fx.sale("30"), "Cgst Rate": "9", "Sgst Rate": "9"}]  # already percent: scaled to 900
    v = verdicts(B2C, fx.csv_bytes(fx.B2C_HEADERS, rows))
    assert v["ITEM-30"][1] == (StagedRowStatus.held, "sanity")


def test_a_file_naming_two_sellers_has_no_single_gstin():
    content = fx.csv_bytes(fx.B2C_HEADERS, [fx.sale("1"), fx.sale("2", gstin=fx.OTHER)])
    assert B2C.gstin(table(content)) == "MIXED"


def test_a_b2b_file_naming_two_sellers_has_no_single_gstin():
    headers = fx.B2C_HEADERS + fx.B2B_EXTRA
    content = fx.csv_bytes(headers, [fx.sale("1"), fx.sale("2", gstin=fx.OTHER)])
    assert B2B.gstin(table(content, "MTR_B2B-JULY.csv")) == "MIXED"
