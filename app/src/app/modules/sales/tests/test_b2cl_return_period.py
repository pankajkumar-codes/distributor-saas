"""#362: sales compute reads the B2C-large limit on the GSTR-1 return period, not the document date."""

from datetime import date
from decimal import Decimal

from app.modules.sales.compute import inputs

D = Decimal


def test_rules_read_the_limit_on_the_return_period(monkeypatch):
    seen = {}

    def fake_value_on(tx, key, on):
        seen[key] = on
        return {
            "invoice.rounding_mode": "x",
            "invoice.round_to_rupee": "x",
            "gst.utgst_state_codes": "",
            "gstr1.b2cl_threshold": D("1"),
            "invoice.unregistered_address_threshold": D("1"),
            "eway.consignment_value_threshold": D("1"),
        }[key]

    monkeypatch.setattr(inputs, "value_on", fake_value_on)
    monkeypatch.setattr(inputs, "gstr1_period_month", lambda tx, g, on: date(2024, 9, 1))
    inputs._rules(None, date(2024, 7, 31), "19AAACX1111A1Z2")
    assert seen["gstr1.b2cl_threshold"] == date(2024, 9, 1)
    assert seen["invoice.rounding_mode"] == date(2024, 7, 31)  # other rules stay on the document date
