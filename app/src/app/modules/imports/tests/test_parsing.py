"""Import parsing: files in, staged rows out. Synthetic data only; the profile below is
a made-up layout for tests, not any marketplace's real report format."""

import datetime as dt
import io
import re
import zipfile
from decimal import Decimal

import openpyxl
import pytest

from app.modules.imports.parsing import FieldKind, FieldSpec, FileRejected, MappingProfile, ProfileError, RowStatus, parse, read_table
from app.modules.imports.parsing.normalize import HeaderMismatch

PROFILE = MappingProfile(
    marketplace="amazon",
    report_type="orders",
    version="test-1",
    fields=(
        FieldSpec("order_id", ("Order ID", "order-id")),
        FieldSpec("line_id", ("Line ID",)),
        FieldSpec("sku", ("SKU",)),
        FieldSpec("quantity", ("Qty",), FieldKind.integer),
        FieldSpec("amount", ("Amount",), FieldKind.decimal),
        FieldSpec("order_date", ("Order Date",), FieldKind.date, formats=("%d-%m-%Y", "%Y-%m-%d %H:%M:%S")),
        FieldSpec("note", ("Note",), required=False),
    ),
    dedup_key=("order_id", "line_id"),
)

HEADER = "Order ID,Line ID,SKU,Qty,Amount,Order Date,Note\n"


def csv_table(body: str, header: str = HEADER, name: str = "orders.csv"):
    return read_table((header + body).encode(), name)


def statuses(result):
    return {r.row_number: r.status for r in result.rows}


# --- reading files -------------------------------------------------------------


def test_csv_rows_normalize_without_float():
    result = parse(csv_table("A1,1,SKU-9,2,\"1,23,456.70\",05-10-2026,\n"), PROFILE)
    (row,) = result.rows
    assert row.status == RowStatus.valid
    assert row.normalized["amount"] == Decimal("123456.70")
    assert isinstance(row.normalized["amount"], Decimal)
    assert row.normalized["quantity"] == 2
    assert row.normalized["order_date"] == dt.date(2026, 10, 5)
    assert row.normalized["note"] is None
    assert row.raw["Amount"] == "1,23,456.70"  # raw value kept exactly as sent
    assert row.row_number == 2
    assert result.profile_verified is False


def test_utf8_bom_is_ignored():
    result = parse(read_table(("﻿" + HEADER + "A1,1,S,1,10,01-10-2026,\n").encode(), "x.csv"), PROFILE)
    assert result.rows[0].status == RowStatus.valid


def test_non_utf8_csv_is_rejected_not_guessed():
    with pytest.raises(FileRejected, match="UTF-8"):
        read_table((HEADER + "A1,1,Café,1,10,01-10-2026,\n").encode("latin-1"), "x.csv")


@pytest.mark.parametrize("name", ["report.xls", "report.pdf", "report"])
def test_unsupported_types_are_rejected(name):
    with pytest.raises(FileRejected):
        read_table(b"anything", name)


def test_empty_and_oversized_files_are_rejected(monkeypatch):
    with pytest.raises(FileRejected, match="empty"):
        read_table(b"", "x.csv")
    monkeypatch.setattr("app.modules.imports.parsing.files.MAX_FILE_BYTES", 10)
    with pytest.raises(FileRejected, match="larger"):
        read_table(b"a" * 11, "x.csv")


def test_row_limit(monkeypatch):
    monkeypatch.setattr("app.modules.imports.parsing.files.MAX_ROWS", 2)
    with pytest.raises(FileRejected, match="more than 2 rows"):
        read_table(b"a\nb\nc\n", "x.csv")


def test_renamed_copy_has_same_checksum():
    content = (HEADER + "A1,1,S,1,10,01-10-2026,\n").encode()
    assert read_table(content, "a.csv").checksum_sha256 == read_table(content, "copy of a.csv").checksum_sha256
    assert read_table(content + b"\n", "a.csv").checksum_sha256 != read_table(content, "a.csv").checksum_sha256


