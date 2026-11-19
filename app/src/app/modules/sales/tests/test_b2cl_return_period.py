"""#362: the B2C-large limit is chosen by the GSTR-1 return period, not the document date (CA expert v4).
Rs 2.5 lakh applies to return periods up to July 2024, Rs 1 lakh from August 2024 ('more than')."""

from datetime import date
from decimal import Decimal

import pytest

from app.modules.filing import periods
from app.modules.sales.compute import inputs

from .test_filing_lines import b2cl_threshold

D = Decimal
G = "19AAACX1111A1Z2"


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
    month = periods.gstr1_period_month(None, G, doc_date)
    assert b2cl_threshold(month) == D(expected_limit)


def test_a_july_document_in_an_august_return_gets_the_lower_limit(frequency):
    frequency("quarterly")
    by_doc_date = b2cl_threshold(date(2024, 7, 31))
    by_return = b2cl_threshold(periods.gstr1_period_month(None, G, date(2024, 7, 31)))
    assert (by_doc_date, by_return) == (D("250000.00"), D("100000.00"))


def test_an_august_document_in_a_july_return_would_keep_the_higher_limit():
    # The reverse: a return period up to July 2024 uses 2.5 lakh whatever date within it the document carries.
    assert b2cl_threshold(date(2024, 7, 1)) == D("250000.00")
    assert b2cl_threshold(date(2024, 8, 1)) == D("100000.00")


def test_rules_read_the_limit_on_the_return_period(monkeypatch, frequency):
    frequency("quarterly")
    seen = {}

    def fake_value_on(tx, key, on):
        seen[key] = on
        return {"invoice.rounding_mode": "x", "invoice.round_off_line": "x", "gst.utgst_state_codes": "",
                "gstr1.b2cl_threshold": D("1"), "invoice.unregistered_address_threshold": D("1"),
                "eway.consignment_value_threshold": D("1")}[key]

    monkeypatch.setattr(inputs, "value_on", fake_value_on)
    inputs._rules(None, date(2024, 7, 31), G)
    assert seen["gstr1.b2cl_threshold"] == date(2024, 9, 1)
    assert seen["invoice.rounding_mode"] == date(2024, 7, 31)  # other rules stay on the document date
