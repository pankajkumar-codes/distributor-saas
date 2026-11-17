"""Every section's typed API row accepts what the build's row class produces (a renamed field would be a 500 at runtime)."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.filing import api
from app.modules.filing.gstr1.model import B2BRow, B2CLRow, B2CSRow, CDNRRow, CDNURRow, HSNRow, Amounts

A = Amounts(Decimal("100.00"), Decimal("5.00"), Decimal(), Decimal(), Decimal())
D = date(2026, 10, 5)
REFS = ("a.xlsx row 2",)
ROWS = {
    "b2b": B2BRow("27DEMOB5678B1ZH", None, "INV-1", D, Decimal("105.00"), "27", Decimal("5"), A, REFS),
    "b2cl": B2CLRow("INV-2", D, Decimal("300000.00"), "27", Decimal("5"), A, REFS),
    "b2cs": B2CSRow("27", Decimal("5"), A, REFS),
    "cdnr": CDNRRow("27DEMOB5678B1ZH", "Acme", "CN-1", D, Decimal("105.00"), "27", Decimal("5"), A, "INV-1", D, REFS),
    "cdnur": CDNURRow("CN-2", D, Decimal("105.00"), "27", Decimal("5"), A, None, None, REFS),
    "hsn_b2b": HSNRow("61091000", "PCS", Decimal("5"), Decimal("2.000"), A, REFS),
    "hsn_b2c": HSNRow("61091000", "PCS", Decimal("5"), Decimal("2.000"), A, REFS),
}


def test_the_seven_sections_are_the_seven_pages():
    assert set(ROWS) == set(api.SECTIONS) == set(api._PAGES)


@pytest.mark.parametrize("section", api.SECTIONS)
def test_a_build_row_fits_its_typed_page_and_keeps_money_as_strings(section):
    page = api._PAGES[section](
        section=section, rows=[api._row(ROWS[section])], has_more=False, next_cursor=None, fingerprint="fp"
    )
    row = page.model_dump()["rows"][0]
    assert row["taxable_value"] == "100.00" and row["igst"] == "5.00" and row["source_refs"] == ["a.xlsx row 2"]
    assert all(not isinstance(v, (float, Decimal)) for v in row.values())