def xlsx_bytes(rows, sheets=("Orders",)):
    wb = openpyxl.Workbook()
    wb.active.title = sheets[0]
    for extra in sheets[1:]:
        wb.create_sheet(extra)
    for row in rows:
        wb[sheets[0]].append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_numbers_and_dates_become_exact_text():
    content = xlsx_bytes(
        [
            ["Order ID", "Line ID", "SKU", "Qty", "Amount", "Order Date"],
            ["A1", 1, "S", 3, 199.99, dt.datetime(2026, 10, 5)],
            ["A2", 1, "S", 1, 1e16, dt.datetime(2026, 10, 6)],
        ]
    )
    result = parse(read_table(content, "orders.xlsx"), PROFILE)
    first, second = result.rows
    assert first.raw["Amount"] == "199.99"
    assert first.normalized["amount"] == Decimal("199.99")
    assert first.normalized["order_date"] == dt.date(2026, 10, 5)
    # Large values come out as plain digits, never scientific notation.
    assert second.raw["Amount"] == "10000000000000000"
    assert result.sheet == "Orders"


def test_xlsx_formula_cells_are_rejected():
    content = xlsx_bytes(
        [
            ["Order ID", "Line ID", "SKU", "Qty", "Amount", "Order Date"],
            ["A1", 1, "S", 1, "=10*2", "05-10-2026"],
        ]
    )
    (row,) = parse(read_table(content, "o.xlsx"), PROFILE).rows
    assert row.status == RowStatus.invalid
    assert [e.code for e in row.errors] == ["formula"]


def _claim_dimension(content: bytes, ref: str | None) -> bytes:
    """Rewrites sheet1's stored <dimension>, as some marketplace exports have it."""
    src, out = zipfile.ZipFile(io.BytesIO(content)), io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "xl/worksheets/sheet1.xml":
                new = f'<dimension ref="{ref}"/>' if ref else ""
                data, n = re.subn(rb'<dimension ref="[^"]*" ?/>', new.encode(), data)
                assert n == 1
            dst.writestr(info, data)
    return out.getvalue()


@pytest.mark.parametrize("ref", ["A1", None])
def test_xlsx_with_a_wrong_or_missing_dimension_reads_every_row(ref):
    # Meesho and Flipkart workbooks: read-only openpyxl used to return the header only (RM47-J16).
    rows = [["Order ID", "Line ID", "SKU", "Qty", "Amount", "Order Date"]]
    rows += [[f"A{i}", "1", "S", "1", "10", "01-10-2026"] for i in range(1, 4)]
    content = _claim_dimension(xlsx_bytes(rows), ref)
    table = read_table(content, "orders.xlsx")
    assert len(table.rows) == 4
    assert [r.raw["Order ID"] for r in parse(table, PROFILE).rows] == ["A1", "A2", "A3"]


def test_xlsx_with_several_sheets_needs_a_choice():
    content = xlsx_bytes([["Order ID"]], sheets=("Orders", "Summary"))
    with pytest.raises(FileRejected, match="several sheets"):
        read_table(content, "o.xlsx")
    assert read_table(content, "o.xlsx", sheet="Orders").sheet == "Orders"
    with pytest.raises(FileRejected, match="not found"):
        read_table(content, "o.xlsx", sheet="Nope")


def test_corrupt_xlsx_is_rejected():
    with pytest.raises(FileRejected, match="xlsx"):
        read_table(b"PK\x03\x04 not really a zip", "o.xlsx")


# --- headers -------------------------------------------------------------------


def test_header_found_below_preamble_and_matched_loosely():
    body = "Order report,,,\nPeriod: Oct 2026,,,\n" + "  order-id ,LINE ID,sku,QTY,amount,order date,Extra\n"
    result = parse(read_table((body + "A1,1,S,1,10,01-10-2026,x\n").encode(), "x.csv"), PROFILE)
    assert result.header_row_number == 3
    assert result.rows[0].row_number == 4
    assert result.unmapped_headers == ["Extra"]
    assert "Extra" not in result.rows[0].raw  # unmapped columns are never stored (LLD-7 L7-2)


