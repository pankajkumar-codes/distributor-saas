"""scripts/check_reader.py (R1-M4): the local report checker prints header matches and row counts, never a cell
value, and writes nothing. Runs it on synthetic files only."""

import subprocess
import sys
from pathlib import Path

from app.modules.imports.tests.fixtures import amazon as fxa
from app.modules.imports.tests.fixtures import flipkart as fxf
from app.modules.imports.tests.fixtures import meesho as fxm

ROOT = Path(__file__).resolve().parents[6]
SCRIPT = ROOT / "scripts" / "check_reader.py"


def run(tmp_path, name, content, *extra):
    path = tmp_path / name
    path.write_bytes(content)
    before = {p for p in tmp_path.iterdir()}
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(path), *extra], capture_output=True, text=True,
                          cwd=tmp_path)
    assert {p for p in tmp_path.iterdir()} == before  # it wrote nothing
    return done


def assert_no_values(output):
    for secret in (fxa.OWN, fxa.OTHER, "Made Up Buyer", "Made Up Lane", "ORD-1", "ITEM-1", "OI-1", "OD-1",
                   "INV-1", "SO-1_1", "Made Up Supplier", "CN-1", "9999"):
        assert secret not in output, secret


def test_an_amazon_zip_is_claimed_and_counted_without_showing_a_value(tmp_path):
    z = fxa.zipped({"MTR_B2C-JUL-2026.csv": fxa.b2c_held(), "MTR_B2B-JUL-2026.csv": fxa.b2b_good()})
    done = run(tmp_path, "july.zip", z)
    assert done.returncode == 0, done.stdout + done.stderr
    out = done.stdout
    assert "Reader: amazon_mtr_b2c_v1" in out and "Reader: amazon_mtr_b2b_v1" in out
    assert "headers found" in out and "Held by reason: blank_hsn 1" in out
    assert_no_values(out)


def test_a_flipkart_workbook_reads_each_named_sheet(tmp_path):
    done = run(tmp_path, "Sales Report - Jul 2026.xlsx", fxf.good())
    assert done.returncode == 0, done.stdout
    assert "Reader: flipkart_sales_v1" in done.stdout and "Reader: flipkart_cashback_v1" in done.stdout
    assert "cashback_adjustment 2" in done.stdout
    assert_no_values(done.stdout)


def test_a_meesho_zip_and_a_missing_header_is_named(tmp_path):
    sales = fxm.workbook([fxm.sale("1")], headers=[h for h in fxm.SALES_HEADERS if h != "taxable_shipping"])
    done = run(tmp_path, "m.zip", fxa.zipped({"tcs_sales.xlsx": sales}))
    assert done.returncode == 0, done.stdout
    assert "missing: 'taxable_shipping'" in done.stdout
    assert_no_values(done.stdout)


def test_a_file_no_reader_claims_exits_with_one_and_a_bad_file_with_two(tmp_path):
    assert run(tmp_path, "x.csv", b"a,b\n1,2\n").returncode == 1
    assert run(tmp_path, "y.csv", b"\xff\xfe\x00").returncode == 2


def test_show_headers_lists_unused_column_names_only(tmp_path):
    z = fxa.zipped({"MTR_B2C-JUL-2026.csv": fxa.b2c_held()})
    plain = run(tmp_path, "a.zip", z)
    done = run(tmp_path, "b.zip", z, "--show-headers")
    assert "not used:" not in plain.stdout
    assert done.returncode == 0 and "Columns in the file that the reader does not use" in done.stdout
    assert_no_values(done.stdout)


def test_a_workbook_with_several_sheets_never_shows_a_sheet_name_or_file_name(tmp_path):
    import io

    import openpyxl

    wb = openpyxl.Workbook()
    wb.active.title = "SUPPLIER-778899"
    wb.create_sheet("OTHER-SHEET-X")
    buf = io.BytesIO()
    wb.save(buf)
    done = run(tmp_path, "tcs_sales-ACCT-5551234.xlsx", buf.getvalue())
    assert done.returncode == 2
    assert "could not be read" in done.stdout
    for name in ("SUPPLIER-778899", "OTHER-SHEET-X", "ACCT-5551234", "tcs_sales"):
        assert name not in done.stdout + done.stderr
