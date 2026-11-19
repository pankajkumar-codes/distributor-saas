"""#362: the date that dated GSTR-1 rules are looked up on is the return period's, not the document date's."""

from datetime import date
from decimal import Decimal

import pytest
import yaml
from pathlib import Path

from app.modules.filing import periods

D = Decimal
G = "19AAACX1111A1Z2"
REFDATA = Path(__file__).resolve().parents[6] / "refdata" / "values" / "gstr1.yaml"


def b2cl_threshold(on: date) -> Decimal:
    rows = [
        r
        for r in yaml.safe_load(REFDATA.read_text())
        if r["key"] == "gstr1.b2cl_threshold"
        and r["valid_from"] <= on
        and (r["valid_to"] is None or on < r["valid_to"])
    ]
    assert len(rows) == 1, rows
    return D(rows[0]["value"])


class _Freq:
    def __init__(self, frequency):
        self.frequency = frequency


@pytest.fixture
def frequency(monkeypatch):
    def set_(value):
        monkeypatch.setattr(periods, "filing_frequency_on", lambda tx, g, on: None if value is None else _Freq(value))

    return set_


@pytest.mark.parametrize(
    "freq, doc_date, expected_limit",
    [
        ("monthly", date(2024, 7, 31), "250000.00"),  # July return
        ("monthly", date(2024, 8, 1), "100000.00"),  # August return
        ("quarterly", date(2024, 7, 31), "100000.00"),  # the Jul-Sep return is an August-or-later period
        ("quarterly", date(2024, 4, 15), "250000.00"),  # the Apr-Jun return
        ("quarterly", date(2024, 9, 30), "100000.00"),
        (None, date(2024, 7, 31), "250000.00"),  # no frequency yet: the document's own month
    ],
)
def test_limit_follows_the_return_period(frequency, freq, doc_date, expected_limit):
    frequency(freq)
    assert b2cl_threshold(periods.gstr1_period_month(None, G, doc_date)) == D(expected_limit)


def test_a_july_document_in_an_august_return_gets_the_lower_limit(frequency):
    frequency("quarterly")
    d = date(2024, 7, 31)
    assert (b2cl_threshold(d), b2cl_threshold(periods.gstr1_period_month(None, G, d))) == (
        D("250000.00"),
        D("100000.00"),
    )


def test_a_return_up_to_july_keeps_the_higher_limit_whatever_the_day(frequency):
    frequency("monthly")
    assert b2cl_threshold(periods.gstr1_period_month(None, G, date(2024, 7, 1))) == D("250000.00")