def test_missing_required_column_names_it():
    with pytest.raises(HeaderMismatch) as exc:
        parse(csv_table("A1,1,S,10,01-10-2026\n", header="Order ID,Line ID,SKU,Amount,Order Date\n"), PROFILE)
    assert exc.value.missing_fields == ["quantity"]


def test_wrong_report_is_rejected():
    with pytest.raises(HeaderMismatch, match="right report"):
        parse(csv_table("1,2\n", header="foo,bar\n"), PROFILE)


def test_two_columns_for_one_field_is_ambiguous():
    header = "Order ID,order-id,Line ID,SKU,Qty,Amount,Order Date\n"
    with pytest.raises(FileRejected, match="more than one column"):
        parse(csv_table("A,B,1,S,1,10,01-10-2026\n", header=header), PROFILE)


# --- row validation ------------------------------------------------------------


def test_one_bad_row_does_not_touch_the_others():
    body = (
        "A1,1,S,1,10.50,01-10-2026,\n"
        "A2,1,S,two,abc,31-02-2026,\n"
        ",1,S,1,10,01-10-2026,\n"
        "A3,1,S,1,10,01-10-2026,\n"
    )
    result = parse(csv_table(body), PROFILE)
    assert statuses(result) == {2: "valid", 3: "invalid", 4: "invalid", 5: "valid"}
    bad = result.rows[1]
    assert {(e.field, e.code) for e in bad.errors} == {
        ("quantity", "not_integer"),
        ("amount", "not_decimal"),
        ("order_date", "bad_date"),
    }
    assert bad.normalized is None and bad.dedup_key is None
    assert result.rows[2].errors[0].code == "required"
    assert result.summary() == {
        "valid": 2, "invalid": 2, "duplicate": 0, "conflict": 0, "total": 4, "skipped_blank": 0,
        "columns_not_stored": 0,
    }


@pytest.mark.parametrize("value", ["1e3", "(10)", "1.2.3", "12,34", "NaN", "Infinity", "10 INR", "1,000,00"])
def test_decimal_rejects_anything_not_plain(value):
    (row,) = parse(csv_table(f'A1,1,S,1,"{value}",01-10-2026,\n'), PROFILE).rows
    assert [e.code for e in row.errors] == ["not_decimal"]


@pytest.mark.parametrize(
    "value,expected", [("₹ 1,234.50", "1234.50"), ("Rs. 99", "99"), ("INR 5", "5"), ("-12.00", "-12.00"), ("123,456", "123456")]
)
def test_decimal_accepts_currency_prefix_and_grouping(value, expected):
    (row,) = parse(csv_table(f'A1,1,S,1,"{value}",01-10-2026,\n'), PROFILE).rows
    assert row.normalized["amount"] == Decimal(expected)


@pytest.mark.parametrize(
    "value",
    [
        '=HYPERLINK(""x"")',
        "@SUM(A1)",
        " =1+1",
        "+cmd|' /C calc'!A0",  # DDE payload
        "-2+3+cmd|x",
        "\uff1dHYPERLINK(1)",  # full-width equals sign
        "\u200b=1+1",  # zero-width space before =
    ],
)
def test_formula_like_text_is_rejected(value):
    (row,) = parse(csv_table(f'A1,1,"{value}",1,10,01-10-2026,\n'), PROFILE).rows
    assert [e.code for e in row.errors] == ["formula"]


@pytest.mark.parametrize("field,value", [("Qty", "\u0661"), ("Amount", "\u0661\u0662\u0663"), ("Qty", "\uff11")])
def test_non_ascii_digits_are_not_numbers(field, value):
    qty, amount = ("1", value) if field == "Amount" else (value, "10")
    (row,) = parse(csv_table(f"A1,1,S,{qty},{amount},01-10-2026,\n"), PROFILE).rows
    assert row.status == RowStatus.invalid


def test_negative_numbers_still_allowed_in_number_fields():
    (row,) = parse(csv_table("A1,1,S,-1,-10.50,01-10-2026,\n"), PROFILE).rows
    assert row.normalized["quantity"] == -1 and row.normalized["amount"] == Decimal("-10.50")


