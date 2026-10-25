import csv
import io
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from platform_common.clock import FrozenClock, get_clock
from platform_common.csv_export import safe_cell, to_csv
from platform_common.errors import install_error_handlers
from platform_common.paging import DateRange, PageParams, date_range, page_params


@pytest.mark.parametrize("raw", ["=SUM(A1:A2)", "+91 98", "-2+3", "@cmd", "\tx", "\rx", "=HYPERLINK(\"http://x\")"])
def test_formula_like_text_is_neutralised(raw):
    assert safe_cell(raw) == "'" + raw


def test_numbers_and_plain_text_are_untouched():
    assert safe_cell(Decimal("-12.50")) == "-12.50"
    assert safe_cell(-3) == "-3"
    assert safe_cell("Shampoo 200ml") == "Shampoo 200ml"
    assert safe_cell(None) == ""
    assert safe_cell(date(2026, 10, 14)) == "2026-10-14"


def test_floats_are_refused():
    with pytest.raises(TypeError):
        safe_cell(1.5)


def test_to_csv_round_trips_and_quotes():
    out = to_csv(["sku", "name", "amount"], [["A,1", "=cmd|' /C calc'!A0", Decimal("10.00")]])
    rows = list(csv.reader(io.StringIO(out)))
    assert rows == [["sku", "name", "amount"], ["A,1", "'=cmd|' /C calc'!A0", "10.00"]]


def test_to_csv_rejects_ragged_rows():
    with pytest.raises(ValueError):
        to_csv(["a", "b"], [[1]])


# 20:00 UTC on 23 Oct is already 24 Oct in India.
NOW = datetime(2026, 10, 23, 20, 0, tzinfo=UTC)


def _client():
    app = FastAPI()
    install_error_handlers(app)
    app.dependency_overrides[get_clock] = lambda: FrozenClock(NOW)

    @app.get("/x")
    def x(page: PageParams = Depends(page_params), dates: DateRange = Depends(date_range)):
        return {"limit": page.limit, "offset": page.offset, "from": dates.date_from, "to": dates.date_to}

    return TestClient(app)


def test_paging_defaults_and_bounds():
    c = _client()
    # No dates given: the longest allowed window, ending today in India.
    assert c.get("/x").json() == {"limit": 50, "offset": 0, "from": "2025-10-24", "to": "2026-10-24"}
    assert c.get("/x?limit=200&offset=10").status_code == 200
    for bad in ("limit=0", "limit=201", "offset=-1"):
        assert c.get(f"/x?{bad}").status_code == 422


def test_date_range_rules():
    c = _client()
    assert c.get("/x?from=2026-04-01&to=2026-04-01").status_code == 200
    assert c.get("/x?from=2026-04-02&to=2026-04-01").status_code == 422
    assert c.get("/x?from=2025-04-01&to=2026-04-01").status_code == 200  # 366 days inclusive
    assert c.get("/x?from=2025-03-31&to=2026-04-01").status_code == 422  # 367
    assert c.get("/x?from=not-a-date").status_code == 422
    r = c.get("/x?from=2026-04-02&to=2026-04-01")
    assert r.json()["error"] == {"code": "date_range_reversed", "message": "'from' is after 'to'", "field": "from"}


def test_date_range_fills_the_missing_end():
    c = _client()
    assert c.get("/x?from=2026-04-01").json()["to"] == "2026-10-24"
    assert c.get("/x?to=2026-03-31").json()["from"] == "2025-03-31"
    # An old 'from' with no 'to' is still refused rather than silently cut.
    assert c.get("/x?from=2024-01-01").status_code == 422
