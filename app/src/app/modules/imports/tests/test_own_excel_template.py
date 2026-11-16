"""The own-invoice template (R1-M5 slice 2): built from the reader's columns, read back by the reader, no
values in it, and served on a route that follows the section's permissions. The route tests need PG_ADMIN_URL."""

import io

import openpyxl
import pytest

from app.modules.imports import readers, template
from app.modules.imports.parsing import RowStatus, parse, read_table
from app.modules.imports.readers import register_readers
from app.modules.imports.readers.own_excel import COLUMNS, SHEET, OwnExcelReader

from .conftest import PG_ADMIN_URL
from .fixtures import own_excel as fx
from .test_uploads_postgres import get, run_jobs, shop, upload  # noqa: F401  (the shop fixture)

XLSX = template.CONTENT_TYPE


def workbook():
    return openpyxl.load_workbook(io.BytesIO(template.build()))


def test_the_template_has_the_invoices_sheet_with_exactly_the_readers_headers_and_no_values():
    wb = workbook()
    assert wb.sheetnames == [SHEET, template.HELP_SHEET]
    rows = list(wb[SHEET].iter_rows(values_only=True))
    assert rows == [tuple(c.header for c in COLUMNS)]  # a header row and nothing else


def test_the_reader_claims_the_template_and_reads_no_rows_from_it():
    reader = OwnExcelReader()
    table = read_table(template.build(), "own-invoices-template.xlsx", sheet=SHEET)
    assert reader.detect(table) and not reader.has_rows(table)
    result = parse(table, reader.profile())
    assert result.rows == [] and result.unmapped_headers == []


def test_a_filled_template_reads_through_the_reader():
    wb = workbook()
    ws = wb[SHEET]
    line = fx.line("INV-1")
    ws.append([line[c.header] for c in COLUMNS])
    out = io.BytesIO()
    wb.save(out)
    result = parse(read_table(out.getvalue(), "t.xlsx", sheet=SHEET), OwnExcelReader().profile())
    assert [r.status for r in result.rows] == [RowStatus.valid]


def test_the_how_to_sheet_names_every_column_and_every_unsupported_case_in_plain_words():
    text = "\n".join(" ".join(str(c) for c in row if c) for row in workbook()[template.HELP_SHEET].iter_rows(values_only=True))
    for column in COLUMNS:
        assert column.header in text
    for case in ("Exports", "Special Economic Zone", "reverse charge", "Advances", "Nil-rated", "e-commerce operator"):
        assert case in text
    assert "Do not enter any of these as ordinary rows" in text
    assert "not supported" in text.lower()


def test_the_template_suggests_no_gst_rate_anywhere():
    import re

    cells = [str(c) for ws in workbook().worksheets for row in ws.iter_rows(values_only=True) for c in row if c]
    assert not [c for c in cells if re.search(r"\d", c)], "a digit in the template could read as a suggested rate"


def test_the_document_type_cell_offers_exactly_the_three_types():
    validations = workbook()[SHEET].data_validations.dataValidation
    assert len(validations) == 1 and validations[0].formula1 == '"Invoice,Credit note,Debit note"'


pytestmark_pg = pytest.mark.skipif(not PG_ADMIN_URL, reason="PG_ADMIN_URL not set")


@pytest.fixture()
def real_readers():
    readers.clear_for_tests()
    register_readers()
    yield
    readers.clear_for_tests()


@pytestmark_pg
def test_the_route_serves_the_template_to_owner_admin_and_ca_and_hides_it_from_billing_and_strangers(shop):  # noqa: F811
    pg, biz, _ = shop
    path = f"/api/v1/b/{biz}/uploads/own-invoices-template"
    for sub in ("alice", "adam", "cathy"):
        r = get(pg, path, sub=sub)
        assert r.status_code == 200, sub
        assert r.headers["content-type"] == XLSX
        assert 'filename="own-invoices-template.xlsx"' in r.headers["content-disposition"]
        assert openpyxl.load_workbook(io.BytesIO(r.content)).sheetnames == [SHEET, template.HELP_SHEET]
    for sub in ("bill", "stranger"):
        assert get(pg, path, sub=sub).status_code == 404


@pytestmark_pg
def test_another_business_cannot_use_this_businesss_path(shop):  # noqa: F811
    from .conftest import new_business

    pg, biz, _ = shop
    other = new_business(pg, "olivia")
    assert get(pg, f"/api/v1/b/{biz}/uploads/own-invoices-template", sub="olivia").status_code == 404
    assert get(pg, f"/api/v1/b/{other}/uploads/own-invoices-template", sub="olivia").status_code == 200


@pytestmark_pg
def test_the_blank_template_uploads_as_an_empty_run_and_the_section_is_enabled(shop, real_readers):  # noqa: F811
    pg, biz, _ = shop
    upload_id, _ = upload(shop, "own_invoices_excel", "own-invoices-template.xlsx", template.build(), XLSX)
    assert run_jobs(shop) == ["done"]
    out = get(pg, f"/api/v1/b/{biz}/uploads/{upload_id}").json()
    assert (out["status"], out["reject_reason"]) == ("parsed", None)
    sections = {s["section"]: s for s in get(pg, f"/api/v1/b/{biz}/upload-sections").json()["sections"]}
    assert sections["own_invoices_excel"]["enabled"] is True and sections["own_invoices_pdf"]["enabled"] is True
    assert "Excel template" in (sections["own_invoices_excel"]["requirement_note"] or "")