def test_ambiguous_date_is_flagged_not_guessed():
    profile = MappingProfile(
        marketplace="meesho",
        report_type="orders",
        version="t",
        fields=(FieldSpec("id", ("ID",)), FieldSpec("d", ("Date",), FieldKind.date, formats=("%d/%m/%Y", "%m/%d/%Y"))),
        dedup_key=("id",),
    )
    result = parse(read_table(b"ID,Date\n1,03/04/2026\n2,25/04/2026\n3,04/04/2026\n", "x.csv"), profile)
    assert [e.code for e in result.rows[0].errors] == ["ambiguous_date"]
    assert result.rows[1].normalized["d"] == dt.date(2026, 4, 25)
    assert result.rows[2].normalized["d"] == dt.date(2026, 4, 4)  # both readings agree


def test_text_length_limit_and_extra_cells():
    long = "x" * 501
    result = parse(csv_table(f"A1,1,{long},1,10,01-10-2026,\nA2,1,S,1,10,01-10-2026,,surprise\n"), PROFILE)
    assert [e.code for e in result.rows[0].errors] == ["too_long"]
    assert [e.code for e in result.rows[1].errors] == ["extra_cells"]
    assert "surprise" not in result.rows[1].raw.values()


def test_blank_rows_are_skipped_and_counted():
    result = parse(csv_table("A1,1,S,1,10,01-10-2026,\n,,,,,,\n\nA2,1,S,1,10,01-10-2026,\n"), PROFILE)
    assert [r.row_number for r in result.rows] == [2, 5]
    assert result.skipped_blank_rows == 2


# --- duplicates ----------------------------------------------------------------


def test_identical_repeat_is_duplicate_and_changed_repeat_is_conflict():
    body = (
        "A1,1,S,1,10,01-10-2026,\n"
        "A1,1,S,1,10.00,01-10-2026,\n"  # same amount written differently: still a duplicate
        "B1,1,S,1,10,01-10-2026,\n"
        "B1,1,S,2,20,01-10-2026,\n"  # same key, different content
        "B1,2,S,1,10,01-10-2026,\n"  # different line: independent
    )
    result = parse(csv_table(body), PROFILE)
    assert statuses(result) == {2: "valid", 3: "duplicate", 4: "conflict", 5: "conflict", 6: "valid"}
    assert result.rows[1].related_rows == [2]
    assert result.rows[2].related_rows == [5]
    assert result.rows[0].dedup_key == ("A1", "1")
    assert result.rows[0].content_hash == result.rows[1].content_hash


def test_parsing_is_deterministic_for_retries():
    content = (HEADER + "A1,1,S,1,10,01-10-2026,\nA2,1,S,1,10,01-10-2026,\n").encode()
    first = parse(read_table(content, "x.csv"), PROFILE)
    again = parse(read_table(content, "renamed.csv"), PROFILE)
    assert [(r.dedup_key, r.content_hash) for r in first.rows] == [(r.dedup_key, r.content_hash) for r in again.rows]


# --- profiles ------------------------------------------------------------------


def test_profile_from_dict_round_trip():
    profile = MappingProfile.from_dict(
        {
            "marketplace": "flipkart",
            "report_type": "returns",
            "version": "2026-10",
            "fields": [
                {"name": "return_id", "headers": ["Return ID"]},
                {"name": "returned_on", "headers": ["Date"], "kind": "date", "formats": ["%Y-%m-%d"]},
            ],
            "dedup_key": ["return_id"],
        }
    )
    assert profile.profile_id == "flipkart/returns@2026-10"
    assert profile.verified is False
    result = parse(read_table(b"Return ID,Date\nR1,2026-10-01\n", "r.csv"), profile)
    assert result.rows[0].normalized == {"return_id": "R1", "returned_on": dt.date(2026, 10, 1)}


@pytest.mark.parametrize(
    "change,message",
    [
        ({"marketplace": "ebay"}, "unknown marketplace"),
        ({"report_type": "misc"}, "unknown report type"),
        ({"dedup_key": []}, "de-duplication key"),
        ({"dedup_key": ["nope"]}, "not defined"),
        ({"dedup_key": ["note"]}, "must be required"),
        ({"fields": [{"name": "a", "headers": ["X"]}, {"name": "b", "headers": [" x "]}], "dedup_key": ["a"]}, "claimed by both"),
        ({"fields": [{"name": "a", "headers": ["X"], "kind": "date"}], "dedup_key": ["a"]}, "must list its formats"),
        ({"fields": [{"name": "Bad Name", "headers": ["X"]}], "dedup_key": ["Bad Name"]}, "invalid field name"),
        ({"fields": [{"name": "a", "headers": ["X"], "kind": "money"}], "dedup_key": ["a"]}, "invalid profile"),
    ],
)
def test_invalid_profiles_are_refused(change, message):
    data = {
        "marketplace": "amazon",
        "report_type": "orders",
        "version": "1",
        "fields": [{"name": "id", "headers": ["ID"]}, {"name": "note", "headers": ["Note"], "required": False}],
        "dedup_key": ["id"],
    }
    data.update(change)
    with pytest.raises(ProfileError, match=message):
        MappingProfile.from_dict(data)


def test_repeated_unmapped_headers_are_listed_but_not_stored():
    header = "Order ID,Line ID,SKU,Qty,Amount,Order Date,Remark,Remark,\n"
    result = parse(csv_table("A1,1,S,1,10,01-10-2026,a,b,c\n", header=header), PROFILE)
    assert result.unmapped_headers == ["Remark", "Remark"]
    assert set(result.rows[0].raw) == {"Order ID", "Line ID", "SKU", "Qty", "Amount", "Order Date"}


# --- personal data (LLD-7 L7-2, AC7-12) ------------------------------------------

PERSONAL_PROFILE = MappingProfile(
    marketplace="amazon",
    report_type="orders",
    version="test-p",
    fields=(
        FieldSpec("order_id", ("Order ID",)),
        FieldSpec("buyer_name", ("Buyer Name",), personal=True),
        FieldSpec("ship_address", ("Ship To Address",), personal=True, required=False),
        FieldSpec("ship_state", ("Ship To State",)),
        FieldSpec("ship_pin", ("Ship To Postal Code",)),
    ),
    dedup_key=("order_id",),
)


def test_personal_and_unmapped_columns_are_never_stored():
    header = "Order ID,Buyer Name,Ship To Address,Ship To State,Ship To Postal Code,Buyer Phone\n"
    body = "A1,Asha Rao,12 MG Road,WEST BENGAL,700001,9800000000\n"
    result = parse(csv_table(body, header=header), PERSONAL_PROFILE)
    (row,) = result.rows
    assert row.status == RowStatus.valid
    assert row.raw == {"Order ID": "A1", "Ship To State": "WEST BENGAL", "Ship To Postal Code": "700001"}
    assert row.normalized == {"order_id": "A1", "ship_state": "WEST BENGAL", "ship_pin": "700001"}
    stored = repr((row.raw, row.normalized, row.errors))
    for value in ("Asha", "MG Road", "9800000000"):
        assert value not in stored
    assert result.personal_headers == ["Buyer Name", "Ship To Address"]
    assert result.unmapped_headers == ["Buyer Phone"]
    assert result.summary()["columns_not_stored"] == 3


def test_a_personal_field_cannot_be_part_of_the_key():
    with pytest.raises(ProfileError, match="cannot be personal"):
        MappingProfile(
            marketplace="amazon",
            report_type="orders",
            version="x",
            fields=(FieldSpec("buyer", ("Buyer",), personal=True),),
            dedup_key=("buyer",),
        )


def test_from_dict_reads_the_personal_flag():
    profile = MappingProfile.from_dict(
        {
            "marketplace": "meesho",
            "report_type": "orders",
            "version": "1",
            "fields": [{"name": "id", "headers": ["ID"]}, {"name": "name", "headers": ["Name"], "personal": True}],
            "dedup_key": ["id"],
        }
    )
    assert profile.by_name["name"].personal and not profile.by_name["id"].personal
